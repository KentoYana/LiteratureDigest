#!/usr/bin/env python3
"""Offline test of the installed package, resources and persistent user data."""

import argparse
import json
import os
import re
import sqlite3
import subprocess
from pathlib import Path
from xml.etree import ElementTree


def smoke(command, workdir):
    workdir = Path(workdir).absolute()
    workdir.mkdir(parents=True, exist_ok=True)
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in {"PYTHONPATH", "SARASHINA_API_KEY", "LITERATURE_DIGEST_HOME"}
    }
    root = workdir / "user-data"

    def cli(*args):
        result = subprocess.run(
            [str(command), "--home", str(root), *args],
            env=env,
            cwd=workdir,
            text=True,
            capture_output=True,
            check=True,
        )
        return result.stdout

    assert re.fullmatch(r"LiteratureDigest \d+\.\d+\.\d+\s*", cli("--version"))
    cli("--help")
    cli("init")
    config = root / "config/feeds.yaml"
    config.write_text("feeds: []\n# retained user configuration\n")
    db = root / "data/literature.db"
    with sqlite3.connect(db) as conn:
        conn.execute("""INSERT INTO articles(guid,title,abstract,fetched_at,updated_at,status)
                      VALUES('urn:test:preserve','Original title','','2026-11-03T00:00:00+00:00',
                             '2026-11-03T00:00:00+00:00','skipped')""")
    cli("init")
    assert "retained user" in config.read_text()
    cli("publish")
    root_xml = ElementTree.parse(root / "public/feed.xml")
    assert root_xml.findtext("channel/item/guid") == "urn:test:preserve"
    status = json.loads(cli("status"))
    assert status["articles"]["skipped"] == 1
    assert status["api_calls"] == 0
    assert json.loads(cli("doctor", "--offline"))["database"] == "ok"
    cli("run", "--dry-run")
    print("Installed CLI, bundled resources, RSS and persistent data: OK")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--command", required=True, type=Path)
    p.add_argument("--workdir", required=True, type=Path)
    a = p.parse_args()
    smoke(a.command.absolute(), a.workdir)
