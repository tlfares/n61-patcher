"""Create a systembag for encrypted DataB while preserving device-wide BAG1."""
from pathlib import Path
import subprocess

from core import log
from core.context import REPO
from core.tools import run

FRAMEWORK = "/System/Library/PrivateFrameworks/MobileKeyBag.framework/MobileKeyBag"
REMOTE = "/mnt6/.n56-bootstrap"
# Set KBSaveSystemBagHandle argument 5 to 1 to reuse existing BAG1 wrapping material.
PRESERVE_BAG1 = (0x8d20, bytes.fromhex("04008052"), bytes.fromhex("24008052"))


def patch_framework(data):
    offset, before, after = PRESERVE_BAG1
    if data[offset:offset + 4] != before:
        raise ValueError("MobileKeyBag does not match the 16H88 ramdisk profile; refusing to patch")
    return data[:offset] + after + data[offset + 4:]


def build_helper(ctx):
    source = Path(REPO) / "tools/systembag/create_systembag.c"
    output = ctx.wk("systembag/create_systembag")
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    sdk = subprocess.check_output(["xcrun", "--sdk", "iphoneos", "--show-sdk-path"], text=True).strip()
    run(["clang", "-arch", "arm64", "-isysroot", sdk, "-miphoneos-version-min=12.0", "-O2",
         str(source), "-o", output])
    run(["codesign", "-s", "-", "-f", "--entitlements",
         str(source.with_suffix(".entitlements")), output])
    return output


def build_framework(ctx):
    native = ctx.ssh.pull_file(FRAMEWORK, ctx.wk("systembag/MobileKeyBag.native"))
    output = Path(ctx.wk("systembag/MobileKeyBag.preserve-BAG1"))
    output.write_bytes(patch_framework(Path(native).read_bytes()))
    run(["codesign", "-s", "-", "-f", str(output)])
    return str(output)


def ensure_systembag(ctx):
    """Requires read-only /mnt1 and writable /mnt6; loads SEP and mounts /mnt7."""
    ssh = ctx.ssh
    ssh.ensure_sep()
    device = f'/dev/disk0s1s{ctx.t["mounts"]["data_b"]}'
    mode = ssh.sh(f'/sbin/mount | grep -q "{device} on /mnt7" && echo mounted || '
                  f'{{ /sbin/mount_apfs -o protect {device} /mnt7 && echo protect || '
                  f'{{ /sbin/mount_apfs {device} /mnt7 && echo plain; }}; }}').decode().strip()
    log.log(f"DataB mount mode: {mode}")
    if ssh.sh("test -s /mnt7/keybags/systembag.kb && echo yes || true").strip() == b"yes":
        log.log("Systembag already exists; skipping creation.")
        return
    log.log("Creating systembag while preserving BAG1...")
    helper = build_helper(ctx)
    framework = build_framework(ctx)
    ssh.deploy_path(helper, f"{REMOTE}/create_systembag")
    ssh.deploy_path(framework, f"{REMOTE}/MobileKeyBag.preserve-BAG1")
    ssh.sh(f'chmod 755 "{REMOTE}/create_systembag" "{REMOTE}/MobileKeyBag.preserve-BAG1"; '
           'mkdir -p /mnt7/keybags && chmod 700 /mnt7/keybags')
    print(ssh.sh(f'"{REMOTE}/create_systembag" --create /mnt7 "{REMOTE}/MobileKeyBag.preserve-BAG1"').decode(errors="replace"))
    ssh.sh(f'rm -rf "{REMOTE}"; test -s /mnt7/keybags/systembag.kb')
    ssh.sync()
