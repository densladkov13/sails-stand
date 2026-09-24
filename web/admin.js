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
      case "config_updated":
        loadYachts();
        break;
      case "error":
        showToast(data.message || "Произошла ошибка");
        break;
    }
  }

  loadYachts();
  connect();
})();
