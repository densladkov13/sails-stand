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
import array
import asyncio
import io
import json
import math
import os
import socket
import subprocess
import sys
import threading
import time
import wave
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


REPO_URL = "https://github.com/densladkov13/sails-stand.git"


def find_git() -> str:
    """git из PATH, а если его нет — портативный MinGit, который ставит start-скрипт."""
    mingit = Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "MinGit" / "cmd" / "git.exe"
    if mingit.exists():
        return str(mingit)
    return "git"


def _git(args: list, timeout: int = 90) -> "subprocess.CompletedProcess":
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    return subprocess.run(
        [find_git()] + args, cwd=str(PROJECT_ROOT), capture_output=True, text=True, timeout=timeout, env=env
    )


def current_version() -> str:
    try:
        return _git(["rev-parse", "--short", "HEAD"], 10).stdout.strip() or "нет git"
    except Exception:
        return "нет git"


def run_update() -> dict:
    """Команда с панели оператора: подтянуть код с GitHub (fetch + reset --hard —
    на яхтенном компе локальных правок нет, зато так работает и у папки,
    скопированной без .git) и переустановить зависимости. Возвращает итог."""
    print("[yacht_client] Получена команда обновления...")
    try:
        before = current_version()
        if not (PROJECT_ROOT / ".git").exists():
            _git(["init", "-q"])
            _git(["remote", "add", "origin", REPO_URL])
        fetch = _git(["fetch", "origin"])
        if fetch.returncode != 0:
            msg = (fetch.stderr or fetch.stdout or "git fetch не удался").strip()
            print(f"[yacht_client] Ошибка: {msg}")
            return {"ok": False, "changed": False, "output": msg[:300]}
        reset = _git(["reset", "--hard", "origin/master"])
        if reset.returncode != 0:
            msg = (reset.stderr or reset.stdout or "git reset не удался").strip()
            print(f"[yacht_client] Ошибка: {msg}")
            return {"ok": False, "changed": False, "output": msg[:300]}
        after = current_version()
        changed = before != after
        if changed:
            python_exe = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
            if python_exe.exists():
                subprocess.run(
                    [str(python_exe), "-m", "pip", "install", "--disable-pip-version-check", "-q", "-r", "requirements.txt"],
                    cwd=str(PROJECT_ROOT), capture_output=True, text=True, timeout=180,
                )
        print(f"[yacht_client] Версия: {before} -> {after}")
        return {"ok": True, "changed": changed, "output": f"{before} -> {after}"}
    except Exception as e:
        print(f"[yacht_client] Ошибка обновления: {e}")
        return {"ok": False, "changed": False, "output": str(e)[:300]}


def build_morse_wav(morse: str, wpm: float, tone_hz: int) -> bytes:
    """Собирает всё сообщение азбукой Морзе в один WAV в памяти (16 бит, моно).
    Тайминг: точка = 1 единица, тире = 3, пауза между сигналами 1, между
    буквами 3, между словами 7 — как на сервере и на стенде. Короткие
    плавные нарастание/спад на каждом сигнале убирают щелчки."""
    rate = 22050
    unit = 1.2 / max(wpm, 1)
    ramp = min(0.004, unit / 3)
    samples = array.array("h")

    def silence(sec: float) -> None:
        samples.extend([0] * int(rate * sec))

    def tone(sec: float) -> None:
        n = int(rate * sec)
        r = max(1, int(rate * ramp))
        for i in range(n):
            env = min(1.0, i / r, (n - 1 - i) / r if n - 1 - i < r else 1.0)
            samples.append(int(20000 * env * math.sin(2 * math.pi * tone_hz * i / rate)))

    words = [w.strip() for w in morse.split(" / ") if w.strip()]
    for w_idx, word in enumerate(words):
        letters = [l for l in word.split(" ") if l]
        for l_idx, letter in enumerate(letters):
            for symbol in letter:
                tone(unit * 3 if symbol == "-" else unit)
                silence(unit)
            if l_idx < len(letters) - 1:
                silence(unit * 2)
        if w_idx < len(words) - 1:
            silence(unit * 4)

    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(samples.tobytes())
    return buf.getvalue()


def play_morse_blocking(morse: str, wpm: float, tone_hz: int) -> str:
    """Проигрывает сообщение азбукой Морзе через звук Windows по умолчанию
    и ждёт, пока оно доиграет. Возвращает текст ошибки или "" если всё хорошо."""
    if not morse:
        return ""
    error = ""
    set_led(True)
    try:
        wav = build_morse_wav(morse, wpm, tone_hz)
        if winsound:
            winsound.PlaySound(wav, winsound.SND_MEMORY)
        else:
            print(f"[BEEP] {len(wav)} байт, {tone_hz} Гц")
            time.sleep(len(wav) / 44100)
    except Exception as e:
        error = str(e)
        print(f"[yacht_client] Не удалось проиграть звук: {e}")
    finally:
        set_led(False)
    return error


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


def play_locked(morse: str, wpm: float, tone_hz: int) -> str:
    with play_lock:
        return play_morse_blocking(morse, wpm, tone_hz)


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
                            result = await asyncio.to_thread(run_update)
                            await ws.send(json.dumps({"type": "update_result", **result}))
                            if result["ok"] and result["changed"]:
                                print("[yacht_client] Обновление применено, перезапуск...")
                                await asyncio.sleep(1)
                                os._exit(0)
                            update_started = False
                        continue

                    if msg_type == "test_sound":
                        print("[yacht_client] Тест звука: SOS")
                        err = await asyncio.to_thread(play_locked, "... --- ...", wpm, tone_hz)
                        await ws.send(json.dumps({
                            "type": "sound_result", "ok": not err, "output": err or f"{wpm} сл/мин, {tone_hz} Гц",
                        }))
                        continue

                    if msg_type != "play_morse" or data.get("sender") != "yacht":
                        continue  # реплики зрителя звучат на стенде, здесь — только ответы яхт
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

    print(f"[yacht_client] Версия кода: {current_version()}. Яхты: {yacht_ids}. UDP-таблица -> {udp_host}:{udp_port}")
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
