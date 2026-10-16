import os
import sys
import threading
import time
import uvicorn

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

HOST = "127.0.0.1"
PORT = 8765


def start_backend_server():
    from backend.main import app
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")


if __name__ == "__main__":
    server_thread = threading.Thread(target=start_backend_server, daemon=True)
    server_thread.start()

    if "--headless" in sys.argv:
        while True:
            time.sleep(1)
    else:
        time.sleep(0.6)
        from desktop_overlay import run_native_overlay
        run_native_overlay()
