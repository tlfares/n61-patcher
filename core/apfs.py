"""APFS volume creation and raw superblock role updates through the SSH ramdisk.

newfs_apfs assigns System and Data to filesystem slots 0 and 1, already occupied
by iOS 12. Create SystemB/DataB with role 0, then update apfs_role at 0x3c4 and
recompute Fletcher-64. Roles 0x1/0x40 must remain unique in the container.
Raw I/O uses 4 KiB blocks on /dev/rdisk0s1. Back up each block before writing
and compare the readback with the expected bytes."""
import os
import re
import struct
import subprocess
import time

from . import log

BS = 4096
RDEV = "/dev/rdisk0s1"
ROLE_OFF = 0x3C4
NAME_OFF = 0x2C0
FS_FLAGS_OFF = 0x108            # apfs_fs_flags (u64)；bit0=APFS_FS_UNENCRYPTED
APFS_FS_UNENCRYPTED = 0x1
ALLOC_COUNT_OFF = 0x58          # apfs_fs_alloc_count (u64)：allocated volume blocks (read without mounting)


def human(n):
    f = float(n)
    for u in ("B", "KiB", "MiB", "GiB", "TiB"):
        if f < 1024 or u == "TiB":
            return f"{f:.0f}{u}" if u == "B" else f"{f:.2f}{u}"
        f /= 1024
ROLES = {0: "None", 0x1: "System", 0x2: "User", 0x4: "Recovery", 0x8: "VM",
         0x10: "Preboot", 0x20: "Installer", 0x40: "Data", 0x80: "Baseband",
         0xC0: "Update", 0x100: "xART", 0x140: "Hardware"}


