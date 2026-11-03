#!/usr/bin/env python3
"""Render a Formula only from an existing, version-checked source archive."""

import argparse
import hashlib
import json
import re
import tarfile
from pathlib import Path
from urllib.request import urlopen


def render(archive, output, url=None):
    archive = Path(archive).resolve()
    with tarfile.open(archive, "r:gz") as tar:
        metadata = next(
            x for x in tar.getmembers() if x.name.count("/") == 1 and x.name.endswith("/PKG-INFO")
        )
        text = tar.extractfile(metadata).read().decode()
    version = re.search(r"^Version: (\d+\.\d+\.\d+)$", text, re.M).group(1)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    if url:
        if not url.startswith("https://") or f"/v{version}/" not in url:
            raise ValueError("Release URL must be HTTPS and contain the matching fixed version")
        # Do not insert unverified URLs or hashes into a publishable Formula.
        with urlopen(url, timeout=60) as response:
            remote_digest = hashlib.sha256(response.read()).hexdigest()
        if remote_digest != digest:
            raise ValueError("Published archive does not match local SHA-256")
    else:
        url = archive.as_uri()
    root = Path(__file__).resolve().parents[1]
    resources = json.loads((root / "packaging/homebrew/resources.json").read_text())
    blocks = []
    for resource in resources:
        blocks.append(
            '  resource "{name}" do\n    url "{url}"\n    sha256 "{sha256}"\n  end\n'.format(
                **resource
            )
        )
    formula = (root / "packaging/homebrew/literature-digest.rb.in").read_text()
    for key, value in {
        "URL": url,
        "VERSION": version,
        "SHA256": digest,
        "RESOURCES": "\n".join(blocks),
    }.items():
        formula = formula.replace(f"@{key}@", value)
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(formula)
    print(f"{output}: version={version} sha256={digest}")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--archive", required=True)
    p.add_argument("--output", required=True)
    p.add_argument(
        "--url", help="Existing versioned GitHub Release asset URL; omitted for local test"
    )
    args = p.parse_args()
    render(args.archive, args.output, args.url)
