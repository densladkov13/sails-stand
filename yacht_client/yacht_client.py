# yacht_client/yacht_client.py
# -*- coding: utf-8 -*-
"""
Клиент для компьютера НА ЯХТЕ (второй компьютер проекта "Паруса").

Подключается к серверу стенда по Wi-Fi и получает события "play_morse" —
когда нужно проиграть азбуку Морзе через колонку на борту и (в будущем)
мигать LED-палкой / LED-париком в такт.

Ответы яхты иногда несут ещё и скрытую команду эффекта подсветки (сервер
вырезает её из текста/азбуки Морзе ещё до рассылки — зритель её не видит и
не слышит) — она приходит отдельными полями "effect"/"color" в том же
событии "play_morse".

Сейчас реализовано:
  - звук через winsound.Beep (Windows) с точным таймингом точка/тире;
  - заглушки set_led() и set_led_effect(), которые просто печатают
    состояние в консоль — замените их на реальное управление
    (GPIO / DMX / serial), когда будет готово оборудование.

Запуск:
    python yacht_client.py --host 192.168.1.10 --port 8000 --yacht yacht1
"""
import argparse
import asyncio
import json
import sys
import time

import requests
import websockets

try:
    import winsound
except ImportError:  # не Windows — работаем без реального звука
    winsound = None


def set_led(is_on: bool) -> None:
    """TODO: заменить на реальное управление LED-палкой/париком (GPIO/DMX/serial)."""
    print(f"[LED] {'ВКЛ' if is_on else 'выкл'}")


EFFECT_NAMES = {1: "ровное свечение", 2: "пульс", 3: "вспышка", 4: "бегущие огни", 5: "мерцание"}
COLOR_NAMES = {1: "синий", 2: "красный", 3: "золотой", 4: "белый", 5: "зелёный", 6: "фиолетовый"}


def set_led_effect(effect: int, color: int) -> None:
    """TODO: заменить на реальный запуск эффекта на LED-палке (номер эффекта + номер цвета)."""
    effect_name = EFFECT_NAMES.get(effect, f"#{effect}")
    color_name = COLOR_NAMES.get(color, f"#{color}")
    print(f"[LED-EFFECT] {effect_name} / {color_name} (raw: {{{effect},{color}}})")


def play_tone(duration_s: float, freq_hz: int) -> None:
    """Блокирующее воспроизведение одного тона (вызывается в отдельном потоке)."""
    set_led(True)
    if winsound:
        winsound.Beep(int(freq_hz), max(1, int(duration_s * 1000)))
    else:
        print(f"[BEEP] {freq_hz} Hz x {duration_s:.2f}s")
        time.sleep(duration_s)
    set_led(False)


def play_morse_blocking(morse: str, wpm: float, tone_hz: int) -> None:
    """Проигрывает строку азбуки Морзе (та же нотация, что и на сервере/дисплее)."""
    if not morse:
        return
    unit = 1.2 / max(wpm, 1)
    words = [w.strip() for w in morse.split(" / ") if w.strip()]
    for w_idx, word in enumerate(words):
        letters = [l for l in word.split(" ") if l]
        for l_idx, letter in enumerate(letters):
            for symbol in letter:
                duration = unit * 3 if symbol == "-" else unit
                play_tone(duration, tone_hz)
                time.sleep(unit)  # межсимвольный интервал
            if l_idx < len(letters) - 1:
                time.sleep(unit * 2)  # добираем межбуквенный интервал (итого 3)
        if w_idx < len(words) - 1:
            time.sleep(unit * 4)  # добираем межсловный интервал (итого 7)


async def run(host: str, port: int, yacht_id: str) -> None:
    config_url = f"http://{host}:{port}/api/config"
    ws_url = f"ws://{host}:{port}/ws/yacht/{yacht_id}"

    wpm, tone_hz = 15, 600
    try:
        resp = requests.get(config_url, timeout=5)
        resp.raise_for_status()
        morse_cfg = resp.json().get("morse", {})
        wpm = morse_cfg.get("wpm", wpm)
        tone_hz = morse_cfg.get("tone_hz", tone_hz)
    except Exception as e:
        print(f"[yacht_client] Не удалось получить конфиг со стенда ({e}), использую значения по умолчанию.")

    backoff = 1.0
    while True:
        try:
            print(f"[yacht_client] Подключение к {ws_url} ...")
            async with websockets.connect(ws_url) as ws:
                print(f"[yacht_client] Подключено как '{yacht_id}'. Ожидание сообщений...")
                backoff = 1.0
                async for raw in ws:
                    data = json.loads(raw)
                    if data.get("type") != "play_morse":
                        continue
                    sender = data.get("sender")
                    text = data.get("text", "")
                    morse = data.get("morse", "")
                    effect, color = data.get("effect"), data.get("color")
                    print(f"[yacht_client] Проигрываю ({sender}): {text!r} -> {morse}")
                    if effect is not None and color is not None:
                        set_led_effect(effect, color)
                    await asyncio.to_thread(play_morse_blocking, morse, wpm, tone_hz)
        except (websockets.ConnectionClosed, OSError) as e:
            print(f"[yacht_client] Соединение потеряно ({e}). Переподключение через {backoff:.0f}с...")
        except Exception as e:
            print(f"[yacht_client] Неожиданная ошибка: {e}. Переподключение через {backoff:.0f}с...")
        await asyncio.sleep(backoff)
        backoff = min(backoff * 1.6, 15.0)


def main() -> None:
    parser = argparse.ArgumentParser(description="Клиент яхты для проекта 'Паруса'")
    parser.add_argument("--host", default="127.0.0.1", help="IP-адрес стенда в сети Wi-Fi")
    parser.add_argument("--port", type=int, default=8000, help="Порт сервера стенда")
    parser.add_argument("--yacht", required=True, help="ID яхты из config.json (например yacht1)")
    args = parser.parse_args()

    try:
        asyncio.run(run(args.host, args.port, args.yacht))
    except KeyboardInterrupt:
        print("\n[yacht_client] Остановлено пользователем.")
        sys.exit(0)


if __name__ == "__main__":
    main()
