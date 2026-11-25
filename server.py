#!/usr/bin/env python3
"""Serve the oscilloscope control panel on the Linux host's loopback interface."""

import argparse
import csv
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from ipaddress import IPv4Address
from io import StringIO
import json
from pathlib import Path
from secrets import token_urlsafe
from threading import Lock
from urllib.parse import parse_qs, urlsplit

from instrument import Oscilloscope, ProtocolError, channel_number


STATIC = Path(__file__).resolve().parent / "static"
ASSETS = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/style.css": ("style.css", "text/css; charset=utf-8"),
}
MAX_CONTROL_SESSIONS = 128


class Handler(BaseHTTPRequestHandler):
    server_version = "OscilloControl"

    def setup(self):
        super().setup()
        self.connection.settimeout(12)

    def allowed_host(self):
        return self.headers.get("Host") in self.server.allowed_hosts

    def reply(self, status, content_type, body, extra=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        if extra:
            for key, value in extra.items():
                self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def reply_json(self, status, payload):
        self.reply(status, "application/json; charset=utf-8", json.dumps(payload).encode())

    def error(self, status, message):
        self.reply_json(status, {"error": message})

    def scope_route(self):
        uri = urlsplit(self.path)
        segments = uri.path.split("/")
        if len(segments) != 4 or segments[:2] != ["", "api"]:
            raise KeyError("Unknown endpoint")
        return self.server.scopes[segments[2]], segments[3], parse_qs(uri.query)

    def do_GET(self):
        if not self.allowed_host():
            self.error(403, "Open the panel through its portal link or on localhost")
            return

        if self.path in ASSETS:
            file, content_type = ASSETS[self.path]
            self.reply(200, content_type, (STATIC / file).read_bytes())
            return
        if self.path == "/api/scopes":
            self.reply_json(200, [
                {"id": key, "address": scope.address, "port": scope.port}
                for key, scope in self.server.scopes.items()
            ])
            return

        try:
            scope, service, args = self.scope_route()
            if service == "state":
                result = scope.state()
            elif service == "screen":
                result = scope.screenshot()
            elif service in ("waveform", "waveform.csv"):
                channel = channel_number(int(args.get("channel", ["1"])[0]))
                result = scope.waveform(channel)
            else:
                raise KeyError("Unknown endpoint")
        except KeyError:
            self.error(404, "Unknown endpoint")
            return
        except ValueError as error:
            self.error(400, str(error))
            return
        except (OSError, ProtocolError) as error:
            self.error(503, str(error))
            return

        try:
            if service == "screen":
                self.reply(200, "image/png", result)
            elif service == "waveform.csv":
                self.csv_download(result, channel)
            else:
                self.reply_json(200, result.preview() if service == "waveform" else result)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def csv_download(self, waveform, channel):
        self.send_response(200)
        self.send_header("Content-Type", "text/csv; charset=utf-8")
        self.send_header("Content-Disposition", f'attachment; filename="CH{channel}-waveform.csv"')
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

        buffer = StringIO()
        writer = csv.writer(buffer)
        writer.writerow(("sample", "time_from_first_sample_s", f"value_{waveform.unit}", "adc_count"))
        for index, value in enumerate(waveform.samples):
            writer.writerow((index, f"{index * waveform.interval:.12g}",
                             f"{value * waveform.scale:.12g}", value))
            if index % 1024 == 1023:
                self.wfile.write(buffer.getvalue().encode())
                buffer.seek(0)
                buffer.truncate()
        self.wfile.write(buffer.getvalue().encode())

    def update_control_session(self, enabled, token):
        if not isinstance(enabled, bool):
            raise ValueError("Choose whether to enable control")
        with self.server.control_sessions_lock:
            sessions = self.server.control_sessions
            if not enabled:
                sessions.pop(token, None)
                return {}
            if len(sessions) >= MAX_CONTROL_SESSIONS:
                sessions.pop(next(iter(sessions)))
            token = token_urlsafe(24)
            sessions[token] = None
        return {"token": token}

    def do_POST(self):
        if not self.allowed_host() or self.headers.get("Origin") != f"http://{self.headers.get('Host')}":
            self.error(403, "The command must come from the origin serving this control panel")
            return
        if self.headers.get_content_type() != "application/json":
            self.error(415, "Send application/json")
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 1 <= size <= 2048:
                raise ValueError("Invalid command length")
            body = json.loads(self.rfile.read(size))
            if not isinstance(body, dict):
                raise ValueError("Expected a command object")
            token = self.headers.get("X-Oscillo-Session", "")
            if self.path == "/api/control-session":
                result = self.update_control_session(body.get("enabled"), token)
            else:
                scope, service, _ = self.scope_route()
                if service != "control":
                    raise KeyError("Unknown endpoint")
                with self.server.control_sessions_lock:
                    enabled = token in self.server.control_sessions
                if not enabled:
                    self.error(403, "Click Enable control to send instrument commands")
                    return
                value = scope.operate(body.get("action"), body.get("channel"), body.get("value"))
                result = {"value": value}
        except KeyError:
            self.error(404, "Unknown endpoint")
        except (ValueError, UnicodeError) as error:
            self.error(400, str(error))
        except (OSError, ProtocolError) as error:
            self.error(503, str(error))
        else:
            self.reply_json(200, result)

    def log_message(self, format, *args):
        if len(args) > 1 and str(args[1]).isdigit() and int(args[1]) >= 400:
            super().log_message(format, *args)


def port_number(text):
    value = int(text)
    if not 1 <= value <= 65535:
        raise argparse.ArgumentTypeError("Port must be between 1 and 65535")
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--http-port", type=port_number, default=8765)
    parser.add_argument("--portal-host", type=IPv4Address, action="append", default=[],
                        help="allow this portal address as Host when proxied by nginx (repeatable)")
    parser.add_argument("--scope01", type=IPv4Address, default="192.168.50.128")
    parser.add_argument("--scope02", type=IPv4Address, default="192.168.50.129")
    parser.add_argument("--device-port", type=port_number, default=3000)
    options = parser.parse_args()

    scopes = {key: Oscilloscope(str(address), options.device_port)
              for key, address in (("01", options.scope01), ("02", options.scope02))}
    with ThreadingHTTPServer(("127.0.0.1", options.http_port), Handler) as server:
        server.scopes = scopes
        server.allowed_hosts = {f"127.0.0.1:{server.server_port}", f"localhost:{server.server_port}"}
        server.allowed_hosts.update(str(address) for address in options.portal_host)
        server.control_sessions = {}
        server.control_sessions_lock = Lock()
        print(f"Oscillo Control: http://127.0.0.1:{server.server_port}/", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
