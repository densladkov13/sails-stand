# server/config.py
# -*- coding: utf-8 -*-
"""
Загрузка config.json и переменных окружения (.env) для стенда SAILS.
Настройки можно менять на лету через панель настроек (клавиша S) —
save_config() валидирует, перезаписывает config.json и обновляет
глобальные переменные этого модуля, так что изменения применяются
сразу, без перезапуска сервера.
"""
import json
import os
from pathlib import Path
from typing import Any, Dict, List

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

CONFIG_PATH = BASE_DIR / "config.json"

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
HTTP_REFERER = os.environ.get("YOUR_SITE_URL", "")
X_TITLE = os.environ.get("YOUR_APP_NAME", "SAILS Stand")


def load_config() -> Dict[str, Any]:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _clamp(value: Any, lo: float, hi: float, cast=float) -> Any:
    try:
        v = cast(value)
    except (TypeError, ValueError):
        return lo
    return max(lo, min(hi, v))


def _apply(new_config: Dict[str, Any]) -> None:
    """Пересчитывает публичные глобальные переменные модуля из CONFIG."""
    global STAND, OPENROUTER_DEFAULTS, MAX_HISTORY_LENGTH, MORSE_SETTINGS
    global SYSTEM_PROMPT_COMMON, YACHTS, YACHTS_BY_ID, CONFIG, MIN_REPLY_DELAY_SECONDS

    CONFIG = new_config
    STAND = CONFIG.get("stand", {"title": "SAILS", "subtitle": ""})
    OPENROUTER_DEFAULTS = CONFIG.get("openrouter", {})
    MAX_HISTORY_LENGTH = int(CONFIG.get("max_history_length", 10))
    MIN_REPLY_DELAY_SECONDS = float(CONFIG.get("min_reply_delay_seconds", 0.5))
    MORSE_SETTINGS = CONFIG.get("morse", {"wpm": 20, "tone_hz": 600})
    SYSTEM_PROMPT_COMMON = CONFIG.get("system_prompt_common", "")
    YACHTS = CONFIG.get("yachts", [])
    YACHTS_BY_ID = {y["id"]: y for y in YACHTS}


CONFIG: Dict[str, Any] = load_config()
_apply(CONFIG)


def save_config(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Принимает настройки из панели (тот же формат, что отдаёт GET /api/settings),
    валидирует/подчищает значения, сохраняет в config.json и сразу применяет.
    ID и количество яхт не меняются — редактируются только их name/icon/system_prompt.
    """
    updated = json.loads(json.dumps(CONFIG))  # глубокая копия текущего конфига

    if "stand" in payload and isinstance(payload["stand"], dict):
        updated.setdefault("stand", {})
        updated["stand"]["title"] = str(payload["stand"].get("title", updated["stand"].get("title", "SAILS")))[:60]
        updated["stand"]["subtitle"] = str(payload["stand"].get("subtitle", updated["stand"].get("subtitle", "")))[:200]

    if "openrouter" in payload and isinstance(payload["openrouter"], dict):
        oc = payload["openrouter"]
        updated.setdefault("openrouter", {})
        if "model" in oc and str(oc["model"]).strip():
            updated["openrouter"]["model"] = str(oc["model"]).strip()[:120]
        if "temperature" in oc:
            updated["openrouter"]["temperature"] = _clamp(oc["temperature"], 0.0, 2.0, float)
        if "max_tokens" in oc:
            updated["openrouter"]["max_tokens"] = int(_clamp(oc["max_tokens"], 16, 600, float))

    if "max_history_length" in payload:
        updated["max_history_length"] = int(_clamp(payload["max_history_length"], 1, 40, float))

    if "min_reply_delay_seconds" in payload:
        updated["min_reply_delay_seconds"] = round(_clamp(payload["min_reply_delay_seconds"], 0.0, 10.0, float), 2)

    if "morse" in payload and isinstance(payload["morse"], dict):
        mc = payload["morse"]
        updated.setdefault("morse", {})
        if "wpm" in mc:
            updated["morse"]["wpm"] = int(_clamp(mc["wpm"], 5, 60, float))
        if "tone_hz" in mc:
            updated["morse"]["tone_hz"] = int(_clamp(mc["tone_hz"], 200, 1200, float))
        # Громкость намеренно без верхнего предела (только защита от переполнения).
        for key in ("volume_yacht", "volume_stand"):
            if key in mc:
                updated["morse"][key] = _clamp(mc[key], 0, 100000, float)

    if "system_prompt_common" in payload:
        updated["system_prompt_common"] = str(payload["system_prompt_common"])[:2000]

    if "yachts" in payload and isinstance(payload["yachts"], list):
        by_id = {y["id"]: y for y in updated.get("yachts", [])}
        for item in payload["yachts"]:
            if not isinstance(item, dict) or item.get("id") not in by_id:
                continue
            target = by_id[item["id"]]
            if "name" in item and str(item["name"]).strip():
                target["name"] = str(item["name"]).strip()[:40]
            if "icon" in item and str(item["icon"]).strip():
                target["icon"] = str(item["icon"]).strip()[:8]
            if "system_prompt" in item:
                target["system_prompt"] = str(item["system_prompt"])[:2000]
            if "enabled" in item:
                target["enabled"] = bool(item["enabled"])

    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(updated, f, ensure_ascii=False, indent=2)
        f.write("\n")

    _apply(updated)
    return updated


def build_system_prompt(yacht: Dict[str, Any]) -> str:
    parts = [yacht.get("system_prompt", ""), SYSTEM_PROMPT_COMMON]
    return "\n\n".join(p for p in parts if p)
