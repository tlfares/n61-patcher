#!/usr/bin/env python3
"""Fetch the four pinned N61 firmware inputs directly from Apple's CDN.

Downloads remain in ignored ipsw/. Each file is streamed and checked against
its pinned size and SHA-256 before becoming a usable IPSW. Existing files are
verified rather than overwritten. No device connection is required.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import urllib.request
from urllib.parse import urlparse

REPO = Path(__file__).resolve().parents[1]
MANIFEST = Path(__file__).with_name("firmware_n61.json")
CHUNK = 8 * 1024 * 1024


def valid(path, entry):
    if path.stat().st_size != entry["size"]:
        return False
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest() == entry["sha256"]


def fetch(entry, directory, verify_only=False):
    path = directory / entry["filename"]
    if path.exists():
        if not valid(path, entry):
            raise ValueError(f"Existing file failed verification: {path}. Move it aside before retrying.")
        print(f"Verified {entry['profile']}: {path.name}", flush=True)
        return
    if verify_only:
        raise FileNotFoundError(f"Missing {path}")
    parsed = urlparse(entry["url"])
    if parsed.scheme != "https" or parsed.hostname != "updates.cdn-apple.com":
        raise ValueError("Firmware URLs must use Apple's HTTPS CDN")
    directory.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".part")
    print(f"Downloading {entry['profile']}: {path.name} ({entry['size'] / 1024**3:.2f} GiB)", flush=True)
    digest = hashlib.sha256()
    received = 0
    next_report = 256 * 1024 * 1024
    with urllib.request.urlopen(entry["url"], timeout=120) as source, partial.open("wb") as dest:
        while chunk := source.read(CHUNK):
            dest.write(chunk)
            digest.update(chunk)
            received += len(chunk)
            if received >= next_report:
                print(f"  {received * 100 / entry['size']:.0f}%", flush=True)
                next_report += 256 * 1024 * 1024
    if received != entry["size"] or digest.hexdigest() != entry["sha256"]:
        partial.unlink()
        raise ValueError(f"Download failed size/SHA-256 verification: {path.name}")
    partial.replace(path)
    print(f"Verified {path.name}", flush=True)


def main(argv=None):
    manifest = json.loads(MANIFEST.read_text())
    entries = {entry["profile"]: entry for entry in manifest["firmwares"]}
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profiles", nargs="+", choices=sorted(entries), default=list(entries),
                        help="profiles to fetch (default: n61 n66 n71 j96)")
    parser.add_argument("--output", type=Path, default=REPO / "ipsw")
    parser.add_argument("--verify-only", action="store_true", help="check existing inputs without network access")
    parser.add_argument("--list", action="store_true", help="print URLs and hashes without downloading")
    args = parser.parse_args(argv)
    for profile in args.profiles:
        entry = entries[profile]
        if args.list:
            print(f"{profile}: {entry['identifier']} iOS {entry['version']} ({entry['build']})")
            print(f"  {entry['url']}\n  SHA-256: {entry['sha256']}")
        else:
            fetch(entry, args.output, args.verify_only)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        sys.exit(1)
