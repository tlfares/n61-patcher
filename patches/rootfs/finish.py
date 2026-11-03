# -*- coding: utf-8 -*-
"""Finalize SystemB: DataB relocation, fsck, SEP firmware and keybags.

The iOS 13 private/var tree belongs on a separate DataB volume. Use the
legacy personalized SEP firmware from native SystemA and iOS 14 fsck/APFS
helpers for the dual-system volume layout. The unencrypted fallback takes
keybags from a previously jailbroken iOS 12 system; the ramdisk cannot mount
its encrypted Data volume. Always stream tar with numeric owners and never
pipe the remote extraction into head."""
import os
import subprocess

from core import log
from core.context import STATE_DIR
from core.patch import Patch
from patches.impl.rootfs.systembag import ensure_systembag


class RootfsFinish(Patch):
    id = "rootfs.finish"
    layer = "rootfs"
    role = "finalize"
    feature = "core"
    scope = "version"
    requires = ("rootfs.base_stream",)
    donors = ("apfs14",)
    note = "Finalize var -> DataB / fsck / SEP firmware / keybags"

    def apply(self, ctx, art=None):
        ssh = ctx.ssh
        apfs14 = ctx.donor("apfs14")
        encrypted = ctx.t.get("data_protection") == "encrypted"
        keybags = None if encrypted else os.path.join(STATE_DIR, "keybags.tar")

        ssh.mount(ctx.t["mounts"]["system_b"], "/mnt6")
        ssh.mount(ctx.t["mounts"]["system12"], "/mnt1", ro=True)
        if encrypted:
            ensure_systembag(ctx)
        else:
            ssh.mount(ctx.t["mounts"]["data_b"], "/mnt7")

        log.log("private/var → DataB…")
        ssh.sh("/bin/cp -a /mnt6/private/var/. /mnt7/")

        log.log("Creating xarts / preboot directories...")
        ssh.sh("mkdir -p /mnt6/private/xarts /mnt6/private/preboot && "
               "chmod 755 /mnt6/private/xarts /mnt6/private/preboot")

        log.log("Installing iOS 14 fsck + apfs.fs (originals renamed *Backup)...")
        ssh.sh("cd /mnt6 && { [ -e sbin/fsckBackup ] || mv sbin/fsck sbin/fsckBackup; } && "
               "{ [ -e System/Library/Filesystems/apfs.fsBackup ] || "
               "mv System/Library/Filesystems/apfs.fs System/Library/Filesystems/apfs.fsBackup; }")
        # Stream fsck + apfs.fs from apfsios14 directly to the device.
        src = subprocess.Popen(
            ["/usr/bin/tar", "--uid", "0", "--gid", "0", "--no-xattrs", "-cf", "-",
             "-C", apfs14, "./sbin/fsck", "./System/Library/Filesystems/apfs.fs"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            env=dict(os.environ, COPYFILE_DISABLE="1"))
        dst = subprocess.Popen(
            ssh.ssh_argv() + ["/usr/bin/tar --numeric-owner -xpf - -C /mnt6 && "
                              "chmod 755 /mnt6/System/Library/Filesystems/apfs.fs"],
            stdin=src.stdout, stderr=subprocess.PIPE)
        src.stdout.close()
        _, err = dst.communicate()
        src.wait()
        if dst.returncode != 0:
            log.die("Failed to replace fsck/apfs.fs\n" + (err or b"").decode(errors="replace"))

        log.log("Copying SEP firmware from iOS 12 SystemA...")
        ssh.sh("/bin/cp -a /mnt1/usr/standalone/firmware/sep-firmware.img4 "
               "/mnt6/usr/standalone/firmware/")

        if encrypted:
            log.log("Keeping the systembag created for encrypted DataB...")
            ssh.sh("test -s /mnt7/keybags/systembag.kb")
        else:
            log.log("keybags → DataB…")
            with open(keybags, "rb") as f:
                ssh.deploy_tar_bytes(f.read(), "/mnt7")

        ssh.sh("ls -ln /mnt6/sbin/fsck /mnt6/usr/standalone/firmware/sep-firmware.img4 "
               "/mnt7/keybags/systembag.kb")
        ssh.sync()
        ssh.umount("/mnt1", "/mnt7", "/mnt6")
        log.log("Finalization complete; volumes unmounted.")
