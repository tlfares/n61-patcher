"""Derive appearance-aware JPEG wallpapers from a local iPhone 6s IPSW.

N61's port stalled while decoding the stock HEIC assets. JPEGs avoid that
path while preserving separate light/dark assets in Wallpaper.plist. Apple
images are read from the user's local rootfs and are never stored in Git.
"""
import copy
from pathlib import Path
import plistlib
import subprocess

SCREEN = "375w-667h@2x~iphone"
COLORS = ((1510, "Warm"), (1520, "Cool"), (1530, "Neutral"))


def convert(source, dest, thumbnail=False):
    """Use the macOS ImageIO decoder, then center-crop to the N61 screen."""
    command = ["/usr/bin/sips", "-s", "format", "jpeg", "-s", "formatOptions", "90"]
    if not thumbnail:
        info = subprocess.check_output(
            ["/usr/bin/sips", "-g", "pixelWidth", "-g", "pixelHeight", str(source)], text=True
        ).splitlines()
        dimensions = dict(line.strip().split(": ", 1) for line in info
                          if line.strip().startswith(("pixelWidth:", "pixelHeight:")))
        width, height = int(dimensions["pixelWidth"]), int(dimensions["pixelHeight"])
        crop_width = min(width, round(height * 750 / 1334))
        crop_height = min(height, round(width * 1334 / 750))
        command += ["--cropToHeightWidth", str(crop_height), str(crop_width),
                    "--resampleHeightWidth", "1334", "750"]
    subprocess.run(command + [str(source), "--out", str(dest)], check=True,
                   stdout=subprocess.DEVNULL)
    if dest.read_bytes()[:2] != b"\xff\xd8":
        raise ValueError(f"ImageIO did not produce a JPEG: {dest}")


def prepare(source_root, output_root):
    """Return a deployable rootfs overlay; never connects to a device."""
    source = Path(source_root) / "Library/Wallpaper/Stills/iPhone"
    output_root = Path(output_root)
    destination = output_root / "Library/Wallpaper"
    destination.mkdir(parents=True, exist_ok=True)
    identifiers = []
    for original_id, color in COLORS:
        matches = list(source.glob(f"{original_id}.*-{SCREEN}.wallpaper"))
        if len(matches) != 1:
            raise ValueError(f"Expected one {original_id} wallpaper in {source}")
        bundle = matches[0]
        info = plistlib.loads((bundle / "Wallpaper.plist").read_bytes())
        if not info.get("appearanceAware") or info.get("logicalScreenClass") != SCREEN:
            raise ValueError(f"Unexpected wallpaper profile: {bundle}")
        new_id = original_id + 90000
        identifiers.append(new_id)
        dest = destination / "Stills/iPhone" / f"{new_id}.iOS14_{color}_JPEG-{SCREEN}.wallpaper"
        dest.mkdir(parents=True, exist_ok=True)
        result = copy.deepcopy(info)
        result.update(identifier=new_id, name=f"iOS 14 {color} (JPEG)")
        assets = result["assets"]["lockAndHome"]
        for appearance, suffix in (("default", "light"), ("dark", "dark")):
            asset = assets[appearance]
            asset["identifier"] = new_id + (1 if appearance == "default" else 2)
            for key, thumbnail in (("fullSizeImageFileName", False),
                                   ("thumbnailImageFileName", True)):
                filename = f"{color.lower()}-{suffix}{'-thumbnail' if thumbnail else ''}.jpg"
                convert(bundle / asset[key], dest / filename, thumbnail)
                asset[key] = filename
        result["thumbnailImageFileName"] = assets["default"]["thumbnailImageFileName"]
        (dest / "Wallpaper.plist").write_bytes(plistlib.dumps(result))
    # Advertise only the generated collection and the existing dynamic choices.
    # Live wallpapers need hardware/UI support that this N61 port has not tested.
    catalogue = [{"wallpaperType": "Dynamic"}, {
        "wallpaperType": "Still", "path": "Stills/iPhone",
        "order": {"default": identifiers}, "previews": {"default": identifiers[0]},
    }]
    (destination / "Wallpapers~iphone.plist").write_bytes(plistlib.dumps(catalogue))
    return output_root
