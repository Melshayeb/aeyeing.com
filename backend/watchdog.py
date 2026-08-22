"""
Watchdog: keep the trip planner API AND the Cloudflare tunnel running.
Restarts the local API if /health fails and starts a manual cloudflared
process if the tunnel has no active connection.
"""
import subprocess
import time
import urllib.request
import socket
from pathlib import Path

API_DIR = Path(r"C:\Users\elsha\AppData\Local\hermes\skills\ozmoeg\trip_planner\scripts")
PYTHON = Path(r"C:\Python314\python.exe")
API_URL = "http://127.0.0.1:8777/health"
LOG = API_DIR / "watchdog.log"

CLOUDFLARED = Path(r"C:\Users\elsha\AppData\Local\hermes\skills\ozmoeg\trip_planner\scripts\cloudflared.exe")
TUNNEL_ID = "73e22dd4-381e-4542-8d5a-e41d1682232d"
TUNNEL_CONFIG = Path.home() / ".cloudflared" / "config.yml"
TUNNEL_LOG = Path.home() / ".cloudflared" / "cloudflared_manual_watchdog.log"
PUBLIC_URL = "https://trip-planner.aeyeing.com/ozmoeg/ozmoeg-latest.json"


def log(msg: str):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def api_healthy() -> bool:
    try:
        with urllib.request.urlopen(API_URL, timeout=5) as r:
            return r.status == 200
    except Exception:
        return False


def tunnel_healthy() -> bool:
    """True if the public URL returns 200 with a JSON content type."""
    try:
        req = urllib.request.Request(
            PUBLIC_URL,
            headers={"User-Agent": "ozmoeg-watchdog/1.0"},
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status == 200
    except Exception:
        return False


def tunnel_has_active_connection() -> bool:
    """Ask cloudflared whether the tunnel has an active edge connection."""
    if not CLOUDFLARED.exists():
        return False
    try:
        proc = subprocess.run(
            [str(CLOUDFLARED), "tunnel", "info", TUNNEL_ID],
            capture_output=True,
            text=True,
            timeout=30,
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        # Newer CLI prints "active connection" text; absence means down.
        if "active connection" in out.lower():
            return True
        # If the CLI output changed, treat "does not have any active connection" as down.
        if "does not have any active connection" in out:
            return False
        # Conservative default: assume up if command succeeded and didn't say down.
        return proc.returncode == 0 and "does not have" not in out.lower()
    except Exception as e:
        log(f"tunnel info check failed: {e}")
        return False


def kill_api():
    # Use WMIC to kill python processes running api.py; taskkill filters are unreliable.
    try:
        result = subprocess.run(
            ["powershell.exe", "-Command", "Get-WmiObject Win32_Process | Where-Object { $_.Name -like 'python*.exe' -and $_.CommandLine -like '%api.py%' } | Select-Object ProcessId -ExpandProperty ProcessId"],
            capture_output=True,
            text=True,
            timeout=20,
        )
        for line in (result.stdout or "").splitlines():
            parts = [p.strip() for p in line.split(",") if p.strip().isdigit()]
            for pid in parts:
                try:
                    subprocess.run(["taskkill", "/F", "/PID", pid], capture_output=True, timeout=10)
                except Exception as e:
                    log(f"taskkill pid {pid}: {e}")
    except Exception as e:
        log(f"kill_api warning: {e}")


def start_api():
    log("Starting API")
    subprocess.Popen(
        [str(PYTHON), str(API_DIR / "api.py")],
        cwd=str(API_DIR),
        creationflags=subprocess.CREATE_NO_WINDOW,
    )


def kill_tunnel():
    """Stop any manual cloudflared process we started (Console session)."""
    try:
        result = subprocess.run(
            ["powershell.exe", "-Command", "Get-WmiObject Win32_Process | Where-Object { $_.Name -like 'cloudflared.exe' } | Select-Object ProcessId,SessionId"],
            capture_output=True,
            text=True,
            timeout=20,
        )
        for line in (result.stdout or "").splitlines()[1:]:
            parts = [p.strip() for p in line.split(",") if p.strip()]
            if len(parts) >= 2 and parts[-1].isdigit() and parts[-1] != "0":
                pid = parts[-2]
                try:
                    subprocess.run(["taskkill", "/F", "/PID", pid], capture_output=True, timeout=10)
                    log(f"Killed manual cloudflared PID {pid}")
                except Exception as e:
                    log(f"taskkill cloudflared pid {pid}: {e}")
    except Exception as e:
        log(f"kill_tunnel warning: {e}")


def _load_tunnel_token() -> str:
    token_path = Path.home() / ".cloudflared" / ".tunnel_token"
    if token_path.exists():
        return token_path.read_text(encoding="utf-8").strip()
    return ""


def start_tunnel():
    log("Starting manual cloudflared tunnel")
    if not CLOUDFLARED.exists():
        log(f"cloudflared not found at {CLOUDFLARED}; cannot start tunnel")
        return
    if not TUNNEL_CONFIG.exists():
        log(f"tunnel config not found at {TUNNEL_CONFIG}; cannot start tunnel")
        return
    env = os.environ.copy()
    env["TUNNEL_TOKEN"] = _load_tunnel_token()
    with open(TUNNEL_LOG, "a", encoding="utf-8") as logf:
        subprocess.Popen(
            [str(CLOUDFLARED), "tunnel", "--config", str(TUNNEL_CONFIG), "run", TUNNEL_ID],
            cwd=str(Path.home() / ".cloudflared"),
            stdout=logf,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW,
            env=env,
        )


def main():
    log("API + tunnel watchdog started")

    if not api_healthy():
        log("API not healthy at startup; restarting API")
        kill_api()
        time.sleep(2)
        start_api()
        time.sleep(10)

    if not tunnel_healthy():
        log("Tunnel not healthy at startup; restarting tunnel")
        kill_tunnel()
        time.sleep(3)
        start_tunnel()
        time.sleep(15)

    while True:
        # API loop
        if not api_healthy():
            log("API down; restarting API")
            kill_api()
            time.sleep(2)
            start_api()
            time.sleep(12)
        else:
            log("API OK")

        # Tunnel loop
        if not tunnel_healthy():
            log("Tunnel down; restarting tunnel")
            kill_tunnel()
            time.sleep(3)
            start_tunnel()
            time.sleep(20)
        else:
            log("Tunnel OK")

        time.sleep(60)


if __name__ == "__main__":
    main()
