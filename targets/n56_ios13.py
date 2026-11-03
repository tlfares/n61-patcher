# -*- coding: utf-8 -*-
"""iPhone 6 Plus (N56AP) / iOS 13.7: local donors and the complete KC build chain."""

TARGET = {
    "name": "n56-ios13",
    "source_root": "donors",

    # ===================== Device constants (independent of the iOS version)=====================
    "device": {
        "model": "n56ap",
        "product": "iPhone7,1",
        "board": "n56",
        "ecid": "",
        "udid": "",
        "pmu": "d2186",
        "touch": "multi-touch,n56",
        "codec": "CS42L67",
        "charger": "SN2400",
    },
    # Second-system root is s4. kairos changes iBEC root-matching to disk0s1s4.
    "root_part": 4,
    # Create s4=SystemB / s5=DataB with role 0, then assign roles at the end.
    "volumes": {
        "create": ["SystemB", "DataB"],
        "roles": {3: 0x80, 4: 0x1, 5: 0x40},     # s4=System, s5=Data (0x1/0x40 roles must be unique in the container)
    },
    # Content protection is enabled for second-system Data by default.
    "data_protection": "encrypted",
    "mounts": {"system_b": 4, "data_b": 5, "system12": 1},   # device slices mounted at /mnt6, /mnt7, /mnt1

    "ramdisk_port": 2222,
    "ramdisk_password": "alpine",
    "ramdisk_dir": "tools/SSHRD_Script/sshramdisk",       # iOS 12.5.8 SSHRD images

    # ===================== Version-specific constants=====================
    # Boot arguments from the working chain (debug=0x2014e, permissive AMFI/CS, root=disk0s1s4)
    "bootargs": "rd=disk0s1s4 -v amfi_get_out_of_my_way=1 "
                "cs_enforcement_disable=1 wdt=-1 debug=0x2014e",
    "source_profiles": {
        "n56": {"build": "16H88", "ipsw": "iPhone_5.5_12.5.8_16H88_Restore.ipsw"},
        "n66": {"build": "17H35", "rootfs_entry": "038-68134-036.dmg",
                "ipsw": "iPhone_5.5_13.7_17H35_Restore.ipsw"},
        "j96": {"build": "17H35", "rootfs_entry": "038-68261-036.dmg",
                "ipsw": "iPad_64bit_TouchID_13.7_17H35_Restore.ipsw"},
    },

    # ===================== Toolchain (repository tools/)=====================
    "tools": {
        "img4": "tools/img4lib/img4",
        "devicetree-repack": "tools/devicetree-parse/devicetree-repack",
        "iBoot64Patcher": "tools/SSHRD_Script/Darwin/iBoot64Patcher",
        "KPlooshFinder": "tools/SSHRD_Script/Darwin/KPlooshFinder",
        "gaster": ["tools/SSHRD_Script/Darwin/gaster", "tools/bin/gaster"],
        "irecovery": "tools/SSHRD_Script/Darwin/irecovery",
        "iproxy": "tools/SSHRD_Script/Darwin/iproxy",
        "sshpass": "tools/SSHRD_Script/Darwin/sshpass",
        "Kernel64Patcher": "tools/dualra1n/binaries/Darwin/Kernel64Patcher",
        "kairos": "tools/dualra1n/binaries/Darwin/kairos",
    },

    # ===================== Donor inputs (local donors/)=====================
    "donors": {
        "apfs14": "projects/dualra1n-bin/apfsios14",              # iOS 14 fsck + apfs.fs
        "sys12_mount_hint": "disk0s1s1",   # SEP firmware / N56 model-file source (mount s1 read-only)
    },

    # ===================== Generated from IPSWs (ipsw/cache/derived)=====================
    "derived": {
        "ibss_src": "extracted/n56ap_ios12/iBSS.n56.patched",  # First extraction requires DFU decryption
        "ibec_dec": "extracted/n56ap_ios12/iBEC.n56.dec",
        "j96_kernel": "extracted/j96ap_ios13/kernelcache.release.ipad5",
        "trustcache": "extracted/j96ap_ios13/038-68261-036.dmg.trustcache",
    },

    "full_trustcache": True,
    "profile_cdhashes": [
        "ea9b6b492e5f1fc2e1692a0ec93c65ab594c20c4",  # bluetoothd.xpc13
        "e001b09ea59f73cc2804d1654059138ed571029a",  # BlueTool 16H88
        "f2a9b00a2e7fb8e0fefbccdf80bfc79a2aec2202",  # nanoregistryd
        "2f4f85f4bdd0937195536da3d89927dfd01b142f",  # nanoregistrylaunchd
        "44b3dce9c846916db1419304401ceabe9b872031",  # fairplayd.H2
        "eff0e0b43afd6e72cfd81fda04325ce4282d9824",  # healthappd
    ],

    # ===================== Patch selection =====================
    # Select exactly one base for each layer (dt/kc).
    "bases": {
        "dt": "dt.base",
        "kc": "kc.j96_clean",
    },
    # Features select the default full build; --patches overrides KC alone.
    "features": [
        "pmu", "touch", "charging", "chestnut", "wifi", "vibration", "audio",
        "core",       # rootfs stream, finalization, roles and N56 model files (required to boot)
        "ui",         # icons, keyboard, Control Center, SpringBoard and Settings 3x icons
        "bluetooth",  # iOS 12 to 13 Bluetooth userland
        "baseband",   # factorydata + CommCenter + Mav10 + Carrier Bundles
        "sep",        # SEP firmware (required to boot) + fairplayd.H2
        "health",     # Health app frameworks repair-v7
        "checkra1n",  # offline KPF, userland tools and USB SSH
    ],
    # Explicit additional patch IDs (independent of features)
    "patches": [],
    # Exclusions
    "exclude": [],

    # ===================== Boot-chain transmission order =====================
    # gaster pwn/reset → iBSS → iBEC → DT(devicetree) → TC(firmware) → KC → bootx
    "boot_chain": ["iBSS", "iBEC", "DeviceTree", "TrustCache", "KernelCache"],
}
