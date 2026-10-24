#!/usr/bin/env python3
"""Persistent reverse proxy: forwards LLM traffic from the S2S container to GPUStack.

Why this exists
---------------
The S2S pipeline runs inside a Docker container backed by WSL2. WSL2's NAT path to
the LAN GPUStack host (192.168.40.30) returns HTTP 502 for every request, while the
Windows host itself reaches GPUStack fine. So we run this tiny proxy ON THE WINDOWS
HOST (where the network works) and point the container's LLM base URL at it via
``host.docker.internal``. The container -> Windows host -> GPUStack path is proven to
return 200.

The proxy is streaming-capable (it forwards the response body in chunks) so the
OpenAI streaming endpoint used by the pipeline keeps working, and it forwards
request/response headers and bodies transparently.

Usage
-----
    python llm-proxy.py [listen_port] [upstream_host] [upstream_port]

Defaults: listen on 127.0.0.1:8891, upstream http://192.168.40.30:80.
"""
from __future__ import annotations

import http.client
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

UPSTREAM_HOST = sys.argv[2] if len(sys.argv) > 2 else "192.168.40.30"
UPSTREAM_PORT = int(sys.argv[3]) if len(sys.argv) > 3 else 80
LISTEN_HOST = "127.0.0.1"
LISTEN_PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8891

# Hop-by-hop headers that must not be blindly forwarded.
_HOP = {
    "host", "content-length", "connection", "keep-alive", "transfer-encoding",
    "upgrade", "te", "trailer", "proxy-authenticate", "proxy-authorization",
    "proxy-connection",
}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "llm-proxy/1.0"

    def log_message(self, fmt, *args):  # quiet unless you need access logs
        pass

    def _handle(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        fwd = {k: v for k, v in self.headers.items() if k.lower() not in _HOP}
        try:
            conn = http.client.HTTPConnection(UPSTREAM_HOST, UPSTREAM_PORT, timeout=300)
            conn.request(self.command, self.path, body=body, headers=fwd)
            resp = conn.getresponse()
            status = resp.status
            headers_sent = False
            try:
                # Stream the response body in chunks so OpenAI streaming keeps
                # its low-latency benefits (TTS can start before the full reply).
                self.send_response_only(status)
                for k, v in resp.getheaders():
                    if k.lower() in _HOP or k.lower() == "transfer-encoding":
                        continue
                    self.send_header(k, v)
                self.send_header("Transfer-Encoding", "chunked")
                self.end_headers()
                headers_sent = True
                while True:
                    chunk = resp.read(8192)
                    if not chunk:
                        break
                    self.wfile.write(b"%X\r\n" % len(chunk))
                    self.wfile.write(chunk)
                    self.wfile.write(b"\r\n")
                    self.wfile.flush()
                self.wfile.write(b"0\r\n\r\n")
                self.wfile.flush()
            finally:
                try:
                    conn.close()
                except Exception:
                    pass
        except Exception as exc:  # upstream unreachable
            if not headers_sent:
                msg = f"llm-proxy upstream error: {exc}".encode("utf-8")
                self.send_response(502)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(msg)))
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(msg)

    # http.server dispatches on do_<METHOD>; route every method through _handle.
    def do_GET(self):
        self._handle()

    def do_POST(self):
        self._handle()

    def do_PUT(self):
        self._handle()

    def do_DELETE(self):
        self._handle()

    def do_PATCH(self):
        self._handle()

    def do_OPTIONS(self):
        self._handle()


def main():
    httpd = ThreadingHTTPServer((LISTEN_HOST, LISTEN_PORT), Handler)
    print(
        f"llm-proxy listening on {LISTEN_HOST}:{LISTEN_PORT} -> "
        f"http://{UPSTREAM_HOST}:{UPSTREAM_PORT}",
        flush=True,
    )
    httpd.serve_forever()


if __name__ == "__main__":
    main()
