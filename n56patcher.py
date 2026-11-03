#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""n56patcher.py: experimental iOS 13 second-system patcher for N56/N61.

Read targets/<name>.py and the patches registry, select features and dependencies,
and use local IPSWs plus upstream tools to build and install a second system.

Commands:
  ramdisk       Boot an iOS 12.5.8 SSH ramdisk from DFU.
  extract-im4m  Read this device's onboard ticket from NOR; repeat after restore.
  volumes       Create SystemB/DataB with role 0 through the ramdisk.
  rootfs        Stream the iOS 13 root filesystem to SystemB (requires sudo).
  patch-rootfs  Apply overlays, finalize DataB/SEP/keybags, and set APFS roles.
  build         Build iBSS, iBEC, DeviceTree, TrustCache, and KernelCache.
  boot          Send the boot chain through DFU (build first if missing).
  install       Run volumes, rootfs, and patch-rootfs for a fresh installation.
  all           Prepare inputs, boot ramdisk, extract ticket, install, build, boot.
  list          List selected patches.
  status        Inspect APFS roles through the ramdisk.

Example:
  python3 n56patcher.py list --target n61-ios13
  python3 n56patcher.py build --target n61-ios13 --workdir build/n61
  python3 n56patcher.py boot --target n61-ios13 --workdir build/n61
