"""Build the N56 hardware kernel from the J96/N66 iOS 14 inputs."""
import json
from pathlib import Path
import re
from xml.sax.saxutils import escape
import shutil
import subprocess
import sys

from .boot_volumes import REPO
sys.path.insert(0, str(REPO / "patches/shared/impl/kc/vibration"))
from patches.shared.impl.kc.sn2400.macho import Kernel
from patches.shared.impl.kc.wifi import hashstore_patch as wifi
from patches.shared.impl.kc.vibration import transplant as vibration
from .kext import transplant

LAYOUTS = {
    "com.apple.driver.AppleSN2400Charger": {
        "__TEXT": (0xfffffff005cad140, "__PRELINK_TEXT"),
        "__TEXT_EXEC": (0xfffffff0077543a0, "__TEXT_EXEC"),
        "__DATA_CONST": (0xfffffff0070f5d00, "__DATA_CONST"),
        "__DATA": (0xfffffff007a1e970, "__PRELINK_DATA"),
    },
    "com.apple.driver.AppleChestnutDisplayPMU": {
        "__TEXT": (0xfffffff005cae150, "__PRELINK_TEXT"),
        "__TEXT_EXEC": (0xfffffff006d5a530, "__PLK_TEXT_EXEC"),
        "__DATA_CONST": (0xfffffff0070f66a0, "__DATA_CONST"),
        "__DATA": (0xfffffff007a1eaa0, "__PRELINK_DATA"),
    },
}
WIFI_APPROVED = dict(zip(wifi.OLD_HASHES, (
    "3ba18c1fe074b77ed0d46b9cc43914633b9ca4fe90ae502c9e655d5c11a1c88a",
    "cad7fd6d3718f86c5d2394e3570af4b23f0b419bf9725cd0ff7cc825a27922bb",
    "d687809bfb46fd11ca56f000b17c74e189f703946a83d43fae52e0827505f342",
)))


def touch(native, target, model="n56ap"):
    source = next(iter(native.kexts[f"com.apple.driver.AppleMultitouchSPI{model[:-2].upper()}"]["IOKitPersonalities"].values()))
    # Keep Apple's prelink serializer's integer widths and shared IDs intact.
    pattern = rb'(<key>AppleMultitouchSPI - J96</key><dict>)(.*?)(</dict></dict><key>CFBundleSignature</key>)'
    matches = list(re.finditer(pattern, target.xml, re.DOTALL))
    if len(matches) != 1:
        raise ValueError("Expected exactly one J96 touchscreen personality")
    match = matches[0]
    body = match[2]

    def encode(value):
        if isinstance(value, str):
            return b"<string>" + escape(value).encode() + b"</string>"
        if type(value) is int:
            return f'<integer size="64">{value:#x}</integer>'.encode()
        if isinstance(value, list):
            return b"<array>" + b"".join(encode(item) for item in value) + b"</array>"
        raise ValueError(f"Unsupported touchscreen property type: {type(value)}")

    for name in ("IONameMatch", "fll-mval", "mt-merge-personality", "ref-clk-div-val",
                 "touch-size-id", "parser-options"):
        key = f"<key>{name}</key>".encode()
        field = re.compile(re.escape(key) + rb'(?:<array>.*?</array>|<integer[^>]*(?:/>|>[^<]*</integer>)|<string[^>]*(?:/>|>[^<]*</string>))')
        old = field.search(body)
        if old and b' ID="' in old[0]:
            raise ValueError(f"Touchscreen property {name} owns a shared prelink ID")
        replacement = key + encode(source[name]) if name != "parser-options" else b""
        if old:
            body = body[:old.start()] + replacement + body[old.end():]
        elif name != "parser-options":
            if key in body:
                raise ValueError(f"Unrecognized touchscreen property encoding: {name}")
            body += replacement
    xml = target.xml[:match.start(2)] + body + target.xml[match.end(2):]
    segment = next(s for s in target.segs if s["name"] == "__PRELINK_INFO")
    if len(xml) > segment["fs"]:
        raise ValueError("Touch plist exceeds prelink capacity")
    data = bytearray(target.data)
    data[segment["fo"]:segment["fo"] + segment["fs"]] = xml.ljust(segment["fs"], b"\0")
    return data



def driver(input_path, donor_path, bundle, output):
    data, report = transplant(Kernel(donor_path), Kernel(input_path), bundle, LAYOUTS[bundle])
    output.write_bytes(data)
    return report


def adapt_wifi(input_path, firmware, output, resize_unique=False):
    target = Kernel(input_path)
    data, report = wifi.adapt(target, wifi.native_files(firmware), 0xfffffff007003be0,
                              header=0xfffffff006d6bcf8, expected_count=642,
                              approved=WIFI_APPROVED, resize_trx=True, resize_unique=resize_unique)
    wifi.add_slide_slots(target, data, report["new_slide_slots"])
    output.write_bytes(data)
    return report


def adapt_vibration(input_path, native, output):
    output.mkdir(parents=True, exist_ok=True)
    target = Kernel(input_path)
    symbols = output / "target-symbols.json"
    symbols.write_text(json.dumps({name: hex(address) for name, address in target.symbols().items()}))
    profile = dict(donor=native, pwm_meta=0xfffffff007901688, pwm_ctor=0xfffffff005dca5d0,
                   pwm_dtor=0xfffffff005dca5f0, iic_vtable=0xfffffff006d92340,
                   pwm_meta_vtable=0xfffffff006d9e6f8, delay_function=0xfffffff007136978,
                   clock_global=0xfffffff007901058, const_host="__DATA_CONST",
                   search_padding=True, symbols=symbols,
                   externs=Path(__file__).with_name("vibration-externs.json"))
    vibration.build(input_path, output, profile)
    return output / "kernelcache.vibration.raw"
