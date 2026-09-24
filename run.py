# run.py
# -*- coding: utf-8 -*-
"""
Запуск сервера стенда SAILS (первый компьютер — тот, что стоит на стенде,
подключён к Wi-Fi роутеру и к сенсорному экрану/колонке).

    python run.py

После запуска сам открывает Microsoft Edge в полноэкранном киоск-режиме
(без адресной строки и вкладок) — для сенсорного монитора стенда ничего
руками разворачивать не нужно. Закрывается по Alt+F4.
"""
import subprocess
import threading
import time
import webbrowser

import uvicorn

HOST = "0.0.0.0"
PORT = 8000


def _open_browser() -> None:
    time.sleep(1.2)
    url = f"http://localhost:{PORT}"
    try:
        # "start" ищет msedge через реестр Windows (App Paths), а не через PATH,
        # поэтому находит его на любом Windows 10/11 без дополнительной настройки.
        subprocess.Popen(
            [
                "cmd",
                "/c",
                "start",
                "msedge",
                "--kiosk",
                url,
                "--edge-kiosk-type=fullscreen",
                "--no-first-run",
                "--edge-kiosk-idle-timeout-minutes=0",
            ],
            shell=False,
        )
    except Exception:
        # Нет Edge или что-то пошло не так — открываем обычным браузером,
        # на весь экран придётся развернуть вручную (F11).
        webbrowser.open(url)


if __name__ == "__main__":
    print("=" * 60)
    print("SAILS — сервер стенда")
    print(f"Локально:     http://localhost:{PORT}")
    print("В сети Wi-Fi: http://<IP-этого-компьютера>:8000  (для yacht_client.py)")
    print("Стенд откроется сам в полноэкранном режиме (Edge, kiosk). Закрыть — Alt+F4.")
    print("Панель оператора с телефона: http://<IP-этого-компьютера>:8000/admin")
    print("=" * 60)

    threading.Thread(target=_open_browser, daemon=True).start()
    uvicorn.run("server.main:app", host=HOST, port=PORT, log_level="info")
