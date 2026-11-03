"""Offline checks that unexpected APFS destinations cannot reach writes."""
import contextlib
import io
from pathlib import Path
import struct
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import log
from core.apfs import Apfs, BS, NAME_OFF, ROLE_OFF
from n56patcher import Flow


class InstallLayoutTests(unittest.TestCase):
    def setup_apfs(self, names=("System", "Data", "Baseband Data"), roles=None):
        ssh = Mock()
        ssh.slices.return_value = [f"/dev/disk0s1s{i}" for i in range(1, len(names) + 1)]
        context = SimpleNamespace(t={"mounts": {"system12": 1, "system_b": 4, "data_b": 5}},
                                  ssh=ssh, wk=lambda name: name, verify_device_system=Mock())
        apfs = Apfs(context)
        volumes = []
        for index, name in enumerate(names, 1):
            superblock = bytearray(BS)
            superblock[32:36] = b"APSB"
            superblock[NAME_OFF:NAME_OFF + len(name)] = name.encode()
            struct.pack_into("<H", superblock, ROLE_OFF, (roles or {}).get(index, 0))
            volumes.append((index, index * 10, apfs.with_checksum(superblock)))
        apfs.volumes = Mock(return_value=volumes)
        return apfs

    def reject(self, apfs, **kwargs):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(log.Die):
            apfs.validate_layout(**kwargs)
        apfs.ssh.sh.assert_not_called()

    def test_accepts_native_partial_and_complete_layouts(self):
        for names in (("System", "Data", "Baseband Data"),
                      ("System", "Data", "Baseband Data", "SystemB"),
                      ("System", "Data", "Baseband Data", "SystemB", "DataB")):
            apfs = self.setup_apfs(names)
            with contextlib.redirect_stderr(io.StringIO()):
                apfs.validate_layout()
            apfs.ctx.verify_device_system.assert_called_once_with(apfs.ssh)

    def test_accepts_existing_installed_roles(self):
        apfs = self.setup_apfs(("System", "Data", "Baseband Data", "SystemB", "DataB"),
                              {3: 0x80, 4: 1, 5: 0x40})
        with contextlib.redirect_stderr(io.StringIO()):
            apfs.validate_layout(require_second_system=True)

    def test_rejects_unrelated_s4_before_any_write(self):
        self.reject(self.setup_apfs(("System", "Data", "Baseband Data", "PersonalBackup")))

    def test_rejects_extra_volume(self):
        self.reject(self.setup_apfs(("System", "Data", "Baseband Data", "SystemB", "DataB", "OtherOS")))

    def test_rejects_wrong_baseband_destination(self):
        self.reject(self.setup_apfs(("System", "Data", "OtherData")))

    def test_rejects_missing_data_volume_before_rootfs(self):
        self.reject(self.setup_apfs(("System", "Data", "Baseband Data", "SystemB")),
                    require_second_system=True)

    def test_rejects_slice_metadata_disagreement(self):
        apfs = self.setup_apfs()
        apfs.ssh.slices.return_value.append("/dev/disk0s1s6")
        self.reject(apfs)

    def test_rejects_bad_checksum(self):
        apfs = self.setup_apfs()
        index, address, superblock = apfs.volumes.return_value[0]
        changed = bytearray(superblock)
        changed[100] ^= 1
        apfs.volumes.return_value[0] = index, address, bytes(changed)
        self.reject(apfs)

    def test_rootfs_and_overlay_stop_before_running_patches(self):
        for method in (Flow.rootfs, Flow.patch_rootfs):
            flow = object.__new__(Flow)
            flow.ctx = SimpleNamespace(dry_run=False, close_source_mounts=Mock())
            flow._need_ramdisk = Mock()
            flow._run_patches = Mock()
            with patch("n56patcher.Apfs") as apfs:
                apfs.return_value.validate_layout.side_effect = log.Die(1)
                with self.assertRaises(log.Die):
                    method(flow)
            flow._run_patches.assert_not_called()


if __name__ == "__main__":
    unittest.main()
