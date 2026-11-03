#!/usr/bin/env python3
"""Build N61 light/dark JPEG wallpapers offline from a mounted iOS 13 rootfs."""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from patches.impl.rootfs.adaptive_wallpapers import prepare


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", required=True, type=Path,
                        help="read-only mounted iPhone 6s iOS 13.7 rootfs")
    parser.add_argument("--output", type=Path, default=Path("build/n61-wallpapers"),
                        help="rootfs overlay directory (default: build/n61-wallpapers)")
    args = parser.parse_args()
    root = prepare(args.source_root.resolve(), args.output.resolve())
    print(f"JPEG wallpaper overlay ready: {root}")


if __name__ == "__main__":
    main()
