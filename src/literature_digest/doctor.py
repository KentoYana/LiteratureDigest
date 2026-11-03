"""Read-only diagnosis. Never send a paid request or print a credential."""

import sqlite3
import sys
from urllib.request import ProxyHandler, build_opener
from xml.etree import ElementTree

from .config import load_feeds, load_settings, template
from .credentials import api_key


def diagnose(paths, offline=False):
    checks = {"python": "ok" if sys.version_info >= (3, 11) else "error"}
    try:
        import ssl

        checks["python_tls"] = "ok" if ssl.OPENSSL_VERSION else "error"
    except ImportError:
        checks["python_tls"] = "error"
    try:
        settings = load_settings(paths)
        load_feeds(paths)
        template("prompts/digest.md")
        checks["config_and_resources"] = "ok"
    except ValueError:
        checks["config_and_resources"] = "error"
        settings = None
    try:
        conn = sqlite3.connect(paths.db.as_uri() + "?mode=ro", uri=True, timeout=5)
        try:
            checks["database"] = (
                "ok" if conn.execute("PRAGMA quick_check").fetchone()[0] == "ok" else "error"
            )
            checks["schema"] = (
                "ok" if conn.execute("PRAGMA user_version").fetchone()[0] == 1 else "error"
            )
        finally:
            conn.close()
    except sqlite3.Error:
        checks["database"] = "error"
    if offline:
        checks["api_authentication"] = "not checked (offline)"
        checks["http"] = "not checked (offline)"
    else:
        checks["api_authentication"] = (
            "configured (validity unverified)" if api_key() else "missing"
        )
        if settings:
            try:
                with build_opener(ProxyHandler({})).open(
                    f"http://127.0.0.1:{settings['server']['port']}/feed.xml", timeout=2
                ) as response:
                    if response.headers.get_content_type() != "application/rss+xml":
                        raise ValueError("content_type")
                    if ElementTree.fromstring(response.read(32 * 1024 * 1024)).tag != "rss":
                        raise ValueError("root")
                    checks["http"] = "ok"
            except Exception:
                checks["http"] = "not running or invalid feed (service startで起動)"
    return checks
