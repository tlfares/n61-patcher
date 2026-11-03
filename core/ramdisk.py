"""iOS 12.5.8 SSH ramdisk boot, USB proxy, remote commands, and file deployment.

Use iproxy 2222 to device port 22; the ramdisk password is alpine. Mount SystemA
read-only on /mnt1, SystemB on /mnt6, and DataB on /mnt7. Never mount encrypted
iOS 12 Data (s2): even a read-only mount can hang and lock the APFS container.
The ramdisk root is read-only and lacks /tmp, ps, df, shasum, and dirname.
Use /usr/sbin/chown explicitly. Never pipe remote tar into head: SIGPIPE can
truncate the deployment. Extract with tar --numeric-owner to preserve ownership."""
import os
import subprocess
import time

from . import log
from .tools import run

SEP_FIRMWARE = "/mnt1/usr/standalone/firmware/sep-firmware.img4"

RAMDISK_SEND = ["iBSS", "iBEC", "ramdisk", "devicetree", "trustcache", "kernelcache"]


class Ramdisk:
    def __init__(self, ctx):
        self.ctx = ctx
        self.port = ctx.t.get("ramdisk_port", 2222)
        self.password = ctx.t.get("ramdisk_password", "alpine")
        self._proxy = None
        self._ssh_base = [
            ctx.tool("sshpass"), "-p", self.password, "ssh",
            "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null",
            "-o", "LogLevel=ERROR", "-o", "ConnectTimeout=10",
            "-p", str(self.port), "root@localhost",
        ]

    # ---- Device state ----
    def dfu_wait(self):
        irecovery = self.ctx.tool("irecovery")
        log.log("Waiting for DFU (use the Home and Power buttons)…")
        while True:
            r = run([irecovery, "-q"], check=False, timeout=10)
            if b"MODE: DFU" in (r.stdout or b""):
                return
            time.sleep(1)

    def pwn(self):
        irecovery = self.ctx.tool("irecovery")
        gaster = self.ctx.tool("gaster")
        q = run([irecovery, "-q"], check=False, timeout=10).stdout or b""
        if b"PWND" not in q:
            log.log("gaster pwn…")
            run([gaster, "pwn"], capture=False)
        log.log("gaster reset…")
        run([gaster, "reset"], capture=False, check=False)
        time.sleep(1)

    # ---- Boot the ramdisk ----
    def boot(self):
        """Send the SSHRD boot chain, then start iproxy."""
        rd = self.ctx.t["ramdisk_dir"]
        rd_dir = self.ctx.local(rd)
        irecovery = self.ctx.tool("irecovery")

        def img(name):
            return os.path.join(rd_dir, f"{name}.img4")

        self.dfu_ensure()
        self.pwn()
        log.step(1, 6, "Send iBSS")
        run([irecovery, "-f", img("iBSS")], capture=False); time.sleep(2)
        log.step(2, 6, "Send iBEC")
        run([irecovery, "-f", img("iBEC")], capture=False); time.sleep(3)
        logo = img("logo")
        if os.path.exists(logo):
            run([irecovery, "-f", logo], capture=False, check=False)
            run([irecovery, "-c", "setpicture 0x1"], capture=False, check=False)
        log.step(3, 6, "Send ramdisk")
        run([irecovery, "-f", img("ramdisk")], capture=False)
        run([irecovery, "-c", "ramdisk"], capture=False); time.sleep(1)
        log.step(4, 6, "Send DeviceTree")
        run([irecovery, "-f", img("devicetree")], capture=False)
        run([irecovery, "-c", "devicetree"], capture=False); time.sleep(1)
        log.step(5, 6, "Send TrustCache")
        run([irecovery, "-f", img("trustcache")], capture=False)
        run([irecovery, "-c", "firmware"], capture=False); time.sleep(1)
        log.step(6, 6, "Send KernelCache + bootx")
        run([irecovery, "-f", img("kernelcache")], capture=False)
        run([irecovery, "-c", "bootx"], capture=False)
        log.log("Ramdisk chain sent; waiting for SSH…")
        self.wait_ssh(boot=True)

    def dfu_ensure(self):
        irecovery = self.ctx.tool("irecovery")
        r = run([irecovery, "-q"], check=False, timeout=10).stdout or b""
        if b"MODE: DFU" not in r:
            self.dfu_wait()

    # ---- iproxy / SSH ----
    def start_proxy(self):
        if self._proxy and self._proxy.poll() is None:
            return
        # Reuse an existing iproxy, or start one
        if subprocess.run(["pgrep", "-x", "iproxy"], capture_output=True).returncode == 0:
            return
        self._proxy = subprocess.Popen(
            [self.ctx.tool("iproxy"), str(self.port), "22"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(2)

    def wait_ssh(self, boot=False, tries=120):
        self.start_proxy()
        for _ in range(tries):
            if self._alive():
                self.ctx._ssh = self
                log.log("Ramdisk SSH is ready.")
                return
            time.sleep(1)
        log.die("Ramdisk SSH is unavailable" + (" (the ramdisk may not have booted)" if boot else "; run the ramdisk stage first"))

    def _alive(self):
        return subprocess.run(self._ssh_base + ["true"], capture_output=True).returncode == 0

    def ensure(self):
        """Ensure SSH is available; rootfs streaming may have stopped iproxy."""
        self.start_proxy()
        if not self._alive():
            self.wait_ssh()
        self.ctx._ssh = self

    # ---- Remote commands ----
    def sh(self, cmd, data=None, check=True, timeout=120):
        r = subprocess.run(self._ssh_base + [cmd], input=data,
                           capture_output=True, timeout=timeout)
        if check and r.returncode != 0:
            log.die(f"Remote command failed({r.returncode}): {cmd}\n"
                    f"{(r.stderr or b'').decode(errors='replace')}")
        return r.stdout or b""

    def ssh_argv(self):
        return list(self._ssh_base)

    # ---- Mount volumes ----
    def slices(self):
        return self.sh("ls /dev/disk0s1s*").decode(errors="replace").split()

    def mount(self, slice_no, mnt, ro=False):
        opt = "-o ro " if ro else ""
        self.sh(f'/sbin/mount | grep -q "disk0s1s{slice_no} on {mnt}" || '
                f'/sbin/mount_apfs {opt}/dev/disk0s1s{slice_no} {mnt}')

    def umount(self, *mnts):
        for m in mnts:
            self.sh(f"/sbin/umount {m}", check=False)

    def sync(self):
        self.sh("sync")

    # ---- SEP ----
    def ensure_sep(self):
        """Load SEP for encrypted volume creation and systembags; /mnt1 must be mounted read-only."""
        ping = "/usr/libexec/seputil --ping 2>&1"
        if b"ping failed" not in self.sh(ping, check=False):
            return
        log.log("Loading native SEP firmware…")
        self.sh(f'/usr/libexec/seputil --load "{SEP_FIRMWARE}"', check=False)
        if b"ping failed" in self.sh(ping, check=False):
            log.warn("SEP is still unresponsive after loading; encryption operations may hang.")

    # ---- Tar deployment ----
    def deploy_tar_bytes(self, tar_bytes, dest_mnt):
        """Extract tar bytes into device dest_mnt, preserving ownership."""
        self.sh(f"/usr/bin/tar --numeric-owner -xpf - -C {dest_mnt}", data=tar_bytes)

    def read_tar(self, remote_path_expr):
        """Create and retrieve a device archive, for example a backup. remote_path_expr may be '-C /mnt7 keybags'."""
        return self.sh(f"/usr/bin/tar -cf - {remote_path_expr}")

    def deploy_path(self, source, dest, uid=None, gid=None):
        """Stream a local file or directory without an intermediate tar file."""
        source = os.path.abspath(source)
        if os.path.isdir(source):
            self.sh(f'mkdir -p "{dest}"')
            command = ["/usr/bin/tar", "--no-xattrs"]
            if uid is not None:
                command += ["--uid", str(uid)]
            if gid is not None:
                command += ["--gid", str(gid)]
            command += ["-cpf", "-", "-C", source, "."]
            producer = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                        env=dict(os.environ, COPYFILE_DISABLE="1"))
            consumer = subprocess.Popen(
                self._ssh_base + [f'/usr/bin/tar --numeric-owner -xpf - -C "{dest}"'],
                stdin=producer.stdout, stderr=subprocess.PIPE)
            producer.stdout.close()
            _, consumer_err = consumer.communicate()
            _, producer_err = producer.communicate()
            if producer.returncode or consumer.returncode:
                log.die(f"Directory streaming failed: {source} → {dest}\n"
                        f"{(producer_err or consumer_err or b'').decode(errors='replace')}")
            return
        self._deploy_file(source, dest)

    def deploy_relative_paths(self, root, paths, dest):
        """Stream selected paths relative to root, preserving directory structure."""
        root = os.path.abspath(root)
        paths = list(paths)
        if not paths:
            return
        self.sh(f'mkdir -p "{dest}"')
        producer = subprocess.Popen(
            ["/usr/bin/tar", "--no-xattrs", "-cpf", "-", "-C", root, *paths],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=dict(os.environ, COPYFILE_DISABLE="1"))
        consumer = subprocess.Popen(
            self._ssh_base + [f'/usr/bin/tar --numeric-owner -xpf - -C "{dest}"'],
            stdin=producer.stdout, stderr=subprocess.PIPE)
        producer.stdout.close()
        _, consumer_err = consumer.communicate()
        _, producer_err = producer.communicate()
        if producer.returncode or consumer.returncode:
            log.die("File set streaming failed\n" +
                    (producer_err or consumer_err or b"").decode(errors="replace"))

    def pull_file(self, source, dest):
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "wb") as stream:
            proc = subprocess.run(self._ssh_base + [f'cat "{source}"'], stdout=stream,
                                  stderr=subprocess.PIPE)
        if proc.returncode:
            log.die(f"Cannot read device file: {source}\n"
                    f"{(proc.stderr or b'').decode(errors='replace')}")
        return dest

    def _deploy_file(self, source, dest):
        command = f'mkdir -p "{os.path.dirname(dest)}"; cat > "{dest}"'
        with open(source, "rb") as stream:
            proc = subprocess.Popen(self._ssh_base + [command], stdin=stream, stderr=subprocess.PIPE)
            _, err = proc.communicate()
        if proc.returncode:
            log.die(f"File streaming failed: {source} → {dest}\n"
                    f"{(err or b'').decode(errors='replace')}")

    def read_range(self, path, offset, size):
        return self.sh(f'dd if="{path}" bs=1 skip={offset} count={size} 2>/dev/null')

    def write_range(self, path, offset, data):
        self.sh(f'dd of="{path}" bs=1 seek={offset} conv=notrunc 2>/dev/null',
                data=data, timeout=120)