class Apfs:
    def __init__(self, ctx):
        self.ctx = ctx
        self.backup_dir = ctx.wk("apfs-role-backup")

    @property
    def ssh(self):
        return self.ctx.ssh

    # ---- Raw block I/O ----
    def read_block(self, n):
        b = self.ssh.sh(f"dd if={RDEV} bs={BS} skip={n} count=1 2>/dev/null")
        if len(b) != BS:
            log.die(f"Unexpected read length for block {n}: {len(b)}")
        return b

    def write_block(self, n, data):
        assert len(data) == BS
        self.ssh.sh(f"dd of={RDEV} bs={BS} seek={n} count=1 conv=notrunc 2>/dev/null && sync",
                    data=data)

    # ---- Fletcher-64 checksum ----
    @staticmethod
    def fletcher64(block):
        s1 = s2 = 0
        for (w,) in struct.iter_unpack("<I", block[8:]):
            s1 = (s1 + w) % 0xFFFFFFFF
            s2 = (s2 + s1) % 0xFFFFFFFF
        lo = 0xFFFFFFFF - ((s1 + s2) % 0xFFFFFFFF)
        hi = 0xFFFFFFFF - ((s1 + lo) % 0xFFFFFFFF)
        return (hi << 32) | lo

    def checksum_ok(self, block):
        return struct.unpack_from("<Q", block, 0)[0] == self.fletcher64(block)

    def with_checksum(self, block):
        b = bytearray(block)
        struct.pack_into("<Q", b, 0, self.fletcher64(b))
        return bytes(b)

    # ---- Volume enumeration ----
    def _latest_nxsb(self):
        nx = self.read_block(0)
        if nx[32:36] != b"NXSB":
            log.die("Block 0 is not an APFS container superblock")
        xp_blocks = struct.unpack_from("<I", nx, 0x68)[0] & 0x7FFFFFFF
        xp_base = struct.unpack_from("<Q", nx, 0x70)[0]
        best = nx
        for i in range(xp_blocks):
            b = self.read_block(xp_base + i)
            if (b[32:36] == b"NXSB" and self.checksum_ok(b)
                    and struct.unpack_from("<Q", b, 16)[0] > struct.unpack_from("<Q", best, 16)[0]):
                best = b
        return best

    def volumes(self):
        """Return [(sN, paddr, superblock)] in filesystem slot order."""
        nx = self._latest_nxsb()
        omap_oid = struct.unpack_from("<Q", nx, 0xA0)[0]
        max_fs = struct.unpack_from("<I", nx, 0xB4)[0]
        fs_oids = [o for o in struct.unpack_from(f"<{max_fs}Q", nx, 0xB8) if o]
        om = self.read_block(omap_oid)
        tree = self.read_block(struct.unpack_from("<Q", om, 0x30)[0])
        flags, level, nkeys = struct.unpack_from("<HHI", tree, 32)
        if level != 0:
            log.die("The omap tree has multiple leaves; this parser needs extending")
        toff, tlen = struct.unpack_from("<HH", tree, 40)
        keystart = 56 + toff + tlen
        valend = BS - (40 if flags & 1 else 0)
        m = {}
        for i in range(nkeys):
            ko, vo = struct.unpack_from("<HH", tree, 56 + toff + i * 4)
            oid, xid = struct.unpack_from("<QQ", tree, keystart + ko)
            _, _, paddr = struct.unpack_from("<IIQ", tree, valend - vo)
            if oid not in m or xid > m[oid][0]:
                m[oid] = (xid, paddr)
        out = []
        for idx, oid in enumerate(fs_oids, 1):
            paddr = m[oid][1]
            sb = self.read_block(paddr)
            if sb[32:36] != b"APSB":
                log.die(f"s{idx}: block {paddr} is not a volume superblock")
            out.append((idx, paddr, sb))
        return out

    def describe(self, idx, paddr, sb):
        role = struct.unpack_from("<H", sb, ROLE_OFF)[0]
        name = sb[NAME_OFF:NAME_OFF + 256].split(b"\0")[0].decode(errors="replace")
        ck = "ok" if self.checksum_ok(sb) else "BAD"
        return (f"s{idx}  slot={idx - 1}  {name:16s} "
                f"role=0x{role:x} ({ROLES.get(role, '?')})  {self.enc_state(sb):11s}  "
                f"used {human(self.used_bytes(sb)):>10s}  block={paddr}  cksum={ck}")

    # ---- Encryption state (independent of role)----
    def fs_flags(self, sb):
        return struct.unpack_from("<Q", sb, FS_FLAGS_OFF)[0]

    def enc_state(self, sb):
        return "UNENCRYPTED" if self.fs_flags(sb) & APFS_FS_UNENCRYPTED else "encrypted"

    # ---- Allocated space (apfs_fs_alloc_count × block size; readable without mounting)----
    def alloc_count(self, sb):
        return struct.unpack_from("<Q", sb, ALLOC_COUNT_OFF)[0]

    def used_bytes(self, sb):
        return self.alloc_count(sb) * BS

    def list(self):
        nx = self._latest_nxsb()
        blk = struct.unpack_from("<I", nx, 0x24)[0] or BS       # nx_block_size
        total = struct.unpack_from("<Q", nx, 0x28)[0] * blk     # nx_block_count × block_size
        vols = self.volumes()
        used_sum = sum(self.used_bytes(sb) for _, _, sb in vols)
        log.log(f"Container disk0s1: capacity {human(total)}, total volume usage {human(used_sum)}"
                f" (APFS space is shared; individual volumes have no fixed limit)")
        for v in vols:
            log.log(self.describe(*v))
        return vols

    def validate_layout(self, require_second_system=False):
        """Reject unexpected slice layouts before any installation writes.

        This workflow supports native slices s1/s2/s3 followed only by the
        named SystemB/DataB pair. A matching slice number alone is not enough
        to authorize clearing a volume that may belong to another setup.
        """
        mounts = self.ctx.t["mounts"]
        if (mounts.get("system12"), mounts.get("system_b"), mounts.get("data_b")) != (1, 4, 5):
            log.die("This installer supports only SystemA=s1, SystemB=s4 and DataB=s5")
        volumes = self.volumes()
        indices = [index for index, _, _ in volumes]
        if indices not in ([1, 2, 3], [1, 2, 3, 4], [1, 2, 3, 4, 5]):
            log.die(f"Unsupported APFS volume layout: {indices}; expected native s1/s2/s3 and optional SystemB/DataB")
        device_indices = sorted(int(match.group(1)) for path in self.ssh.slices()
                                if (match := re.fullmatch(r"/dev/disk0s1s([0-9]+)", path)))
        if device_indices != indices:
            log.die(f"APFS metadata and device slices disagree: {indices} versus {device_indices}")
        for index, _, superblock in volumes:
            if not self.checksum_ok(superblock):
                log.die(f"s{index} has an invalid superblock checksum; refusing installation writes")
        by_index = {index: superblock for index, _, superblock in volumes}
        expected_names = {3: "Baseband Data", 4: "SystemB", 5: "DataB"}
        allowed_roles = {3: (0, 0x80), 4: (0, 0x1), 5: (0, 0x40)}
        for index, expected in expected_names.items():
            if index not in by_index:
                continue
            superblock = by_index[index]
            name = superblock[NAME_OFF:NAME_OFF + 256].split(b"\0", 1)[0].decode(errors="replace")
            role = struct.unpack_from("<H", superblock, ROLE_OFF)[0]
            if name != expected or role not in allowed_roles[index]:
                log.die(f"s{index} is {name!r} with role 0x{role:x}; expected {expected!r}. "
                        "Refusing to reuse an unrelated or unsupported volume")
        if require_second_system and 5 not in by_index:
            log.die("SystemB/DataB are not both present; run the volumes stage before writing the rootfs")
        self.ctx.verify_device_system(self.ssh)
        log.log("Validated native APFS layout and SystemB/DataB destinations")
        return volumes

    # ---- Volume creation ----
    def create_volumes(self, names=("SystemB", "DataB"), encrypt_data=False):
        """Create missing s4/s5 volumes with role 0. Use -P for Data content protection when encrypt_data is set.

        Encryption and role are independent fields: -P sets encryption at creation; apfs_setrole changes role afterward.
        These settings do not conflict.
        The iOS 12 ramdisk newfs_apfs routes both -P and -E to its encrypted option.
        Return whether a volume was created.
        """
        self.validate_layout()
        s = self.ssh.slices()
        if any("disk0s1s5" in x for x in s):
            log.log(f"s4/s5 already exist; skipping: {' '.join(s)}")
            return False
        if any("disk0s1s4" in x for x in s):
            # If creation stopped after SystemB, only DataB remains to be created
            log.warn(f"s4 exists; creating only {names[-1]}: {' '.join(s)}")
            names = names[1:]
        if encrypt_data:
            # Creating a -P volume before loading SEP can hang and lock the container
            self.ssh.mount(self.ctx.t["mounts"]["system12"], "/mnt1", ro=True)
            self.ssh.ensure_sep()
        cmds = []
        for n in names:
            flag = " -P" if (encrypt_data and "Data" in n) else ""
            cmds.append(f"/sbin/newfs_apfs -A{flag} -v {n} /dev/disk0s1")
            log.log(f"Creating volume {n} (role 0{', encrypted' if flag else ''})…")
        try:
            self.ssh.sh(" && ".join(cmds))
        except subprocess.TimeoutExpired:
            log.die("Volume creation timed out; the container may be locked. Reboot into DFU and try again.")
        if encrypt_data:
            self.ssh.umount("/mnt1")
        self.validate_layout(require_second_system=True)
        log.log(f"Current volumes: {' '.join(self.ssh.slices())}")
        if encrypt_data:
            self.report_data_encryption(names)
        return True

    def report_data_encryption(self, names):
        """Check actual Data volume encryption after creation."""
        data_name = next((n for n in names if "Data" in n), None)
        for idx, paddr, sb in self.volumes():
            nm = sb[NAME_OFF:NAME_OFF + 256].split(b"\0")[0].decode(errors="replace")
            if nm == data_name:
                st = self.enc_state(sb)
                log.log(f"  {nm} actual encryption state: {st} (apfs_fs_flags=0x{self.fs_flags(sb):x})")
                if st == "UNENCRYPTED":
                    log.warn(f"  {nm} remains UNENCRYPTED: this ramdisk newfs_apfs did not set the encryption flag; "
                             "check that the formatter supports -P.")
                return

    # ---- Update roles ----
    def set_roles(self, targets, write=False):
        """targets maps volume numbers to roles; write=False is a dry run. Unmount target volumes first."""
        vols = self.volumes()
        for v in vols:
            log.log(self.describe(*v))

        if write:
            mnt = self.ssh.sh("/sbin/mount").decode(errors="replace")
            for idx in targets:
                if f"/dev/disk0s1s{idx} " in mnt:
                    log.die(f"s{idx} is mounted; unmount it first")

        used = {struct.unpack_from("<H", sb, ROLE_OFF)[0]: idx
                for idx, _, sb in vols if idx not in targets}
        os.makedirs(self.backup_dir, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        for idx, role in sorted(targets.items()):
            vol = next((v for v in vols if v[0] == idx), None)
            if vol is None:
                log.die(f"s{idx} does not exist")
            _, paddr, sb = vol
            if not self.checksum_ok(sb):
                log.die(f"s{idx}: existing checksum is invalid; refusing to write")
            if role and role in used:
                log.die(f"role 0x{role:x} is already assigned to s{used[role]}")
            new = bytearray(sb)
            struct.pack_into("<H", new, ROLE_OFF, role)
            new = self.with_checksum(new)
            old_role = struct.unpack_from("<H", sb, ROLE_OFF)[0]
            log.log(f"s{idx}: role 0x{old_role:x} -> 0x{role:x}")
            if not write:
                continue
            bak = os.path.join(self.backup_dir, f"block-{paddr}-s{idx}-{stamp}.bin")
            with open(bak, "wb") as f:
                f.write(sb)
            self.write_block(paddr, new)
            if self.read_block(paddr) != new:
                log.die(f"s{idx}: Readback mismatch! Restore the backup: {bak}")
            log.log(f"  Written and verified (backup: {bak})")
        if write:
            for v in self.volumes():
                log.log(self.describe(*v))
