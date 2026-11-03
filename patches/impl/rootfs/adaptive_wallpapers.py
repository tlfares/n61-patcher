"""Derive four appearance-aware JPEG wallpapers from a local iOS 13 IPSW.

N61's port stalled while decoding the stock HEIC assets. JPEGs avoid that
path while preserving separate light/dark assets in Wallpaper.plist. Apple
images are read from the user's local rootfs and are never stored in Git.
"""
import copy
from pathlib import Path
import plistlib
import subprocess

SCREEN = "375w-667h@2x~iphone"
COLORS = ((1210, "Orange"), (1220, "Green"), (1230, "Blue"), (1240, "Black"))


def convert(source, dest, thumbnail=False):
    """Use the macOS ImageIO decoder, then center-crop to the N61 screen."""
    # The full-size WWDC2019 HEIC images are 1634x1634. Their stock thumbnails
    # already have the portrait crop and should not be cropped a second time.
    command = ["/usr/bin/sips", "-s", "format", "jpeg", "-s", "formatOptions", "90"]
    if not thumbnail:
        command += ["--cropToHeightWidth", "1634", "919",
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
        dest = destination / "Stills/iPhone" / f"{new_id}.iOS13_{color}_JPEG-{SCREEN}.wallpaper"
        dest.mkdir(parents=True, exist_ok=True)
        result = copy.deepcopy(info)
        result.update(identifier=new_id, name=f"iOS 13 {color} (JPEG)")
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
