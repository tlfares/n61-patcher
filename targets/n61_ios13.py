# -*- coding: utf-8 -*-
"""iPhone 6 (N61AP) × iOS 13.7 experimental second-system profile."""

TARGET = {
    "name": "n61-ios13",
    "source_root": "donors",

    # Device constants shared across OS versions.
    "device": {
        "model": "n61ap",
        "product": "iPhone7,2",
        "board": "n61",
        "ecid": "",
        "udid": "",
        "pmu": "d2186",
        "touch": "multi-touch,n61",
        "codec": "CS42L67",
        "charger": "SN2400",
    },
    # SystemB is slice 4; kairos changes iBEC root matching to disk0s1s4.
    "root_part": 4,
    # Create SystemB on s4 and DataB on s5 with role 0, then assign roles.
    "volumes": {
        "create": ["SystemB", "DataB"],
        "roles": {3: 0x80, 4: 0x1, 5: 0x40},     # s4=System, s5=Data; each role is unique in the container.
    },
    # Enable content protection for the second system by default.
    "data_protection": "encrypted",
    "mounts": {"system_b": 4, "data_b": 5, "system12": 1},   # device slices mounted at /mnt6, /mnt7, /mnt1

    "ramdisk_port": 2222,
    "ramdisk_password": "alpine",
    "ramdisk_dir": "tools/SSHRD_Script/sshramdisk",       # locally generated iOS 12.5.8 SSHRD images

    # Version-specific inputs.
    # Boot arguments used by the working SystemB boot chain.
    "bootargs": "rd=disk0s1s4 -v amfi_get_out_of_my_way=1 "
                "cs_enforcement_disable=1 wdt=-1 debug=0x2014e",
    "native_profile": "n61",
    "ui_resource_profile": "n71",
    # Applying the appearance-aware HEIC catalogue stalled this N61 port.
    # Keep it out of future installs until its rendering path is repaired.
    "install_wallpapers": False,
    "wallpaper_format": "jpeg-adaptive",
    "source_profiles": {
        "n61": {"build": "16H88", "rootfs_entry": "038-87263-058.dmg",
                "ipsw": "iPhone_4.7_12.5.8_16H88_Restore.ipsw"},
        "n66": {"build": "17H35", "rootfs_entry": "038-68134-036.dmg",
                "ipsw": "iPhone_5.5_13.7_17H35_Restore.ipsw"},
        "n71": {"build": "17H35", "rootfs_entry": "038-69187-036.dmg",
                "ipsw": "iPhone_4.7_13.7_17H35_Restore.ipsw"},
        "j96": {"build": "17H35", "rootfs_entry": "038-68261-036.dmg",
                "ipsw": "iPad_64bit_TouchID_13.7_17H35_Restore.ipsw"},
    },

    # Tools built or downloaded by tools/setup.py.
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

    # Local donor sources; generated/downloaded files are not committed.
    "donors": {
        "apfs14": "projects/dualra1n-bin/apfsios14",              # iOS 14 fsck + apfs.fs
        "sys12_mount_hint": "disk0s1s1",
    },

    # Build inputs derived from the user-provided IPSWs.
    "derived": {
        "native_kernel": "extracted/n61ap_ios12/kernelcache.release.iphone7.decompressed",
        "native_dt": "extracted/n61ap_ios12/DeviceTree.n61ap.jsonc",
        "ibss_src": "extracted/n61ap_ios12/iBSS.n61.patched",
        "ibec_dec": "extracted/n61ap_ios12/iBEC.n61.dec",
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
    ],

    # Default patch selection.
    # Select exactly one base for each DT/KC layer.
    "bases": {
        "dt": "dt.base",
        "kc": "kc.j96_clean",
    },
    # Features select the default full build; --patches overrides KC alone.
    "features": [
        "pmu", "touch", "charging", "chestnut", "wifi", "vibration",
        "core",       # rootfs stream, finalization, roles and native model files
        "ui",         # icons, keyboard, Control Center, SpringBoard, Settings
        "bluetooth",  # iOS 12 Bluetooth userland compatibility
        "baseband",   # factorydata + CommCenter + Mav10 + carrier bundles
        "sep",        # boot-required legacy SEP compatibility + fairplayd.H2
        # Health repair-v7 is excluded on this host: its independently
        # rebuilt dylibs did not match the repository's pinned manifest.
        "checkra1n",  # offline KPF, userland tools and USB SSH
    ],
    # Explicit patch IDs in addition to feature-based selection.
    "patches": [],
    # Explicit exclusions.
    "exclude": [],

    # Boot-chain transfer order.
    # gaster pwn/reset → iBSS → iBEC → DT(devicetree) → TC(firmware) → KC → bootx
    "boot_chain": ["iBSS", "iBEC", "DeviceTree", "TrustCache", "KernelCache"],
}
