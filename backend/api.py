"""
HTTP API for the OzMoEg Trip Planner website tab.
Uses only stdlib (http.server) so no Flask dependency is required.
"""
import os
import sys
import json
import smtplib
import shutil
import subprocess
import threading
import mimetypes
from pathlib import Path
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler, ThreadingHTTPServer
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.mime.text import MIMEText
from email import encoders
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).parent))
from generate import generate_excel
from parser import parse_request


PORT = int(os.environ.get("TRIP_PLANNER_PORT", 8777))
HOST = os.environ.get("TRIP_PLANNER_HOST", "")


def _load_env():
    env_path = Path(__file__).parent / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"'))


_load_env()


def _send_email(to: str, subject: str, body: str, attachment_path: str):
    """Send via gog CLI if available, otherwise fall back to SMTP."""
    gog = shutil.which("gog.exe") or shutil.which("gog")
    if gog:
        cmd = [
            gog, "gmail", "send",
            "-a", "aeyeingserver@gmail.com",
            "--to", to,
            "--subject", subject,
            "--body", body,
            "--attach", attachment_path,
            "-y"
        ]
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        return

    smtp_host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.environ.get("SMTP_PORT", 587))
    smtp_user = os.environ.get("SMTP_USER", "aeyeingserver@gmail.com")
    smtp_pass = os.environ.get("SMTP_PASS")
    if not smtp_pass:
        raise RuntimeError("SMTP_PASS not configured")

    msg = MIMEMultipart()
    msg["From"] = smtp_user
    msg["To"] = to
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    with open(attachment_path, "rb") as f:
        part = MIMEBase("application", "octet-stream")
        part.set_payload(f.read())
    encoders.encode_base64(part)
    part.add_header("Content-Disposition", f"attachment; filename={os.path.basename(attachment_path)}")
    msg.attach(part)

    with smtplib.SMTP(smtp_host, smtp_port) as server:
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.send_message(msg)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"[{datetime.utcnow().isoformat()}] {fmt % args}")

    def _json(self, status: int, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def _file(self, status: int, path: str, filename: str):
        with open(path, "rb") as f:
            data = f.read()
        mime, _ = mimetypes.guess_type(filename)
        self.send_response(status)
        self.send_header("Content-Type", mime or "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("X-Filename", filename)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(data)

    def _read_json_body(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length).decode("utf-8")
        data = json.loads(raw) if raw else {}
        # Website sends cities with a list of dates; scheduler wants start_date/end_date.
        for c in data.get("cities", []):
            if "dates" in c and isinstance(c["dates"], list) and c["dates"]:
                c["start_date"] = min(c["dates"])
                c["end_date"] = max(c["dates"])
        return data

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self._json(200, {"ok": True})
        elif parsed.path in ("/", "/ozmoeg-trip-planner.html", "/index.html"):
            # Serve the latest website HTML directly from the API if GitHub Pages is cached/stuck.
            html_candidates = [
                Path.home() / "Desktop" / "aeyeing.com" / "ozmoeg-trip-planner.html",
                Path(__file__).parent / "ozmoeg-trip-planner.html",
            ]
            html_path = None
            for p in html_candidates:
                if p.exists():
                    html_path = p
                    break
            if html_path:
                with open(html_path, "rb") as f:
                    data = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store, must-revalidate")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(data)
            else:
                self._json(404, {"error": "Website HTML not found"})
        elif parsed.path in (
            "/ozmoeg-trader-us.html", "/ozmoeg-trader-asx.html",
            "/ozmoeg/ozmoeg-trader-us.html", "/ozmoeg/ozmoeg-trader-asx.html",
        ):
            # Temporary mirror of scanner HTML while GitHub Pages deployment queue is stuck.
            base_dir = Path.home() / "Desktop" / "aeyeing.com"
            file_name = parsed.path.split("/")[-1]
            file_path = base_dir / file_name
            if not file_path.exists():
                self._json(404, {"error": f"{file_name} not found"})
                return
            data = file_path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store, must-revalidate")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(data)
        elif parsed.path.split("/")[-1].startswith(("ozmoeg-latest", "ozmoeg-manifest")) and parsed.path.split("/")[-1].endswith(".json"):
            # Serve OzMoEg live scanner JSON through the tunnel (rolling latest + any dated snapshot).
            base_dir = Path.home() / "Desktop" / "aeyeing.com"
            file_name = parsed.path.split("/")[-1]
            file_path = base_dir / file_name
            if not file_path.exists():
                self._json(404, {"error": f"{file_name} not found"})
                return
            data = file_path.read_bytes()
            mime, _ = mimetypes.guess_type(file_name)
            self.send_response(200)
            self.send_header("Content-Type", mime or "application/octet-stream")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, proxy-revalidate, max-age=0")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(data)
        else:
            # Static file fallback for anything else under the site root.
            base_dir = Path.home() / "Desktop" / "aeyeing.com"
            # Strip leading slash and path traversal attempts.
            clean_path = parsed.path.lstrip('/').replace('..', '')
            if not clean_path:
                clean_path = "index.html"
            file_path = base_dir / clean_path
            if not file_path.exists() or not file_path.is_file():
                self._json(404, {"error": "Not found"})
                return
            data = file_path.read_bytes()
            mime, _ = mimetypes.guess_type(file_path.name)
            self.send_response(200)
            self.send_header("Content-Type", mime or "application/octet-stream")
            self.send_header("Content-Length", str(len(data)))
            if mime == "text/html":
                self.send_header("Cache-Control", "no-store, must-revalidate")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(data)

    def _validate_trip(self, data: dict) -> tuple[bool, str]:
        """Reject incomplete trip data before generation."""
        if data.get("_error"):
            return False, data["_error"]
        if not data.get("cities"):
            return False, "No destination city found. Please include a city name, e.g. 'Santiago, Chile'."
        for c in data.get("cities", []):
            if not c.get("city"):
                return False, "Missing city name in request."
            if not c.get("start_date") or not c.get("end_date"):
                return False, f"Missing dates for {c.get('city')}."
        if not data.get("destination_country") or data.get("destination_country") == "Unknown Country":
            return False, "Could not determine destination country. Please include the country name."
        return True, ""

    def do_POST(self):
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/parse":
                data = self._read_json_body()
                text = data.get("text", "")
                if not text:
                    self._json(400, {"error": "Missing 'text' field"})
                    return
                parsed_data = parse_request(text)
                ok, err = self._validate_trip(parsed_data)
                if not ok:
                    self._json(400, {"error": err, "parsed": parsed_data})
                    return
                self._json(200, parsed_data)
            elif parsed.path == "/generate":
                data = self._read_json_body()
                ok, err = self._validate_trip(data)
                if not ok:
                    self._json(400, {"error": err})
                    return
                try:
                    pace = data.get("pace", "relaxed")
                    path = generate_excel(data, pace=pace)
                    # Update the cached/generated path so website visitors download the latest version.
                    latest_path = Path(path).parent / "Japan_Trip_Latest.xlsx"
                    shutil.copy(path, latest_path)
                    self._file(200, path, os.path.basename(path))
                except ValueError as e:
                    self._json(400, {"error": str(e)})
            elif parsed.path == "/generate-and-email":
                data = self._read_json_body()
                ok, err = self._validate_trip(data)
                if not ok:
                    self._json(400, {"error": err})
                    return
                email_to = data.get("requester_email", "")
                pace = data.get("pace", "relaxed")
                if not email_to:
                    self._json(400, {"error": "Missing requester_email"})
                    return

                def _generate_and_email():
                    log_prefix = f"[{datetime.utcnow().isoformat()}] [email task {email_to}]"
                    try:
                        start = datetime.utcnow()
                        print(f"{log_prefix} starting generation for {data.get('destination_country')}")
                        path = generate_excel(data, pace=pace)
                        duration = (datetime.utcnow() - start).total_seconds()
                        print(f"{log_prefix} generation took {duration:.1f}s -> {path}")
                        country = data.get('destination_country', 'Trip')
                        subject = f"Your {country} plan from OzMoEg Trip Planner"
                        body = (
                            f"Hi there,\n\n"
                            f"OzMoEg AI Assistant here — currently working inside the Aeyeing environment.\n"
                            f"Your {country} itinerary is ready.\n\n"
                            "The attached Excel workbook includes:\n"
                            "- Day-by-day schedule with city, weather and time-of-day slots\n"
                            "- Top hotel recommendation with live Nuitee benchmark rates (up to 2 hotels per city)\n"
                            "- Attractions, food suggestions, museums, markets and day trips\n"
                            "- Green highlights for confirmed selections; blue rows are free backups you can fill in\n"
                            "- A dedicated Hotels sheet with the best option pre-marked with 'X'\n\n"
                            "Open the file in Excel or Google Sheets and edit anything you like.\n\n"
                            "Cheers,\n"
                            "OzMoEg Trip Planner"
                        )
                        _send_email(email_to, subject, body, path)
                        print(f"{log_prefix} Sent {os.path.basename(path)} to {email_to}")
                    except Exception as exc:
                        import traceback
                        print(f"{log_prefix} Failed to send to {email_to}: {exc}")
                        print(traceback.format_exc())

                threading.Thread(target=_generate_and_email, daemon=True).start()
                self._json(202, {
                    "ok": True,
                    "message": f"Trip plan is being generated and will be emailed to {email_to} within a few minutes.",
                })
            else:
                self._json(404, {"error": "Not found"})
        except Exception as e:
            import traceback
            print(traceback.format_exc())
            self._json(500, {"error": str(e), "traceback": traceback.format_exc()})


def run():
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Trip Planner API listening on http://{HOST}:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    run()
