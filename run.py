# run.py
# -*- coding: utf-8 -*-
"""
Запуск сервера стенда SAILS (первый компьютер — тот, что стоит на стенде,
подключён к Wi-Fi роутеру и к сенсорному экрану/колонке).

    python run.py

После запуска браузер автоматически откроет http://localhost:8000 —
разверните окно на полный экран (F11) на сенсорном мониторе стенда.
"""
import threading
import time
import webbrowser

import uvicorn

HOST = "0.0.0.0"
PORT = 8000


def _open_browser() -> None:
    time.sleep(1.2)
    webbrowser.open(f"http://localhost:{PORT}")


if __name__ == "__main__":
    print("=" * 60)
    print("SAILS — сервер стенда")
    print(f"Локально:     http://localhost:{PORT}")
    print("В сети Wi-Fi: http://<IP-этого-компьютера>:8000  (для yacht_client.py)")
    print("После открытия страницы разверните окно на полный экран (F11).")
    print("=" * 60)

    threading.Thread(target=_open_browser, daemon=True).start()
    uvicorn.run("server.main:app", host=HOST, port=PORT, log_level="info")
