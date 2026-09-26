#!/usr/bin/env python3
"""Path-filtering reverse proxy in front of the CodeSage ingress.

Purpose: a public tunnel (ngrok/cloudflared) points at THIS proxy instead of
the app directly. Only ``POST /api/v1/webhooks/*`` is forwarded to the
ingress; every other path returns 404. That way exposing the box to the
internet reveals only the HMAC-verified webhook endpoint — login, API and
SPA stay unreachable from outside.

Stdlib-only (no dependencies), threaded, forwards request body and headers
untouched so GitHub's X-Hub-Signature-256 stays valid end-to-end.
"""

from __future__ import annotations

import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib import error, request

UPSTREAM = "http://10.171.24.201:80"
ALLOWED_PREFIX = "/api/v1/webhooks/"
LISTEN_HOST = "127.0.0.1"
LISTEN_PORT = 8081
MAX_BODY = 10 * 1024 * 1024  # webhook deliveries are small; cap at 10 MB

# Hop-by-hop / rewritten headers that must not be copied verbatim.
_SKIP_HEADERS = frozenset(
    {"host", "connection", "content-length", "transfer-encoding", "keep-alive"}
)


class WebhookOnlyProxy(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    # --- helpers -----------------------------------------------------------
    def _respond(self, status: int, body: bytes, content_type: str = "text/plain") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _route(self) -> None:
        if not self.path.startswith(ALLOWED_PREFIX):
            # Anything outside the webhook surface is invisible to the internet.
            self._respond(404, b"not found\n")
            return
        self._forward()

    def _forward(self) -> None:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            self._respond(400, b"bad content-length\n")
            return
        if length > MAX_BODY:
            self._respond(413, b"payload too large\n")
            return
        body = self.rfile.read(length) if length else None

        headers = {
            k: v
            for k, v in self.headers.items()
            if k.lower() not in _SKIP_HEADERS
        }
        headers["X-Forwarded-Proto"] = "https"  # TLS terminates at the tunnel edge

        req = request.Request(
            UPSTREAM + self.path, data=body, headers=headers, method=self.command
        )
        try:
            with request.urlopen(req, timeout=180) as resp:
                data = resp.read()
                self.send_response(resp.status)
                for k, v in resp.getheaders():
                    if k.lower() in _SKIP_HEADERS:
                        continue
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(data)
        except error.HTTPError as e:
            data = e.read()
            self.send_response(e.code)
            for k, v in e.headers.items():
                if k.lower() in _SKIP_HEADERS:
                    continue
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(data)
        except Exception as e:  # upstream unreachable etc.
            self._respond(502, f"upstream error: {e}\n".encode())

    # --- verbs -------------------------------------------------------------
    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = do_HEAD = do_OPTIONS = _route

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))


if __name__ == "__main__":
    server = ThreadingHTTPServer((LISTEN_HOST, LISTEN_PORT), WebhookOnlyProxy)
    print(
        f"webhook-proxy: {LISTEN_HOST}:{LISTEN_PORT} -> {UPSTREAM} "
        f"(allow: {ALLOWED_PREFIX}*)",
        flush=True,
    )
    server.serve_forever()
