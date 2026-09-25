# server/main.py
# -*- coding: utf-8 -*-
"""
Сервер стенда SAILS.

Обслуживает:
  - веб-страницу стенда (полноэкранный чат зритель <-> яхты азбукой Морзе);
  - WebSocket /ws          — для дисплея/панели ввода на стенде;
  - WebSocket /ws/yacht/{yacht_id} — для клиента на компьютере яхты
    (модули на борту: LED-палка, LED-парик, колонка).

Логика диалога: сообщение зрителя добавляется в историю нужной яхты,
переводится в азбуку Морзе и рассылается всем подключённым дисплеям и
клиенту этой яхты для проигрывания. Параллельно уходит запрос к OpenRouter
(с системным промптом и ограниченной историей), и ответ яхты точно так же
переводится в Морзе и рассылается.
"""
import asyncio
import datetime
import logging
import os
import re
import subprocess
import time
from typing import Any, Dict, List, Optional, Tuple

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import config as cfg
from .history import ConversationStore
from .morse import text_to_morse
from .openrouter_client import call_openrouter

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("parusa.server")

app = FastAPI(title="Parusa Stand")

WEB_DIR = cfg.BASE_DIR / "web"
app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")


@app.middleware("http")
async def no_cache_for_static(request, call_next):
    """
    Стенд — киоск на одном открытом окне браузера: без этого правки в
    web/*.js и web/*.css молча продолжают исполняться из кэша браузера
    после обновления файлов на диске. Заставляем браузер каждый раз
    перепроверять статику у сервера (ETag/Last-Modified всё равно избавляют
    от повторной передачи неизменившихся файлов).
    """
    response = await call_next(request)
    if request.url.path.startswith("/static/") or request.url.path == "/":
        response.headers["Cache-Control"] = "no-cache"
    return response

conversations = ConversationStore(
    yacht_ids=[y["id"] for y in cfg.YACHTS],
    max_history_length=cfg.MAX_HISTORY_LENGTH,
)

# Полный журнал сообщений на дисплее (для восстановления состояния при переподключении)
display_log: Dict[str, List[Dict[str, Any]]] = {y["id"]: [] for y in cfg.YACHTS}


class ConnectionManager:
    def __init__(self) -> None:
        self.displays: List[WebSocket] = []
        self.yacht_clients: Dict[str, List[WebSocket]] = {y["id"]: [] for y in cfg.YACHTS}

    async def connect_display(self, ws: WebSocket) -> None:
        await ws.accept()
        self.displays.append(ws)

    def disconnect_display(self, ws: WebSocket) -> None:
        if ws in self.displays:
            self.displays.remove(ws)

    async def connect_yacht(self, yacht_id: str, ws: WebSocket) -> None:
        await ws.accept()
        self.yacht_clients.setdefault(yacht_id, []).append(ws)

    def disconnect_yacht(self, yacht_id: str, ws: WebSocket) -> None:
        clients = self.yacht_clients.get(yacht_id, [])
        if ws in clients:
            clients.remove(ws)

    def is_yacht_online(self, yacht_id: str) -> bool:
        return bool(self.yacht_clients.get(yacht_id))

    async def broadcast_display(self, message: Dict[str, Any]) -> None:
        dead = []
        for ws in self.displays:
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect_display(ws)

    async def send_to_yacht(self, yacht_id: str, message: Dict[str, Any]) -> None:
        dead = []
        for ws in self.yacht_clients.get(yacht_id, []):
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect_yacht(yacht_id, ws)


manager = ConnectionManager()

# На стенде одновременно может идти только один обмен репликами (зритель -> яхта):
# пока лок занят, новые сообщения от зрителя игнорируются (кнопка отправки у него
# всё равно заблокирована на клиенте — см. рассылку "busy" ниже).
conversation_lock = asyncio.Lock()


def _now_iso() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


# Нейросеть дописывает в конец ответа служебную метку вида {эффект,цвет}
# (например {2,1}) — сигнал для LED-палки на борту. Зритель её никогда не
# видит и не слышит: вырезаем до того, как текст попадёт в чат/азбуку Морзе.
_EFFECT_COMMAND_RE = re.compile(r"\{\s*([1-9]\d?)\s*,\s*([1-9]\d?)\s*\}")


def _extract_effect_command(text: str) -> Tuple[str, Optional[int], Optional[int]]:
    matches = list(_EFFECT_COMMAND_RE.finditer(text))
    if not matches:
        return text.strip(), None, None
    m = matches[-1]  # если модель случайно повторилась, берём последнюю
    clean = (text[: m.start()] + text[m.end() :]).strip()
    return clean, int(m.group(1)), int(m.group(2))


