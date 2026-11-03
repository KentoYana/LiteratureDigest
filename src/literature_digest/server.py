"""Only /feed.xml is served; no filesystem mapping or directory listing."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .publisher import ET


def make_server(feed_path, port=8080, host="127.0.0.1"):
    if host != "127.0.0.1":
        raise ValueError("HTTPは127.0.0.1のみで待ち受けます")

    class Handler(BaseHTTPRequestHandler):
        server_version = "LiteratureDigest"
        sys_version = ""

        def do_GET(self):
            if self.path != "/feed.xml":
                self.send_error(404)
                return
            try:
                # Never follow a substituted symlink to an arbitrary local file.
                import os

                fd = os.open(feed_path, os.O_RDONLY | os.O_NOFOLLOW)
                with os.fdopen(fd, "rb") as feed:
                    content = feed.read(32 * 1024 * 1024 + 1)
                if len(content) > 32 * 1024 * 1024 or ET.fromstring(content).tag != "rss":
                    raise ValueError("invalid_feed")
            except (OSError, ValueError, ET.ParseError):
                self.send_error(503, "Feed unavailable; run publish")
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/rss+xml; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(content)

        def log_message(self, fmt, *args):
            # Do not log attacker-controlled paths, query strings or headers.
            pass

    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    return server
