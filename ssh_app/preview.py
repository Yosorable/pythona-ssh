"""Loopback-only UI preview. No SSH, filesystem, or credential API is exposed."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .page import render_page


def serve(port=8878, language="en"):
    class Handler(BaseHTTPRequestHandler):
        def handle(self):
            try:
                super().handle()
            except (BrokenPipeError, ConnectionResetError):
                pass

        def do_GET(self):
            if self.path.split("?")[0] not in ("/", "/index.html"):
                self.send_error(404)
                return
            data = render_page(language, preview=True).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; font-src data:; base-uri 'none'; form-action 'none'")
            self.end_headers()
            self.wfile.write(data)

    with ThreadingHTTPServer(("127.0.0.1", port), Handler) as server:
        print(f"Pythona SSH preview: http://127.0.0.1:{server.server_port}")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