"""
import argparse
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, REPO)

from core import log, patch as patchmod
from core.context import Context, STATE_DIR
from core.ramdisk import Ramdisk
from core.apfs import Apfs
from core.tools import Tools, run
from core.trustcache import TrustCache


class Flow:
    def __init__(self, ctx, selection, allow_manual=False, identity_check=True):
        self.ctx = ctx
        self.sel = selection
        self.t = ctx.tools = Tools(ctx)
        self.rd = Ramdisk(ctx)
        self.allow_manual = allow_manual
        self.identity_check = identity_check

    # ============================ ramdisk ============================
    def ramdisk(self):
        log.log("Booting the iOS 12.5.8 SSH ramdisk…")
        if self.ctx.dry_run:
            log.log("Dry run: skipping device transmission.")
            return
        self.rd.boot()

    def _need_ramdisk(self):
        if self.ctx.dry_run:
            return
        self.rd.ensure()

    def status(self):
        if self.ctx.dry_run:
            log.log("Dry run: skipping volume inspection.")
            return
        self._need_ramdisk()
        Apfs(self.ctx).list()

    # ============================ extract-im4m =======================
    def extract_im4m(self):
        """Extract this device's onboard ticket from NOR (/dev/disk2) into state/IM4M.bin.

        The onboard APTicket changes after a restore. Extract a fresh ticket before personalizing components with -M;
          otherwise build cannot personalize the boot components.
        """
        if self.ctx.dry_run:
            log.log("Dry run: skipping ticket extraction.")
            return None
        self._need_ramdisk()
        os.makedirs(STATE_DIR, exist_ok=True)
        disk2 = os.path.join(STATE_DIR, "disk2.bin")
        out = os.path.join(STATE_DIR, "IM4M.bin")
        log.log("Reading 4 MiB from NOR (/dev/disk2) and extracting IM4M…")
        data = self.rd.sh("dd if=/dev/disk2 bs=256 count=%d 2>/dev/null" % 0x4000, timeout=120)
        if len(data) < 0x1000:
            log.die(f"Unexpected NOR read: only {len(data)} bytes; check the ramdisk and /dev/disk2")
        with open(disk2, "wb") as f:
            f.write(data)
        run([self.ctx.tool("img4"), "-i", disk2, "-m", out])
        sz = os.path.getsize(out)
        log.log(f"New IM4M: {out} ({sz} bytes)")
        return out

    # ============================ volumes ============================
    def volumes(self):
        if self.ctx.dry_run:
            log.log("Dry run: skipping volume creation.")
            return
        self._need_ramdisk()
        encrypt = self._data_encrypt()
        apfs = Apfs(self.ctx)
        created = apfs.create_volumes(self.ctx.t["volumes"]["create"], encrypt_data=encrypt)
        if created:
            # Create with role 0; set_roles updates roles after unmounting during patch-rootfs.
            apfs.list()

    def _data_encrypt(self):
        return str(self.ctx.t.get("data_protection", "encrypted")).lower() == "encrypted"

    # ============================ rootfs =============================
    def rootfs(self):
        self._need_ramdisk()
        if not self.ctx.dry_run:
            Apfs(self.ctx).validate_layout(require_second_system=True)
        try:
            self._run_patches(["stream"])
        finally:
            self.ctx.close_source_mounts()

    # ============================ patch-rootfs =======================
    def patch_rootfs(self):
        self._need_ramdisk()
        if not self.ctx.dry_run:
            Apfs(self.ctx).validate_layout(require_second_system=True)
        try:
            self._run_patches(["overlay", "finalize"])
        finally:
            self.ctx.close_source_mounts()

    def install(self):
        self.volumes()
        self.rootfs()
        self.patch_rootfs()

    def _run_patches(self, roles):
        """Run selected rootfs roles in registry order."""
        ran = 0
        for p in self.sel.get("rootfs", []):
            if p.role not in roles:
                continue
            if p.manual and not self.allow_manual:
                log.warn(f"Skipping manual patch {p.id} (requires --allow-manual); {p.note}")
                continue
            log.log(f"→ {p.id}  ({p.note})")
            if self.ctx.dry_run:
                continue
            p.apply(self.ctx)
            ran += 1
        log.log(f"Rootfs {roles} complete; applied {ran} patches.")

    # ============================ build ==============================
    def build(self):
        """Build five boot components into workdir/boot_*.img4."""
        w = self.ctx.wk
        if not self.ctx.im4m_is_fresh():
            log.warn("No local IM4M found (state/IM4M.bin).")
            log.warn("After restoring the device, run extract-im4m first; components may otherwise fail validation.")
        log.log(f"Building boot components → {self.ctx.work}")
        self._build_ibss(w("boot_iBSS.img4"))
        self._build_ibec(w("boot_iBEC.img4"))
        self._build_dt(w("boot_DT.img4"))
        self._build_tc(w("boot_TC.img4"))
        self._build_kc(w("boot_KC.img4"))
        log.log("All five boot components built:")
        for n in ("boot_iBSS", "boot_iBEC", "boot_DT", "boot_TC", "boot_KC"):
            f = w(n + ".img4")
            log.log(f"  {n}.img4  {os.path.getsize(f) if os.path.exists(f) else 'missing'}")
        self.ctx.close_source_mounts()
        return self.ctx.work

    def _build_ibss(self, out):
        log.log("iBSS…")
        if self.ctx.dry_run:
            return
        self.t.img4_sign(self.ctx.donor("ibss_src"), out, "ibss")

    def _build_ibec(self, out):
        log.log("iBEC (boot arguments + kairos root matching + personalization)…")
        if self.ctx.dry_run:
            return
        patched = self.ctx.wk("iBEC.patched")
        kaired = self.ctx.wk("iBEC.kairos")
        self.t.iboot_patch(self.ctx.donor("ibec_dec"), patched, self.ctx.t["bootargs"])
        self.t.kairos(patched, kaired, self.ctx.t["root_part"])
        self.t.img4_sign(kaired, out, "ibec")

    def _build_dt(self, out):
        log.log("DeviceTree (selected DT patches + rdtr personalization)…")
        dt = self.sel.get("dt", [])
        base = next((p for p in dt if p.role == "base"), None)
        if base is None:
            log.die("No DT base selected (profile bases['dt'])")
        if self.ctx.dry_run:
            return
        art = base.apply(self.ctx)
        for p in dt:
            if p.role == "transform":
                log.log(f"  dt transform: {p.id}")
                art = p.apply(self.ctx, art)
        self.t.img4_sign(art, out, "rdtr")

    def _build_tc(self, out):
        log.log("TrustCache…")
        if self.ctx.dry_run:
            return
        import shutil
        daemon_dir = self.ctx.t.get("launchd_daemon_dir")
        if self.ctx.t.get("full_trustcache"):
            raw = TrustCache(self.ctx).build_full()
            self.t.img4_wrap_tc(raw, out)
        elif daemon_dir:
            res = TrustCache(self.ctx).build_launchd_cache(self.ctx.req(daemon_dir))
            self.t.img4_wrap_tc(res["raw"], out)
        else:
            # Personalize the original static trust cache as rtsc
            run([self.ctx.tool("img4"), "-i", self.ctx.donor("trustcache"),
                 "-o", out, "-M", self.ctx.im4m(), "-T", "rtsc"])

    def _build_kc(self, out):
        log.log("KernelCache (selected KC patches + mkcomplzss + watchtower + rkrn personalization)…")
        kc = self.sel.get("kc", [])
        base = next((p for p in kc if p.role == "base"), None)
        if base is None:
            log.die("No KC base selected (profile bases['kc'])")
        if self.ctx.dry_run:
            return
        raw = base.apply(self.ctx)
        for p in kc:
            if p.role == "transform":
                log.log(f"  kc transform: {p.id}")
                raw = p.apply(self.ctx, raw)
        self._pack_kc(raw, out)

    def _pack_kc(self, raw, out):
        """Pack the raw kernel with mkcomplzss, watchtower, and img4; verify extraction matches."""
        ref = self.ctx.donor("j96_kernel")
        mklzss = self.ctx.wk("mkcomplzss")
        run(["cc", "-O2", "-I", self.ctx.local("tools/img4lib"),
             self.ctx.local("patches/impl/kc/chestnut/mkcomplzss.c"),
             self.ctx.local("tools/img4lib/lzss.c"), "-o", mklzss])
        append_wt = self.ctx.local("patches/impl/kc/chestnut/append_watchtower.py")
        lzss = self.ctx.wk("kc.lzss")
        full = self.ctx.wk("kc.full.lzss")
        run([mklzss, raw, lzss])
        run(["python3", append_wt, ref, lzss, full])
        self.t.img4_sign_replace(ref, out, "rkrn", full)
        # Round trip: extracted raw bytes must match the input
        rt = self.ctx.wk("kc.roundtrip.raw")
        self.t.img4_extract(out, rt)
        r = subprocess.run(["cmp", raw, rt], capture_output=True)
        if r.returncode != 0:
            log.die("KC round-trip check failed: extracted bytes differ from input")
        log.log("  KC round-trip check passed.")

    # ============================ boot ===============================
    def boot(self):
        import time
        w = self.ctx.wk
        imgs = {n: w(f"boot_{n}.img4") for n in ("iBSS", "iBEC", "DT", "TC", "KC")}
        if not all(os.path.exists(p) for p in imgs.values()):
            log.log("No built components found; building first…")
            self.build()
        if self.ctx.dry_run:
            log.log("Dry run: skipping device transmission.")
            return

        irec = self.ctx.tool("irecovery")
        gaster = self.ctx.tool("gaster")
        self.rd.dfu_ensure()
        self._identity_guard()

        log.step(1, 7, "Prepare DFU (gaster pwn/reset)")
        q = run([irec, "-q"], check=False, timeout=10).stdout or b""
        if b"PWND" not in q:
            run([gaster, "pwn"], capture=False)
        run([gaster, "reset"], capture=False, check=False); time.sleep(1)
        log.step(2, 7, "Send iBSS"); run([irec, "-f", imgs["iBSS"]], capture=False); time.sleep(3)
        log.step(3, 7, "Send iBEC"); run([irec, "-f", imgs["iBEC"]], capture=False); time.sleep(3)
        log.step(4, 7, "Send DeviceTree")
        run([irec, "-f", imgs["DT"]], capture=False); run([irec, "-c", "devicetree"], capture=False); time.sleep(1)
        log.step(5, 7, "Send TrustCache")
        run([irec, "-f", imgs["TC"]], capture=False); run([irec, "-c", "firmware"], capture=False); time.sleep(1)
        log.step(6, 7, "Send KernelCache"); run([irec, "-f", imgs["KC"]], capture=False)
        log.step(7, 7, "Boot iOS 13 (bootx)"); run([irec, "-c", "bootx"], capture=False)
        log.log("Boot chain sent; watch the device screen.")

    def _identity_guard(self):
        if not self.identity_check:
            return
        q = run([self.ctx.tool("irecovery"), "-q"], check=False, timeout=10).stdout or b""
        q = q.decode(errors="replace")
        dev = self.ctx.t["device"]
        model = dev["model"]
        ecid = dev["ecid"]
        if f"MODEL: {model}" not in q and model not in q.lower():
            log.die(f"Connected device is not {model} (irecovery -q mismatch). Use --no-identity-check to skip.")
        # Compare ECID case-insensitively; irecovery formatting may omit leading zeros
        short = ecid.lower().replace("0x", "").lstrip("0")
        if short and short not in q.lower().replace("0x", ""):
            log.warn(f"ECID does not match profile {ecid}; check that the target is {model}.")

    def _ensure_iboot(self):
        """Decrypt missing inputs in DFU, before entering the ramdisk."""
        if self.ctx.dry_run:
            return
        self.rd.dfu_ensure()
        self.ctx.derived("ibss_src")
        self.ctx.derived("ibec_dec")

    def all(self):
        """Prepare iBSS/iBEC, boot ramdisk, extract ticket, install, build, and boot."""
        self._ensure_iboot()
        for name, run_stage in (("ramdisk", self.ramdisk), ("extract-im4m", self.extract_im4m),
                                ("volumes", self.volumes), ("rootfs", self.rootfs),
                                ("patch-rootfs", self.patch_rootfs), ("build", self.build),
                                ("boot", self.boot)):
            log.stage(name)
            run_stage()


def build_parser():
    p = argparse.ArgumentParser(
        prog="n56patcher.py",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=__doc__)
    p.add_argument("stage", choices=[
        "ramdisk", "extract-im4m", "volumes", "rootfs", "patch-rootfs",
        "build", "boot", "install", "all", "list", "status"])
    p.add_argument("--target", default="n61-ios13", help="Target profile name (targets/<name>.py)")
    p.add_argument("--features", default=None,
                   help="Comma-separated feature list overriding the target defaults")
    p.add_argument("--patches", default=None,
                   help="Comma-separated KC transform IDs; an empty string selects only the base KC")
    p.add_argument("--exclude", default=None,
                   help="Comma-separated patch IDs to exclude")
    p.add_argument("--bootargs", default=None, help="Override boot arguments")
    p.add_argument("--data-protection", choices=["none", "encrypted"], default=None,
                   help="Second-system Data protection mode (default: encrypted)")
    p.add_argument("--native-ipsw", default=None, help="native iOS 12.5.8 IPSW for this target")
    p.add_argument("--ui-ipsw", default=None, help="optional target UI resource IPSW (N61: iPhone 6s 13.7)")
    p.add_argument("--n66-ipsw", default=None, help="iPhone 6s Plus 13.7 IPSW")
    p.add_argument("--j96-ipsw", default=None, help="iPad mini 4 13.7 IPSW")
    p.add_argument("--workdir", default=None, help="Working directory for generated outputs")
    p.add_argument("--allow-manual", action="store_true", help="Enable patches that require manual steps")
    p.add_argument("--dry-run", action="store_true", help="Show the plan without device writes or generated outputs")
    p.add_argument("--no-identity-check", action="store_true", help="Skip device identity checks when booting")
    return p


def make_flow(args):
    ctx = Context(args.target, workdir=args.workdir, dry_run=args.dry_run)
    if args.bootargs:
        ctx.t["bootargs"] = args.bootargs
    if args.data_protection:
        ctx.t["data_protection"] = args.data_protection
    if args.native_ipsw:
        ctx.set_ipsw_input(ctx.t.get("native_profile", "n56"), args.native_ipsw)
    if args.ui_ipsw:
        ctx.set_ipsw_input(ctx.t.get("ui_resource_profile", "n66"), args.ui_ipsw)
    if args.n66_ipsw:
        ctx.set_ipsw_input("n66", args.n66_ipsw)
    if args.j96_ipsw:
        ctx.set_ipsw_input("j96", args.j96_ipsw)
    if args.features is not None:
        ctx.t["features"] = [x.strip() for x in args.features.split(",") if x.strip()]
    if args.patches is not None:
        ctx.t["kc_patches"] = [x.strip() for x in args.patches.split(",") if x.strip()]
    if args.exclude is not None:
        ctx.t["exclude"] = list(dict.fromkeys(ctx.t.get("exclude", []) +
                                    [x.strip() for x in args.exclude.split(",") if x.strip()]))
    selection = patchmod.select(ctx.t)
    return ctx, selection, Flow(ctx, selection,
                                allow_manual=args.allow_manual,
                                identity_check=not args.no_identity_check)


def main(argv=None):
    args = build_parser().parse_args(argv)
    ctx, selection, flow = make_flow(args)

    if args.stage == "list":
        log.log(f"Target {ctx.t['name']}  features={ctx.t.get('features')}")
        print(patchmod.summary(selection))
        return 0

    dispatch = {
        "ramdisk": flow.ramdisk,
        "extract-im4m": flow.extract_im4m,
        "volumes": flow.volumes,
        "rootfs": flow.rootfs,
        "patch-rootfs": flow.patch_rootfs,
        "build": flow.build,
        "boot": flow.boot,
        "install": flow.install,
        "all": flow.all,
        "status": flow.status,
    }
    dispatch[args.stage]()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except log.Die as e:
        sys.exit(e.code if isinstance(e.code, int) else 1)
    except KeyboardInterrupt:
        sys.exit(130)
