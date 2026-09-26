// web/admin.js
// Панель оператора SAILS: статус связи каждой яхты (подключена ли она сама
// и подключён ли компьютер на её борту), последние сообщения, быстрая
// отправка тестового сообщения и сброс истории — отдельная страница,
// не связанная со стендом визуально (стенд её никак не показывает).

(() => {
  "use strict";

  const connDot = document.getElementById("conn-dot");
  const busyBanner = document.getElementById("busy-banner");
  const cardsEl = document.getElementById("yacht-cards");
  const toastEl = document.getElementById("toast");
  const standUpdateBtn = document.getElementById("stand-update-btn");
  const standUpdateHint = document.getElementById("stand-update-hint");

  let ws = null;
  let reconnectDelay = 1000;
  let yachts = []; // полный список из /api/settings (включая выключенные)
  const stateById = {}; // { online, thinking, lastViewer, lastYacht }
  const cardsById = {};
  let serverBusy = false;

  let toastTimer = null;
  function showToast(msg) {
    toastEl.textContent = msg;
    toastEl.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { toastEl.hidden = true; }, 3500);
  }

  function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
  }

  async function loadYachts() {
    try {
      const resp = await fetch("/api/settings");
      const cfg = await resp.json();
      yachts = cfg.yachts || [];
      yachts.forEach((y) => {
        if (!stateById[y.id]) stateById[y.id] = { online: false, thinking: false, lastViewer: null, lastYacht: null };
      });
      renderCards();
    } catch (e) {
      showToast("Не удалось загрузить список яхт");
    }
  }

  function renderCards() {
    cardsEl.innerHTML = "";
    yachts.forEach((y) => {
      const state = stateById[y.id];
      const enabled = y.enabled !== false;

      const card = document.createElement("div");
      card.className = "yacht-card" + (enabled ? "" : " disabled");
      card.innerHTML = `
        <div class="yacht-card-head">
          <span class="icon">${y.icon || "⛵"}</span>
          <span class="name">${escapeHtml(y.name || y.id)}</span>
          <span class="badge ${enabled ? "on" : "off"}">${enabled ? "включена" : "выключена"}</span>
        </div>
        <div class="status-row">
          <span class="status-pill"><span class="dot online-dot"></span>Компьютер на яхте</span>
          <span class="status-pill"><span class="dot thinking-dot"></span>Думает</span>
        </div>
        <div class="last-messages">
          <div class="empty">Сообщений ещё не было</div>
        </div>
        <div class="card-actions">
          <input type="text" placeholder="Тестовое сообщение..." maxlength="180" />
          <div class="action-row">
            <button class="btn-send">Отправить</button>
            <button class="btn-clear">Очистить историю</button>
          </div>
        </div>
      `;
      cardsEl.appendChild(card);
      cardsById[y.id] = card;

      const input = card.querySelector("input");
      const sendBtn = card.querySelector(".btn-send");
      const clearBtn = card.querySelector(".btn-clear");

      function doSend() {
        const text = input.value.trim();
        if (!text || !enabled) return;
        sendWS({ type: "user_message", yacht_id: y.id, text });
        input.value = "";
      }
      sendBtn.addEventListener("click", doSend);
      input.addEventListener("keydown", (e) => { if (e.key === "Enter") doSend(); });
      clearBtn.addEventListener("click", () => {
        if (!window.confirm(`Очистить историю «${y.name || y.id}»?`)) return;
        sendWS({ type: "reset_history", yacht_id: y.id });
      });

      if (!enabled) {
        input.disabled = true;
        sendBtn.disabled = true;
        input.placeholder = "Яхта выключена в настройках";
      }
    });
    yachts.forEach((y) => refreshCard(y.id));
  }

  function refreshCard(yachtId) {
    const card = cardsById[yachtId];
    const state = stateById[yachtId];
    if (!card || !state) return;

    card.querySelector(".online-dot").classList.toggle("on", state.online);
    card.querySelector(".thinking-dot").classList.toggle("thinking", state.thinking);

    const box = card.querySelector(".last-messages");
    if (!state.lastViewer && !state.lastYacht) {
      box.innerHTML = `<div class="empty">Сообщений ещё не было</div>`;
      return;
    }
    box.innerHTML = "";
    if (state.lastViewer) {
      box.innerHTML += `<div class="line"><span class="who">Зритель:</span><span class="txt">${escapeHtml(state.lastViewer)}</span></div>`;
    }
    if (state.lastYacht) {
      box.innerHTML += `<div class="line"><span class="who">Яхта:</span><span class="txt">${escapeHtml(state.lastYacht)}</span></div>`;
    }
  }

  function applyHistory(historyMap) {
    Object.entries(historyMap || {}).forEach(([yachtId, events]) => {
      if (!stateById[yachtId]) stateById[yachtId] = { online: false, thinking: false, lastViewer: null, lastYacht: null };
      events.forEach((ev) => {
        if (ev.sender === "viewer") stateById[yachtId].lastViewer = ev.text;
        else stateById[yachtId].lastYacht = ev.text;
      });
    });
  }

  function connect() {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    ws = new WebSocket(`${proto}://${location.host}/ws`);

    ws.onopen = () => {
      connDot.classList.add("online");
      reconnectDelay = 1000;
    };
    ws.onclose = () => {
      connDot.classList.remove("online");
      setTimeout(connect, reconnectDelay);
      reconnectDelay = Math.min(reconnectDelay * 1.6, 15000);
    };
    ws.onerror = () => ws.close();
    ws.onmessage = (event) => handleMessage(JSON.parse(event.data));
  }

  function sendWS(payload) {
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(payload));
  }

  function handleMessage(data) {
    switch (data.type) {
      case "init":
        applyHistory(data.history);
        Object.entries(data.yacht_online || {}).forEach(([id, online]) => {
          if (!stateById[id]) stateById[id] = { online: false, thinking: false, lastViewer: null, lastYacht: null };
          stateById[id].online = !!online;
        });
        serverBusy = !!data.busy;
        busyBanner.hidden = !serverBusy;
        renderCards();
        break;
      case "chat_update": {
        const s = stateById[data.yacht_id];
        if (!s) return;
        if (data.sender === "viewer") s.lastViewer = data.text;
        else s.lastYacht = data.text;
        refreshCard(data.yacht_id);
        break;
      }
      case "status": {
        const s = stateById[data.yacht_id];
        if (!s) return;
        s.thinking = data.state === "thinking";
        refreshCard(data.yacht_id);
        break;
      }
      case "yacht_online": {
        if (!stateById[data.yacht_id]) stateById[data.yacht_id] = { online: false, thinking: false, lastViewer: null, lastYacht: null };
        stateById[data.yacht_id].online = !!data.online;
        refreshCard(data.yacht_id);
        break;
      }
      case "busy":
        serverBusy = !!data.busy;
        busyBanner.hidden = !serverBusy;
        break;
      case "history_cleared": {
        const s = stateById[data.yacht_id];
        if (s) { s.lastViewer = null; s.lastYacht = null; }
        refreshCard(data.yacht_id);
        showToast("История очищена");
        break;
      }
      case "yacht_update_result":
        if (!data.ok) showToast("Обновление яхт не удалось: " + data.output);
        else if (data.changed) showToast("Компьютер яхт обновился (" + data.output + ") и перезапускается");
        else showToast("Компьютер яхт уже на последней версии (" + data.output + ")");
        break;
      case "config_updated":
        loadYachts();
        break;
      case "error":
        showToast(data.message || "Произошла ошибка");
        break;
    }
  }

  // ---------- Обновление кода (git pull) ----------
  standUpdateBtn.addEventListener("click", async () => {
    if (!window.confirm("Обновить стенд? Сервер перезапустится (5-8 секунд); если сейчас идёт разговор со зрителем, он прервётся.")) return;
    standUpdateBtn.disabled = true;
    const prevHint = standUpdateHint.textContent;
    standUpdateHint.textContent = "Обновляю...";
    try {
      const resp = await fetch("/api/update", { method: "POST" });
      const data = await resp.json();
      if (data.ok && data.restarting) {
        standUpdateHint.textContent = "Обновлено, сервер перезапускается — страница переподключится сама через несколько секунд.";
        showToast("Стенд обновляется и перезапускается...");
      } else if (data.ok) {
        standUpdateHint.textContent = prevHint;
        showToast("Уже последняя версия — обновлять нечего");
      } else {
        standUpdateHint.textContent = prevHint;
        showToast("Ошибка обновления: " + (data.output || "").slice(0, 200));
      }
    } catch (e) {
      standUpdateHint.textContent = prevHint;
      showToast("Не удалось обратиться к серверу");
    } finally {
      standUpdateBtn.disabled = false;
    }
  });

  document.getElementById("yacht-update-btn").addEventListener("click", () => {
    if (!Object.values(stateById).some((st) => st.online)) {
      showToast("Компьютер яхт сейчас не подключён");
      return;
    }
    if (!window.confirm("Обновить компьютер яхт? Он ненадолго отключится и перезапустится.")) return;
    sendWS({ type: "trigger_yacht_update" });
    showToast("Команда обновления отправлена компьютеру яхт");
  });

  // ---------- Настройки (раньше были отдельным окном на стенде) ----------
  const $ = (id) => document.getElementById(id);
  const settingsYachtsEl = $("settings-yachts");

  function escapeAttr(str) {
    return escapeHtml(str).replace(/"/g, "&quot;");
  }

  async function loadSettingsForm() {
    try {
      const resp = await fetch("/api/settings");
      const cfg = await resp.json();
      $("set-wpm").value = cfg.morse?.wpm ?? 20;
      $("set-tone").value = cfg.morse?.tone_hz ?? 600;
      $("set-model").value = cfg.openrouter?.model ?? "";
      $("set-temp").value = cfg.openrouter?.temperature ?? 0.9;
      $("set-max-tokens").value = cfg.openrouter?.max_tokens ?? 70;
      $("set-min-delay").value = cfg.min_reply_delay_seconds ?? 0.5;
      $("set-history").value = cfg.max_history_length ?? 10;
      $("set-common-prompt").value = cfg.system_prompt_common ?? "";

      settingsYachtsEl.innerHTML = "";
      (cfg.yachts || []).forEach((y) => {
        const card = document.createElement("div");
        card.className = "yacht-settings-card";
        card.dataset.yachtId = y.id;
        card.innerHTML = `
          <div class="field-row">
            <label class="field icon-field"><span>Значок</span>
              <input type="text" class="set-yacht-icon" value="${escapeAttr(y.icon || "⛵")}" maxlength="4" /></label>
            <label class="field"><span>Имя яхты</span>
              <input type="text" class="set-yacht-name" value="${escapeAttr(y.name || y.id)}" maxlength="40" /></label>
          </div>
          <label class="field-checkbox">
            <input type="checkbox" class="set-yacht-enabled" ${y.enabled !== false ? "checked" : ""} />
            <span>Активна на стенде (показывается зрителям)</span>
          </label>
          <label class="field"><span>Характер / системный промпт</span>
            <textarea class="field-textarea set-yacht-prompt" rows="7">${escapeHtml(y.system_prompt || "")}</textarea></label>
        `;
        settingsYachtsEl.appendChild(card);
      });
    } catch (e) {
      showToast("Не удалось загрузить настройки");
    }
  }

  async function saveSettings() {
    const yachtsPayload = [...settingsYachtsEl.querySelectorAll(".yacht-settings-card")].map((card) => ({
      id: card.dataset.yachtId,
      icon: card.querySelector(".set-yacht-icon").value,
      name: card.querySelector(".set-yacht-name").value,
      system_prompt: card.querySelector(".set-yacht-prompt").value,
      enabled: card.querySelector(".set-yacht-enabled").checked,
    }));
    const payload = {
      morse: { wpm: Number($("set-wpm").value), tone_hz: Number($("set-tone").value) },
      openrouter: {
        model: $("set-model").value,
        temperature: Number($("set-temp").value),
        max_tokens: Number($("set-max-tokens").value),
      },
      max_history_length: Number($("set-history").value),
      min_reply_delay_seconds: Number($("set-min-delay").value),
      system_prompt_common: $("set-common-prompt").value,
      yachts: yachtsPayload,
    };
    try {
      const resp = await fetch("/api/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!resp.ok) throw new Error("bad response");
      await resp.json();
      showToast("Настройки сохранены и применены");
      loadSettingsForm();
    } catch (e) {
      showToast("Не удалось сохранить настройки");
    }
  }

  $("settings-save").addEventListener("click", saveSettings);
  $("settings-reload").addEventListener("click", () => { loadSettingsForm(); showToast("Изменения отменены"); });

  loadYachts();
  loadSettingsForm();
  connect();
})();