def _make_chat_event(yacht_id: str, sender: str, text: str) -> Dict[str, Any]:
    morse = text_to_morse(text)
    return {
        "type": "chat_update",
        "yacht_id": yacht_id,
        "sender": sender,  # "viewer" | "yacht"
        "text": text,
        "morse": morse,
        "timestamp": _now_iso(),
    }


async def _broadcast_and_log(
    event: Dict[str, Any], effect: Optional[int] = None, color: Optional[int] = None
) -> None:
    display_log[event["yacht_id"]].append(event)
    await manager.broadcast_display(event)
    play_msg: Dict[str, Any] = {
        "type": "play_morse",
        "yacht_id": event["yacht_id"],
        "sender": event["sender"],
        "text": event["text"],
        "morse": event["morse"],
    }
    if effect is not None and color is not None:
        # Идёт только клиенту на яхте — на стенд/дисплеи эти поля не попадают.
        play_msg["effect"] = effect
        play_msg["color"] = color
    await manager.send_to_yacht(event["yacht_id"], play_msg)


async def handle_user_message(yacht_id: str, text: str) -> None:
    yacht = cfg.YACHTS_BY_ID.get(yacht_id)
    if not yacht or not yacht.get("enabled", True) or not text.strip():
        return
    if conversation_lock.locked():
        # На стенде уже идёт разговор с какой-то яхтой — параллельно писать нельзя.
        return

    async with conversation_lock:
        await manager.broadcast_display({"type": "busy", "busy": True})
        try:
            history = conversations.get(yacht_id)

            # 1. Сообщение зрителя — сразу в эфир (Морзе на стенде + у яхты)
            viewer_event = _make_chat_event(yacht_id, "viewer", text.strip())
            await _broadcast_and_log(viewer_event)
            history.add_message("user", text.strip())

            # 2. Яхта "думает" пока едет запрос к нейросети
            await manager.broadcast_display({"type": "status", "yacht_id": yacht_id, "state": "thinking"})

            model_config = {
                "model_name": cfg.OPENROUTER_DEFAULTS.get("model"),
                "temperature": cfg.OPENROUTER_DEFAULTS.get("temperature", 0.9),
                "max_tokens": cfg.OPENROUTER_DEFAULTS.get("max_tokens", 70),
            }
            system_prompt = cfg.build_system_prompt(yacht)
            messages = history.get_messages(system_prompt)

            request_started = time.monotonic()
            reply = await call_openrouter(messages, model_config)

            # Даже если нейросеть ответила почти мгновенно, ответ яхты не должен
            # звучать раньше настроенной минимальной задержки (естественная пауза).
            elapsed = time.monotonic() - request_started
            remaining = cfg.MIN_REPLY_DELAY_SECONDS - elapsed
            if remaining > 0:
                await asyncio.sleep(remaining)

            if reply.startswith("Ошибка"):
                logger.warning("Ошибка ответа для %s: %s", yacht_id, reply)
                await manager.broadcast_display({"type": "status", "yacht_id": yacht_id, "state": "idle"})
                await manager.broadcast_display(
                    {"type": "error", "yacht_id": yacht_id, "message": reply}
                )
                return

            clean_reply, effect, color = _extract_effect_command(reply)
            history.add_message("assistant", clean_reply)

            # 3. Ответ яхты — тоже в эфир азбукой Морзе (без служебной метки эффекта)
            yacht_event = _make_chat_event(yacht_id, "yacht", clean_reply)
            await _broadcast_and_log(yacht_event, effect=effect, color=color)
            await manager.broadcast_display({"type": "status", "yacht_id": yacht_id, "state": "idle"})
        finally:
            await manager.broadcast_display({"type": "busy", "busy": False})


async def handle_reset(yacht_id: str) -> None:
    if yacht_id not in cfg.YACHTS_BY_ID:
        return
    conversations.clear(yacht_id)
    display_log[yacht_id] = []
    await manager.broadcast_display({"type": "history_cleared", "yacht_id": yacht_id})


async def _delayed_self_restart(delay: float = 1.5) -> None:
    """Даёт время дописать HTTP-ответ клиенту, потом завершает процесс —
    start.bat уже умеет сам перезапускать сервер после падения, так что он
    поднимется заново через несколько секунд уже со свежим кодом."""
    await asyncio.sleep(delay)
    os._exit(0)


