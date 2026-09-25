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

Также умеет обновляться дистанционно: команда "update" с панели оператора
(/admin на стенде) запускает git pull + переустановку зависимостей и
перезапускает процесс — start_yacht_client.bat поднимет его заново.

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
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import requests
import websockets

PROJECT_ROOT = Path(__file__).resolve().parent.parent

try:
    import winsound
except ImportError:  # не Windows — работаем без реального звука
    winsound = None


def set_led(is_on: bool) -> None:
    """TODO: заменить на реальное управление LED-палкой/париком (GPIO/DMX/serial)."""
    pass


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


def run_update_and_exit() -> None:
    """Команда с панели оператора: git pull + переустановка зависимостей,
    затем процесс завершается — start_yacht_client.bat сам поднимет его
    заново через несколько секунд уже со свежим кодом."""
    print("[yacht_client] Получена команда обновления: git pull...")
    try:
        env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
        result = subprocess.run(
            ["git", "pull"], cwd=str(PROJECT_ROOT), capture_output=True, text=True, timeout=60, env=env
        )
        print(result.stdout)
        print(result.stderr)
        if result.returncode != 0:
            print("[yacht_client] git pull завершился с ошибкой, обновление отменено.")
            return

        changed = "Already up to date" not in (result.stdout or "") and "уже акту" not in (result.stdout or "").lower()
        if not changed:
            print("[yacht_client] Уже последняя версия, перезапуск не требуется.")
            return

        python_exe = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
        if python_exe.exists():
            pip = subprocess.run(
                [str(python_exe), "-m", "pip", "install", "--disable-pip-version-check", "-q", "-r", "requirements.txt"],
                cwd=str(PROJECT_ROOT), capture_output=True, text=True, timeout=180,
            )
            print(pip.stdout)
            print(pip.stderr)
    except Exception as e:
        print(f"[yacht_client] Ошибка обновления: {e}")
        return
    print("[yacht_client] Обновление применено, перезапуск...")
    time.sleep(1)
    os._exit(0)


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


class LedTable:
    """Таблица 3x3 для TouchDesigner: строка на яхту "номер эффект цвет".
    Приходит всегда целиком; при новой команде меняется только строка
    текущей яхты, остальные хранят последнее значение."""

    def __init__(self, count: int, udp_host: str, udp_port: int) -> None:
        self.rows = [[n, 0, 0] for n in range(1, count + 1)]
        self.addr = (udp_host, udp_port)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def update(self, number: int, effect: int, color: int) -> None:
        self.rows[number - 1] = [number, effect, color]
        payload = "\n".join(" ".join(str(x) for x in row) for row in self.rows) + "\n"
        try:
            self.sock.sendto(payload.encode("utf-8"), self.addr)
        except OSError as e:
            print(f"[UDP] не удалось отправить: {e}")
        print(f"[UDP] -> {self.addr[0]}:{self.addr[1]}\n{payload}")


play_lock = threading.Lock()
update_started = False


def play_locked(morse: str, wpm: float, tone_hz: int) -> None:
    with play_lock:
        play_morse_blocking(morse, wpm, tone_hz)


async def yacht_loop(host: str, port: int, yacht_id: str, number: int, table: LedTable, wpm: float, tone_hz: int) -> None:
    global update_started
    ws_url = f"ws://{host}:{port}/ws/yacht/{yacht_id}"
    backoff = 1.0
    while True:
        try:
            print(f"[yacht_client] Подключение к {ws_url} ...")
            async with websockets.connect(ws_url) as ws:
                print(f"[yacht_client] Подключено: {yacht_id} (яхта №{number})")
                backoff = 1.0
                async for raw in ws:
                    data = json.loads(raw)
                    msg_type = data.get("type")

                    if msg_type == "update":
                        if not update_started:
                            update_started = True
                            await asyncio.to_thread(run_update_and_exit)
                            update_started = False
                        continue

                    if msg_type != "play_morse":
                        continue
                    text = data.get("text", "")
                    morse = data.get("morse", "")
                    effect, color = data.get("effect"), data.get("color")
                    print(f"[yacht_client] {yacht_id} ({data.get('sender')}): {text!r} -> {morse}")
                    if effect is not None and color is not None:
                        set_led_effect(effect, color)
                        table.update(number, effect, color)
                    await asyncio.to_thread(play_locked, morse, wpm, tone_hz)
        except (websockets.ConnectionClosed, OSError) as e:
            print(f"[yacht_client] {yacht_id}: соединение потеряно ({e}). Повтор через {backoff:.0f}с...")
        except Exception as e:
            print(f"[yacht_client] {yacht_id}: ошибка: {e}. Повтор через {backoff:.0f}с...")
        await asyncio.sleep(backoff)
        backoff = min(backoff * 1.6, 15.0)


async def run(host: str, port: int, udp_host: str, udp_port: int) -> None:
    wpm, tone_hz = 15, 600
    yacht_ids = []
    while not yacht_ids:
        try:
            base = f"http://{host}:{port}"
            settings = requests.get(f"{base}/api/settings", timeout=5).json()
            morse_cfg = settings.get("morse", {})
            wpm = morse_cfg.get("wpm", wpm)
            tone_hz = morse_cfg.get("tone_hz", tone_hz)
            yacht_ids = [y["id"] for y in settings.get("yachts", [])]
        except Exception as e:
            print(f"[yacht_client] Стенд {host}:{port} пока недоступен ({e}). Повтор через 5с...")
            await asyncio.sleep(5)

    print(f"[yacht_client] Яхты: {yacht_ids}. UDP-таблица -> {udp_host}:{udp_port}")
    table = LedTable(len(yacht_ids), udp_host, udp_port)
    await asyncio.gather(
        *[yacht_loop(host, port, yid, n, table, wpm, tone_hz) for n, yid in enumerate(yacht_ids, start=1)]
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Клиент яхт для проекта 'Паруса' (один компьютер на все яхты)")
    parser.add_argument("--host", default="127.0.0.1", help="Адрес компьютера стенда в сети")
    parser.add_argument("--port", type=int, default=8000, help="Порт сервера стенда")
    parser.add_argument("--udp-host", default="127.0.0.1", help="Куда слать UDP-таблицу (TouchDesigner)")
    parser.add_argument("--udp-port", type=int, default=7000, help="UDP-порт TouchDesigner")
    parser.add_argument("--yacht", help="устарел, игнорируется (клиент сам подключается ко всем яхтам)")
    args = parser.parse_args()

    try:
        asyncio.run(run(args.host, args.port, args.udp_host, args.udp_port))
    except KeyboardInterrupt:
        print("\n[yacht_client] Остановлено пользователем.")
        sys.exit(0)


if __name__ == "__main__":
    main()
