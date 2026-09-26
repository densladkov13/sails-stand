// web/app.js
// Логика стенда SAILS: WebSocket-соединение, чат с тремя яхтами (переключение
// вкладками), визуализация азбуки Морзе осциллограммой (canvas) + звук через
// Web Audio API, и панель настроек по клавише S.

(() => {
  "use strict";

  const yachtNavEl = document.getElementById("yacht-nav");
  const chatLogContainer = document.getElementById("chat-log-container");
  const textInput = document.getElementById("text-input");
  const sendBtn = document.getElementById("send-btn");
  const keyboardEl = document.getElementById("keyboard");
  const toastEl = document.getElementById("toast");

  let ws = null;
  let reconnectDelay = 1000;
  let yachts = [];
  let activeYachtId = null;
  let morseSettings = { wpm: 20, tone_hz: 600 };
  let serverBusy = false; // на стенде уже идёт обмен репликами с какой-то яхтой
  let onlineById = {}; // подключён ли компьютер на этой яхте по Wi-Fi прямо сейчас

  const tabsById = {};
  const chatLogsById = {};
  const stateById = {}; // { thinking: bool, unread: bool }

  const COLOR_VIEWER_ON = "#0b2545";
  const COLOR_VIEWER_MUTE = "#c7ccd4";
  const COLOR_YACHT_ON = "#e9c477";
  const COLOR_YACHT_MUTE = "rgba(255,255,255,0.28)";

  // ---------- Toast ----------
  let toastTimer = null;
  function showToast(message) {
    toastEl.textContent = message;
    toastEl.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { toastEl.hidden = true; }, 4000);
  }

  // ---------- WebSocket ----------
  function connect() {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    ws = new WebSocket(`${proto}://${location.host}/ws`);

    ws.onopen = () => {
      reconnectDelay = 1000;
    };
    ws.onclose = () => {
      setTimeout(connect, reconnectDelay);
      reconnectDelay = Math.min(reconnectDelay * 1.6, 15000);
    };
    ws.onerror = () => ws.close();
    ws.onmessage = (event) => handleServerMessage(JSON.parse(event.data));
  }

  function sendWS(payload) {
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(payload));
  }

  function handleServerMessage(data) {
    switch (data.type) {
      case "init": {
        onlineById = data.yacht_online || {};
        applyPublicConfig(data);
        Object.entries(data.history || {}).forEach(([yachtId, events]) => {
          events.forEach((ev) => appendBubble(yachtId, ev, true));
        });
        serverBusy = !!data.busy;
        updateInputLock();
        break;
      }
      case "config_updated":
        applyPublicConfig(data);
        break;
      case "yacht_online":
        onlineById[data.yacht_id] = !!data.online;
        refreshOnlineIndicators();
        break;
      case "chat_update":
        queuePlayback(data);
        break;
      case "status":
        setThinking(data.yacht_id, data.state === "thinking");
        break;
      case "history_cleared":
        clearYachtLog(data.yacht_id);
        break;
      case "busy":
        serverBusy = !!data.busy;
        updateInputLock();
        break;
      case "error":
        showToast(data.message || "Произошла ошибка");
        break;
    }
  }

  // ---------- Яхты: боковой список + журналы ----------
  function applyPublicConfig(data) {
    document.title = data.stand.title ? `${data.stand.title} — Стенд` : "SAILS — Стенд";
    morseSettings = data.morse || morseSettings;
    syncYachts(data.yachts || [], data.history);
  }

  // Полностью пересобирает список яхт слева и их журналы по актуальному
  // списку видимых (enabled) яхт — так включение/выключение яхты в настройках
  // сразу добавляет или убирает её со стенда, без перезагрузки страницы.
  // Журналы существующих яхт переиспользуются (не теряем историю на экране).
  function syncYachts(newYachts, historyMap) {
    const previousActiveId = activeYachtId;
    const oldChatLogs = { ...chatLogsById };
    const oldState = { ...stateById };

    Object.keys(tabsById).forEach((id) => delete tabsById[id]);
    Object.keys(chatLogsById).forEach((id) => delete chatLogsById[id]);
    Object.keys(stateById).forEach((id) => delete stateById[id]);

    yachtNavEl.innerHTML = "";
    chatLogContainer.innerHTML = "";

    newYachts.forEach((y) => {
      stateById[y.id] = oldState[y.id] || { thinking: false, unread: false };

      const item = document.createElement("button");
      item.className = "yacht-nav-item";
      item.style.setProperty("--yacht-color", y.color || "#0b2545");
      item.title = y.name || y.id;
      item.innerHTML = `
        <span class="nav-online" title="Компьютер на яхте"></span>
        <span class="nav-icon">${y.icon || "⛵"}</span>
        <span class="nav-label">${y.name || y.id}</span>
        <span class="nav-dot"></span>
      `;
      item.addEventListener("click", () => selectYacht(y.id));
      yachtNavEl.appendChild(item);
      tabsById[y.id] = item;

      let log = oldChatLogs[y.id];
      const isNewLog = !log;
      if (isNewLog) {
        log = document.createElement("div");
        log.className = "chat-log";
        const empty = document.createElement("div");
        empty.className = "empty-state";
        empty.innerHTML = `Отправьте первое сообщение — оно прозвучит азбукой Морзе,<br />и «${y.name || y.id}» ответит вам тем же языком.`;
        log.appendChild(empty);
      }
      chatLogContainer.appendChild(log);
      chatLogsById[y.id] = log;

      if (isNewLog) {
        const events = (historyMap || {})[y.id] || [];
        events.forEach((ev) => appendBubble(y.id, ev, true));
      }
    });

    yachts = newYachts;
    const stillVisible = newYachts.some((y) => y.id === previousActiveId);
    activeYachtId = stillVisible ? previousActiveId : (newYachts[0] ? newYachts[0].id : null);

    updateActiveTabUI();
    refreshOnlineIndicators();
  }

  // Статус компьютера на борту (Wi-Fi): просто индикатор, ни на что не влияет —
  // азбука Морзе для этой яхты всё равно проигрывается на стенде.
  function refreshOnlineIndicators() {
    yachts.forEach((y) => {
      const tab = tabsById[y.id];
      if (!tab) return;
      const dot = tab.querySelector(".nav-online");
      const online = !!onlineById[y.id];
      dot.classList.toggle("online", online);
      dot.title = online ? "Компьютер на яхте: на связи" : "Компьютер на яхте: не на связи";
    });
  }

  function selectYacht(yachtId) {
    if (yachtId === activeYachtId) return;
    activeYachtId = yachtId;
    stateById[yachtId].unread = false;
    updateActiveTabUI();
  }

  function updateActiveTabUI() {
    yachts.forEach((y) => {
      const isActive = y.id === activeYachtId;
      tabsById[y.id].classList.toggle("active", isActive);
      chatLogsById[y.id].hidden = !isActive;
    });
    refreshTabIndicators();
  }

  function refreshTabIndicators() {
    yachts.forEach((y) => {
      const tab = tabsById[y.id];
      const state = stateById[y.id];
      tab.classList.toggle("thinking", state.thinking);
      tab.classList.toggle("unread", state.unread && y.id !== activeYachtId);
    });
  }

  function setThinking(yachtId, isThinking) {
    if (!stateById[yachtId]) return;
    stateById[yachtId].thinking = isThinking;
    refreshTabIndicators();
  }

  function clearYachtLog(yachtId) {
    const log = chatLogsById[yachtId];
    const y = yachts.find((v) => v.id === yachtId);
    if (!log || !y) return;
    log.style.transition = "opacity 0.25s ease";
    log.style.opacity = "0";
    setTimeout(() => {
      log.innerHTML = "";
      const empty = document.createElement("div");
      empty.className = "empty-state";
      empty.innerHTML = `Отправьте первое сообщение — оно прозвучит азбукой Морзе,<br />и «${y.name || y.id}» ответит вам тем же языком.`;
      log.appendChild(empty);
      log.style.opacity = "1";
    }, 250);
  }

  // ---------- Тайминг азбуки Морзе (используется и для звука, и для рисунка) ----------
  function computeSchedule(morse, wpm) {
    const unit = 1200 / Math.max(wpm, 1); // мс на единицу (стандарт PARIS)
    const events = [];
    const letterEndsMs = []; // момент, когда отзвучала каждая буква — для расшифровки в реальном времени
    let t = 0;
    const words = morse.split(" / ").map((w) => w.trim()).filter(Boolean);
    words.forEach((word, wIdx) => {
      const letters = word.split(" ").filter(Boolean);
      letters.forEach((letter, lIdx) => {
        for (const sym of letter) {
          const dur = sym === "-" ? unit * 3 : unit;
          events.push({ onMs: t, offMs: t + dur });
          t += dur + unit; // + межсимвольный интервал
        }
        letterEndsMs.push(t);
        if (lIdx < letters.length - 1) t += unit * 2; // добить межбуквенный интервал (итого 3)
      });
      if (wIdx < words.length - 1) t += unit * 4; // добить межсловный интервал (итого 7)
    });
    return { events, totalMs: Math.max(t, unit), letterEndsMs };
  }

  // Символы, которые сервер умеет переводить в азбуку Морзе (server/morse.py).
  // Нужно клиенту, чтобы понять, какие символы текста ждут своей "буквы" в
  // расписании letterEndsMs, а какие (пробелы, неизвестные символы) показывать сразу.
  const MORSE_CHARS = new Set([
    "А","Б","В","Г","Д","Е","Ё","Ж","З","И","Й","К","Л","М","Н","О","П","Р","С","Т","У","Ф","Х","Ц","Ч","Ш","Щ","Ъ","Ы","Ь","Э","Ю","Я",
    "A","B","C","D","E","F","G","H","I","J","K","L","M","N","O","P","Q","R","S","T","U","V","W","X","Y","Z",
    "0","1","2","3","4","5","6","7","8","9",
    ".",",","?","!","'","-","/","(",")",":",";","=","+","\"","@",
  ]);

  // ---------- Отрисовка осциллограммы ----------
  function drawWave(canvas, events, totalMs, progressMs, colorOn, colorMute) {
    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    if (rect.width === 0) return;
    canvas.width = rect.width * dpr;
    canvas.height = rect.height * dpr;
    const ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const w = rect.width, h = rect.height;
    ctx.clearRect(0, 0, w, h);

    const baseline = h * 0.74;
    const peak = h * 0.2;

    function tracePath() {
      ctx.beginPath();
      ctx.moveTo(0, baseline);
      events.forEach(({ onMs, offMs }) => {
        const x1 = (onMs / totalMs) * w;
        const x2 = (offMs / totalMs) * w;
        ctx.lineTo(x1, baseline);
        ctx.lineTo(x1, peak);
        ctx.lineTo(x2, peak);
        ctx.lineTo(x2, baseline);
      });
      ctx.lineTo(w, baseline);
    }

    ctx.lineWidth = 2;
    ctx.lineJoin = "round";
    ctx.strokeStyle = colorMute;
    tracePath();
    ctx.stroke();

    if (progressMs > 0) {
      const progressX = Math.min(w, (progressMs / totalMs) * w);
      ctx.save();
      ctx.beginPath();
      ctx.rect(0, 0, progressX, h);
      ctx.clip();
      ctx.strokeStyle = colorOn;
      tracePath();
      ctx.stroke();
      ctx.restore();
    }
  }

  // ---------- Отрисовка сообщений ----------
  function appendBubble(yachtId, ev, instant) {
    const log = chatLogsById[yachtId];
    if (!log) return null;
    const empty = log.querySelector(".empty-state");
    if (empty) empty.hidden = true;

    const bubble = document.createElement("div");
    bubble.className = `bubble ${ev.sender}`;

    const y = yachts.find((v) => v.id === yachtId);
    const who = document.createElement("div");
    who.className = "who";
    who.textContent = ev.sender === "viewer" ? "Зритель · берег" : (y ? y.name : "Яхта");

    const waveWrap = document.createElement("div");
    waveWrap.className = "waveform-wrap";
    const canvas = document.createElement("canvas");
    waveWrap.appendChild(canvas);

    const morseCode = document.createElement("div");
    morseCode.className = "morse-code";
    morseCode.textContent = ev.morse;

    // Текст расшифровывается словами по мере звучания (см. playMorse), а не разом в конце.
    const textLine = document.createElement("div");
    textLine.className = "text-line";
    // Буквы, у которых есть код Морзе, ждут своей очереди в letterEndsMs;
    // пробелы и нераспознанные символы показываются сразу — ждать нечего.
    const letterEls = [];
    for (const ch of ev.text) {
      const span = document.createElement("span");
      span.className = "letter";
      span.textContent = ch;
      const isTimed = ch.trim() !== "" && MORSE_CHARS.has(ch.toUpperCase());
      if (!isTimed || instant) span.classList.add("shown");
      textLine.appendChild(span);
      if (isTimed) letterEls.push(span);
    }

    bubble.appendChild(who);
    bubble.appendChild(waveWrap);
    bubble.appendChild(morseCode);
    bubble.appendChild(textLine);
    log.appendChild(bubble);
    log.scrollTop = log.scrollHeight;

    const isYacht = ev.sender === "yacht";
    const colorOn = isYacht ? COLOR_YACHT_ON : COLOR_VIEWER_ON;
    const colorMute = isYacht ? COLOR_YACHT_MUTE : COLOR_VIEWER_MUTE;
    const schedule = computeSchedule(ev.morse, morseSettings.wpm || 20);

    requestAnimationFrame(() => {
      drawWave(canvas, schedule.events, schedule.totalMs, instant ? schedule.totalMs : 0, colorOn, colorMute);
    });

    if (!instant && yachtId !== activeYachtId) {
      stateById[yachtId].unread = true;
      refreshTabIndicators();
    }

    return { bubble, canvas, schedule, colorOn, colorMute, letterEls };
  }

  // ---------- Очередь воспроизведения (один динамик на всех) ----------
  // Событие рендерится (и его пузырь появляется на экране) только когда до него
  // дошла очередь — поэтому ответ яхты не видно, пока не доиграло сообщение
  // зрителя перед ним, даже если ответ уже пришёл с сервера раньше.
  const playQueue = [];
  let isPlaying = false;

  function queuePlayback(ev) {
    playQueue.push(ev);
    updateInputLock();
    if (!isPlaying) processQueue();
  }

  async function processQueue() {
    isPlaying = true;
    updateInputLock();
    while (playQueue.length) {
      const ev = playQueue.shift();
      const rendered = appendBubble(ev.yacht_id, ev, false);
      if (rendered) await playMorse(rendered);
    }
    isPlaying = false;
    updateInputLock();
  }

  // Пока идёт обмен репликами (с сервера) или ещё не доиграла очередь звука —
  // ввод заблокирован: нельзя писать одной яхте, пока не закончился разговор
  // с другой (или с этой же).
  function updateInputLock() {
    const locked = serverBusy || isPlaying || playQueue.length > 0;
    textInput.disabled = locked;
    sendBtn.disabled = locked;
    textInput.placeholder = locked ? "Яхта отвечает…" : "Сообщение яхте азбукой Морзе…";
  }

  let audioCtx = null;
  function getAudioCtx() {
    if (!audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    if (audioCtx.state === "suspended") audioCtx.resume();
    return audioCtx;
  }

  function playMorse({ canvas, schedule, colorOn, colorMute, letterEls, muted }) {
    return new Promise((resolve) => {
      const { events, totalMs, letterEndsMs } = schedule;
      if (!events.length) { resolve(); return; }

      const ctx = getAudioCtx();
      const toneHz = morseSettings.tone_hz || 600;
      const startDelay = 0.05;
      const t0 = ctx.currentTime + startDelay;

      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = "sine";
      osc.frequency.value = toneHz;
      gain.gain.setValueAtTime(0, ctx.currentTime);
      if (!muted) osc.connect(gain).connect(ctx.destination);
      osc.start();

      // Короткое плавное нарастание/спад громкости на каждом сигнале — без него
      // мгновенный скачок гейна на каждой точке/тире звучит как резкий щелчок/дребезг.
      const PEAK_GAIN = 0.2;
      events.forEach(({ onMs, offMs }) => {
        const onAt = t0 + onMs / 1000;
        const offAt = t0 + offMs / 1000;
        const ramp = Math.min(0.004, (offAt - onAt) / 3);
        gain.gain.setValueAtTime(0, onAt);
        gain.gain.linearRampToValueAtTime(PEAK_GAIN, onAt + ramp);
        gain.gain.setValueAtTime(PEAK_GAIN, offAt - ramp);
        gain.gain.linearRampToValueAtTime(0, offAt);
      });
      osc.stop(t0 + totalMs / 1000 + 0.05);

      // Расшифровка в реальном времени: каждая буква текста проявляется сразу,
      // как только отзвучал её код Морзе — не нужно ждать конца всего сообщения.
      const letterTimers = (letterEndsMs || []).map((ms, i) => {
        const el = letterEls && letterEls[i];
        if (!el) return null;
        return setTimeout(() => el.classList.add("shown"), Math.max(0, startDelay * 1000 + ms));
      });

      const startPerf = performance.now() + startDelay * 1000;
      let rafId;
      function tick() {
        const elapsed = performance.now() - startPerf;
        drawWave(canvas, events, totalMs, Math.max(0, elapsed), colorOn, colorMute);
        if (elapsed < totalMs) {
          rafId = requestAnimationFrame(tick);
        } else {
          drawWave(canvas, events, totalMs, totalMs, colorOn, colorMute);
        }
      }
      rafId = requestAnimationFrame(tick);

      setTimeout(() => {
        cancelAnimationFrame(rafId);
        drawWave(canvas, events, totalMs, totalMs, colorOn, colorMute);
        letterTimers.forEach((id) => id && clearTimeout(id));
        (letterEls || []).forEach((el) => el.classList.add("shown"));
        resolve();
      }, totalMs + startDelay * 1000 + 120);
    });
  }

  // ---------- Отправка сообщений ----------
  function submitMessage() {
    if (sendBtn.disabled) return; // разговор уже идёт — нельзя писать поверх
    const text = textInput.value.trim();
    if (!text || !activeYachtId) return;
    sendWS({ type: "user_message", yacht_id: activeYachtId, text });
    textInput.value = "";
    // Блокируем сразу, не дожидаясь ответного "busy" с сервера — иначе окно
    // между кликом и приходом события позволило бы отправить второе сообщение.
    serverBusy = true;
    updateInputLock();
  }

  // Клик по кнопке (send, клавиши экранной клавиатуры) по умолчанию уводит
  // фокус с текстового поля — из-за этого клавиатура тут же закрывалась бы
  // после каждого нажатия. preventDefault на mousedown не даёт фокусу уйти.
  function keepInputFocused(el) {
    el.addEventListener("mousedown", (e) => e.preventDefault());
  }

  keepInputFocused(sendBtn);
  sendBtn.addEventListener("click", submitMessage);
  textInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") submitMessage();
  });

  // Клавиатура открывается сама при касании поля ввода и прячется, когда
  // зритель уходит к чему-то другому (выбор яхты, сообщения) — отдельная
  // кнопка-переключатель ему не нужна.
  textInput.addEventListener("focus", () => { keyboardEl.hidden = false; });
  textInput.addEventListener("blur", () => { keyboardEl.hidden = true; });

  // ---------- Экранная клавиатура (ЙЦУКЕН) ----------
  const KEYBOARD_ROWS = [
    ["Й", "Ц", "У", "К", "Е", "Н", "Г", "Ш", "Щ", "З", "Х"],
    ["Ф", "Ы", "В", "А", "П", "Р", "О", "Л", "Д", "Ж", "Э"],
    ["Я", "Ч", "С", "М", "И", "Т", "Ь", "Б", "Ю", ".", "?"],
  ];

  function buildKeyboard() {
    keyboardEl.innerHTML = "";
    KEYBOARD_ROWS.forEach((row) => {
      const rowEl = document.createElement("div");
      rowEl.className = "kbd-row";
      row.forEach((ch) => {
        const key = document.createElement("button");
        key.className = "kbd-key";
        key.textContent = ch;
        keepInputFocused(key);
        key.addEventListener("click", () => insertChar(ch));
        rowEl.appendChild(key);
      });
      keyboardEl.appendChild(rowEl);
    });

    const lastRow = document.createElement("div");
    lastRow.className = "kbd-row";
    const backspace = document.createElement("button");
    backspace.className = "kbd-key special";
    backspace.textContent = "⌫";
    keepInputFocused(backspace);
    backspace.addEventListener("click", () => {
      textInput.value = textInput.value.slice(0, -1);
    });
    const space = document.createElement("button");
    space.className = "kbd-key wide";
    space.textContent = "пробел";
    keepInputFocused(space);
    space.addEventListener("click", () => insertChar(" "));
    const enter = document.createElement("button");
    enter.className = "kbd-key special";
    enter.textContent = "передать";
    keepInputFocused(enter);
    enter.addEventListener("click", submitMessage);

    lastRow.appendChild(backspace);
    lastRow.appendChild(space);
    lastRow.appendChild(enter);
    keyboardEl.appendChild(lastRow);
  }

  function insertChar(ch) {
    if (textInput.value.length >= textInput.maxLength) return;
    textInput.value += ch;
  }

  // ============================================================
  // Панель настроек (клавиша S — работает в любой раскладке,
  // т.к. проверяется физический код клавиши, а не введённый символ)
  // ============================================================
  const settingsOverlay = document.getElementById("settings-overlay");
  const settingsClose = document.getElementById("settings-close");
  const settingsCancel = document.getElementById("settings-cancel");
  const settingsSave = document.getElementById("settings-save");
  const settingsYachtsSection = document.getElementById("settings-yachts");
  const setWpm = document.getElementById("set-wpm");
  const setTone = document.getElementById("set-tone");
  const setModel = document.getElementById("set-model");
  const setTemp = document.getElementById("set-temp");
  const setMaxTokens = document.getElementById("set-max-tokens");
  const setMinDelay = document.getElementById("set-min-delay");
  const setHistory = document.getElementById("set-history");
  const setCommonPrompt = document.getElementById("set-common-prompt");
  const setClearAll = document.getElementById("set-clear-all");

  async function openSettings() {
    try {
      const resp = await fetch("/api/settings");
      const cfg = await resp.json();
      populateSettingsForm(cfg);
      settingsOverlay.hidden = false;
    } catch (e) {
      showToast("Не удалось загрузить настройки");
    }
  }

  function closeSettings() {
    settingsOverlay.hidden = true;
  }

  function populateSettingsForm(cfg) {
    setWpm.value = cfg.morse?.wpm ?? 20;
    setTone.value = cfg.morse?.tone_hz ?? 600;
    setModel.value = cfg.openrouter?.model ?? "";
    setTemp.value = cfg.openrouter?.temperature ?? 0.9;
    setMaxTokens.value = cfg.openrouter?.max_tokens ?? 70;
    setMinDelay.value = cfg.min_reply_delay_seconds ?? 0.5;
    setHistory.value = cfg.max_history_length ?? 10;
    setCommonPrompt.value = cfg.system_prompt_common ?? "";

    settingsYachtsSection.querySelectorAll(".yacht-settings-card").forEach((el) => el.remove());
    (cfg.yachts || []).forEach((y) => {
      const card = document.createElement("div");
      card.className = "yacht-settings-card";
      card.dataset.yachtId = y.id;
      const isEnabled = y.enabled !== false;
      card.classList.toggle("is-disabled", !isEnabled);
      card.innerHTML = `
        <div class="field-row">
          <label class="field icon-field">
            <span>Значок</span>
            <input type="text" class="set-yacht-icon" value="${escapeAttr(y.icon || "⛵")}" maxlength="4" />
          </label>
          <label class="field">
            <span>Имя яхты</span>
            <input type="text" class="set-yacht-name" value="${escapeAttr(y.name || y.id)}" maxlength="40" />
          </label>
        </div>
        <label class="field-checkbox">
          <input type="checkbox" class="set-yacht-enabled" ${isEnabled ? "checked" : ""} />
          <span>Активна на стенде (показывается зрителям)</span>
        </label>
        <label class="field">
          <span>Характер / системный промпт</span>
          <textarea class="field-textarea set-yacht-prompt" rows="3">${escapeHtml(y.system_prompt || "")}</textarea>
        </label>
      `;
      const enabledCheckbox = card.querySelector(".set-yacht-enabled");
      enabledCheckbox.addEventListener("change", () => {
        card.classList.toggle("is-disabled", !enabledCheckbox.checked);
      });
      settingsYachtsSection.appendChild(card);
    });
  }

  function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
  }
  function escapeAttr(str) {
    return escapeHtml(str).replace(/"/g, "&quot;");
  }

  function collectSettingsPayload() {
    const yachtsPayload = [];
    settingsYachtsSection.querySelectorAll(".yacht-settings-card").forEach((card) => {
      yachtsPayload.push({
        id: card.dataset.yachtId,
        icon: card.querySelector(".set-yacht-icon").value,
        name: card.querySelector(".set-yacht-name").value,
        system_prompt: card.querySelector(".set-yacht-prompt").value,
        enabled: card.querySelector(".set-yacht-enabled").checked,
      });
    });
    return {
      morse: { wpm: Number(setWpm.value), tone_hz: Number(setTone.value) },
      openrouter: {
        model: setModel.value,
        temperature: Number(setTemp.value),
        max_tokens: Number(setMaxTokens.value),
      },
      max_history_length: Number(setHistory.value),
      min_reply_delay_seconds: Number(setMinDelay.value),
      system_prompt_common: setCommonPrompt.value,
      yachts: yachtsPayload,
    };
  }

  async function saveSettings() {
    try {
      const resp = await fetch("/api/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(collectSettingsPayload()),
      });
      if (!resp.ok) throw new Error("bad response");
      // UI обновится через входящий WebSocket "config_updated" (тот же список
      // получат и другие подключённые дисплеи), поэтому здесь трогать вкладки не нужно.
      await resp.json();
      showToast("Настройки сохранены");
      closeSettings();
    } catch (e) {
      showToast("Не удалось сохранить настройки");
    }
  }

  setClearAll.addEventListener("click", () => {
    if (!window.confirm("Очистить историю всех яхт? Это необратимо.")) return;
    yachts.forEach((y) => sendWS({ type: "reset_history", yacht_id: y.id }));
    showToast("История всех яхт очищена");
  });

  settingsClose.addEventListener("click", closeSettings);
  settingsCancel.addEventListener("click", closeSettings);
  settingsSave.addEventListener("click", saveSettings);
  settingsOverlay.addEventListener("click", (e) => {
    if (e.target === settingsOverlay) closeSettings();
  });

  window.addEventListener("keydown", (e) => {
    if (!settingsOverlay.hidden && e.key === "Escape") {
      closeSettings();
      return;
    }
    // "S" по физической клавише (KeyS) — не зависит от раскладки (ЙЦУКЕН/QWERTY).
    // Игнорируем, пока идёт ввод сообщения, чтобы буква "s"/"ы" не открывала панель.
    if (e.code === "KeyS" && document.activeElement !== textInput && settingsOverlay.hidden) {
      e.preventDefault();
      openSettings();
    }
  });

  // ---------- Инициализация ----------
  buildKeyboard();
  updateInputLock();
  connect();

  // Открыть настройки можно и по ссылке http://<стенд>:8000/?admin=1 — например
  // с телефона в той же Wi-Fi сети, где нет физической клавиши S. Сам стенд
  // при этом не трогаем: это отдельная вкладка в браузере на другом устройстве.
  if (new URLSearchParams(location.search).get("admin")) {
    openSettings();
  }

  window.addEventListener("pointerdown", () => { getAudioCtx(); }, { once: true });
})();