def _run_git_update(cwd: str) -> Dict[str, Any]:
    """git pull + переустановка зависимостей (если что-то реально подтянулось)."""
    try:
        env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
        pull = subprocess.run(
            ["git", "pull"], cwd=cwd, capture_output=True, text=True, timeout=60, env=env
        )
    except Exception as e:
        return {"ok": False, "output": f"Не удалось запустить git: {e}", "changed": False}

    output = ((pull.stdout or "") + (pull.stderr or "")).strip()
    if pull.returncode != 0:
        return {"ok": False, "output": output or "git pull завершился с ошибкой.", "changed": False}

    changed = "Already up to date" not in output and "уже акту" not in output.lower()
    if changed:
        python_exe = os.path.join(cwd, ".venv", "Scripts", "python.exe")
        if os.path.exists(python_exe):
            pip = subprocess.run(
                [python_exe, "-m", "pip", "install", "--disable-pip-version-check", "-q", "-r", "requirements.txt"],
                cwd=cwd, capture_output=True, text=True, timeout=180,
            )
            output += "\n" + ((pip.stdout or "") + (pip.stderr or "")).strip()

    return {"ok": True, "output": output.strip(), "changed": changed}


def _public_config() -> Dict[str, Any]:
    return {
        "stand": cfg.STAND,
        "morse": cfg.MORSE_SETTINGS,
        "yachts": [
            {"id": y["id"], "name": y["name"], "icon": y.get("icon", "⛵"), "color": y.get("color", "#5ad1e6")}
            for y in cfg.YACHTS
            if y.get("enabled", True)
        ],
    }


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(str(WEB_DIR / "index.html"))


@app.get("/admin")
async def admin_page() -> FileResponse:
    """Панель оператора: статус связи, быстрая отправка, ссылка на настройки —
    открывается с телефона/ноутбука в той же Wi-Fi сети, стенд не трогает."""
    return FileResponse(str(WEB_DIR / "admin.html"))


@app.post("/api/update")
async def api_update() -> Dict[str, Any]:
    """git pull на самом стенде + переустановка зависимостей, если что-то
    подтянулось, затем контролируемый перезапуск процесса (см. start.bat)."""
    result = _run_git_update(str(cfg.BASE_DIR))
    if result["ok"] and result["changed"]:
        asyncio.create_task(_delayed_self_restart())
    return {"ok": result["ok"], "output": result["output"], "restarting": result["ok"] and result["changed"]}


@app.get("/api/config")
async def api_config() -> Dict[str, Any]:
    return _public_config()


@app.get("/api/settings")
async def get_settings() -> Dict[str, Any]:
    """Полный конфиг для панели настроек (клавиша S на стенде)."""
    return cfg.CONFIG


@app.post("/api/settings")
async def update_settings(payload: Dict[str, Any]) -> Dict[str, Any]:
    updated = cfg.save_config(payload)
    conversations.set_max_history_length(cfg.MAX_HISTORY_LENGTH)
    await manager.broadcast_display({"type": "config_updated", **_public_config(), "history": display_log})
    return {"ok": True, "config": updated}


@app.websocket("/ws")
async def ws_display(ws: WebSocket) -> None:
    await manager.connect_display(ws)
    try:
        await ws.send_json({
            "type": "init",
            **_public_config(),
            "history": display_log,
            "busy": conversation_lock.locked(),
            "yacht_online": {y["id"]: manager.is_yacht_online(y["id"]) for y in cfg.YACHTS},
        })
        while True:
            data = await ws.receive_json()
            msg_type = data.get("type")
            if msg_type == "user_message":
                yacht_id = data.get("yacht_id", "")
                text = str(data.get("text", ""))[:500]
                asyncio.create_task(handle_user_message(yacht_id, text))
            elif msg_type == "reset_history":
                yacht_id = data.get("yacht_id", "")
                asyncio.create_task(handle_reset(yacht_id))
            elif msg_type == "trigger_yacht_update":
                yacht_id = data.get("yacht_id", "")
                if yacht_id in cfg.YACHTS_BY_ID:
                    asyncio.create_task(manager.send_to_yacht(yacht_id, {"type": "update"}))
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect_display(ws)


@app.websocket("/ws/yacht/{yacht_id}")
async def ws_yacht(ws: WebSocket, yacht_id: str) -> None:
    if yacht_id not in cfg.YACHTS_BY_ID:
        await ws.close(code=4404)
        return
    await manager.connect_yacht(yacht_id, ws)
    logger.info("Клиент яхты подключился: %s", yacht_id)
    await manager.broadcast_display({"type": "yacht_online", "yacht_id": yacht_id, "online": True})
    try:
        while True:
            # клиент яхты не обязан ничего слать, но держим соединение живым
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect_yacht(yacht_id, ws)
        logger.info("Клиент яхты отключился: %s", yacht_id)
        # Если это был последний клиент этой яхты — сообщаем дисплеям, что связь пропала.
        if not manager.is_yacht_online(yacht_id):
            await manager.broadcast_display({"type": "yacht_online", "yacht_id": yacht_id, "online": False})
