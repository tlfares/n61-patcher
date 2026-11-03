# -*- coding: utf-8 -*-
"""Stream the J96 iOS 13.7 base rootfs to SystemB on slice 4.

Run this stage as root and mount the source with owners enabled so tar
preserves system ownership. Stream the roughly 9 GB tree directly from the
Mac; neither loading the archive into RAM nor copying a DMG to the device
fits the intended workflow. Clear the target contents before extraction;
never resume an old tree. Never pipe remote tar into head, which can cause
SIGPIPE and leave an incomplete rootfs. Use numeric owners on the device."""
import os
import subprocess

from core import log
from core.patch import Patch


class RootfsBaseStream(Patch):
    id = "rootfs.base_stream"
    layer = "rootfs"
    role = "stream"
    feature = "core"
    scope = "version"
    note = "Stream the J96 13.7 rootfs to s4 (roughly 25 minutes)"

    def apply(self, ctx, art=None):
        if os.geteuid() != 0:
            log.die("Rootfs streaming requires root; run this stage using sudo")

        ssh = ctx.ssh
        mnt = ctx.mount_rootfs("j96")

        # 2) Mount s4 at /mnt6.
        ssh.mount(ctx.t["mounts"]["system_b"], "/mnt6")

        # 3) Verify the mounted slice, then clear target contents.
        log.log("Clearing target volume /mnt6...")
        ssh.sh('test "$(/sbin/mount | /usr/bin/grep -c "/dev/disk0s1s4 on /mnt6")" -eq 1 '
               '&& /bin/rm -rf /mnt6/.[!.]* /mnt6/*')

        # 4) Stream roughly 9 GB through a direct tar pipeline.
        log.log("Streaming the rootfs (roughly 25 minutes)...")
        src_tar = subprocess.Popen(
            ["/usr/bin/tar", "-cpf", "-", "-C", mnt, "."],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        dst = subprocess.Popen(
            ssh.ssh_argv() + ["/usr/bin/tar --numeric-owner -xpf - -C /mnt6"],
            stdin=src_tar.stdout, stderr=subprocess.PIPE)
        src_tar.stdout.close()
        _, err = dst.communicate()
        src_tar.wait()
        if dst.returncode != 0 or src_tar.returncode != 0:
            log.die(f"Rootfs streaming failed (src={src_tar.returncode} dst={dst.returncode})\n"
                    f"{(err or b'').decode(errors='replace')[:2000]}")

        # 5) Reconnect iproxy after streaming and verify key files.
        ssh.ensure()
        out = ssh.sh("ls -ln /mnt6/sbin/launchd "
                     "/mnt6/System/Library/Caches/com.apple.dyld/dyld_shared_cache_arm64")
        log.log(out.decode(errors="replace").strip())
