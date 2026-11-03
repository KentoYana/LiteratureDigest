"""Secrets come only from the environment or the macOS login keychain."""

import getpass
import os
import subprocess
import sys

SERVICE = "ai.sarashina.LiteratureDigest"


def api_key():
    value = os.environ.get("SARASHINA_API_KEY", "").strip()
    if value:
        return value
    if sys.platform != "darwin":
        return ""
    try:
        result = subprocess.run(
            [
                "/usr/bin/security",
                "find-generic-password",
                "-s",
                SERVICE,
                "-a",
                getpass.getuser(),
                "-w",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""
