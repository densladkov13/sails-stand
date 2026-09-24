# server/openrouter_client.py
# -*- coding: utf-8 -*-
"""
Клиент OpenRouter API. Логика повторных попыток унаследована от
utils/openrouter_api.py из референсного проекта (SoulAICode), адаптирована
под asyncio (вызывается через asyncio.to_thread) и под настройки на каждую яхту.
"""
import asyncio
import json
import logging
import time
from typing import Any, Dict, List

import requests

from . import config as cfg

logger = logging.getLogger("parusa.openrouter")

OPENROUTER_API_BASE_URL = "https://openrouter.ai/api/v1"
MAX_RETRIES = 4
RETRY_DELAY_SECONDS = 1.0

RETRYABLE_ERROR_MESSAGES = [
    "provider returned error",
    "upstream request timeout",
    "service unavailable",
    "internal server error",
    "rate limit exceeded",
]
NON_RETRYABLE_ERROR_SUBSTRINGS = [
    "user location is not supported",
    "invalid api key",
    "insufficient quota",
    "model not found",
    "invalid request",
]


def _call_openrouter_sync(messages: List[Dict[str, str]], model_config: Dict[str, Any]) -> str:
    if not cfg.OPENROUTER_API_KEY:
        return "Ошибка: не задан OPENROUTER_API_KEY (см. .env.example)."

    model_name = model_config.get("model_name")
    if not model_name:
        return "Ошибка: 'model_name' отсутствует в конфигурации."
    if not messages:
        return "Ошибка: список сообщений пуст."

    url = f"{OPENROUTER_API_BASE_URL}/chat/completions"
    headers = {
        "Authorization": f"Bearer {cfg.OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }
    if cfg.HTTP_REFERER:
        headers["HTTP-Referer"] = cfg.HTTP_REFERER
    if cfg.X_TITLE:
        headers["X-Title"] = cfg.X_TITLE

    payload: Dict[str, Any] = {"model": model_name, "messages": messages}
    if "temperature" in model_config:
        payload["temperature"] = model_config["temperature"]
    if "max_tokens" in model_config:
        payload["max_tokens"] = model_config["max_tokens"]

    last_error = "Неизвестная ошибка"
    for attempt in range(MAX_RETRIES + 1):
        if attempt > 0:
            time.sleep(RETRY_DELAY_SECONDS)
            logger.info("Повторная попытка %s/%s к OpenRouter", attempt, MAX_RETRIES)

        try:
            response = requests.post(url, headers=headers, json=payload, timeout=60)
        except requests.exceptions.Timeout as e:
            last_error = f"Ошибка: таймаут запроса к API ({e})"
        except requests.exceptions.RequestException as e:
            last_error = f"Ошибка сети при запросе к API: {e}"
        else:
            try:
                data = response.json()
            except json.JSONDecodeError:
                last_error = f"Ошибка: ответ сервера не JSON (статус {response.status_code})"
                if not (500 <= response.status_code < 600):
                    return last_error
                continue

            if "error" in data and isinstance(data["error"], dict):
                error_obj = data["error"]
                msg = str(error_obj.get("message", "нет сообщения"))
                code = error_obj.get("code")
                last_error = f"Ошибка API OpenRouter: {msg} (код {code})"
                lower_msg = msg.lower()
                retryable = False
                if not any(s in lower_msg for s in NON_RETRYABLE_ERROR_SUBSTRINGS):
                    if any(s in lower_msg for s in RETRYABLE_ERROR_MESSAGES) or code in (429, 500, 502, 503, 504):
                        retryable = True
                if retryable and attempt < MAX_RETRIES:
                    continue
                return last_error

            choices = data.get("choices")
            if isinstance(choices, list) and choices:
                message = choices[0].get("message", {})
                content = message.get("content")
                if content:
                    return content.strip()
                return "[Пустой ответ от модели]"

            last_error = "Ошибка: неожиданная структура ответа API."

        if attempt >= MAX_RETRIES:
            break

    logger.error("Все попытки вызова OpenRouter исчерпаны: %s", last_error)
    return f"Ошибка: не удалось получить ответ от нейросети. {last_error}"


async def call_openrouter(messages: List[Dict[str, str]], model_config: Dict[str, Any]) -> str:
    return await asyncio.to_thread(_call_openrouter_sync, messages, model_config)
