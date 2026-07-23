import subprocess
import sys
import time
import urllib.request
from pathlib import Path

API_DIR = Path(r"C:\Users\openclaw\AppData\Local\hermes\skills\ozmoeg\trip_planner\scripts")
CLOUDFLARED = Path(r"C:\Program Files (x86)\cloudflared\cloudflared.exe")
TUNNEL_ID = "73e22dd4-381e-4542-8d5a-e41d1682232d"
PYTHON = Path(r"C:\Users\openclaw\AppData\Local\Python\pythoncore-3.14-64\python.exe")
API_URL = "http://127.0.0.1:8777/health"
PUBLIC_URL = "https://trip-planner.aeyeing.com/health"
LOG = API_DIR / "watchdog.log"


def log(msg: str):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def api_healthy() -> bool:
    try:
        with urllib.request.urlopen(API_URL, timeout=5) as r:
            return r.status == 200
    except Exception:
        return False


def public_healthy() -> bool:
    try:
        import urllib.request
        req = urllib.request.Request(PUBLIC_URL, method="GET", headers={"User-Agent": "ozmoeg-watchdog/1.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            return b'"ok": true' in r.read()
    except Exception:
        return False


def kill_api():
    try:
        subprocess.run(["taskkill", "/F", "/FI", "IMAGENAME eq python.exe", "/FI", "COMMANDLINE eq *api.py*"], capture_output=True)
    except Exception as e:
        log(f"kill_api warning: {e}")


def kill_tunnel():
    try:
        subprocess.run(["taskkill", "/F", "/IM", "cloudflared.exe"], capture_output=True)
    except Exception as e:
        log(f"kill_tunnel warning: {e}")


def start_api():
    subprocess.Popen([str(PYTHON), str(API_DIR / "api.py")], cwd=str(API_DIR), creationflags=subprocess.CREATE_NO_WINDOW)


def start_tunnel():
    subprocess.Popen([str(CLOUDFLARED), "tunnel", "run", TUNNEL_ID], creationflags=subprocess.CREATE_NO_WINDOW)


def main():
    log("Python watchdog started")
    # Initial start if not running
    if not api_healthy():
        log("API not healthy at startup; starting API")
        kill_api()
        time.sleep(2)
        start_api()
        time.sleep(10)
    if not public_healthy():
        log("Public tunnel not healthy at startup; starting tunnel")
        kill_tunnel()
        time.sleep(2)
        start_tunnel()
        time.sleep(15)

    while True:
        need_api = not api_healthy()
        need_tunnel = not public_healthy()

        if need_api:
            log("API down; restarting")
            kill_api()
            time.sleep(2)
            start_api()
            time.sleep(12)

        if need_tunnel:
            log("Tunnel/public down; restarting")
            kill_tunnel()
            time.sleep(2)
            start_tunnel()
            time.sleep(20)

        if not need_api and not need_tunnel:
            log("Health OK")

        time.sleep(60)


if __name__ == "__main__":
    main()
