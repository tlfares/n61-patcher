from core.overlay import SourceItem, SourceOverlay

B1_FILES = (
    "barbera.trx",
    "barbera.clmb",
    "barbera.txcb",
    "P-barbera_M-CORO_V-m__m-3.7.txt",
    "P-barbera_M-CORO_V-m__m-5.1.txt",
    "P-barbera_M-CORO_V-t__m-3.7.txt",
    "P-barbera_M-CORO_V-u__m-3.7.txt",
)


class B1Firmware(SourceOverlay):
    id = "rootfs.b1_firmware"
    feature = "wifi"
    scope = "device"
    note = "Copy the complete native B1 Wi-Fi/Bluetooth firmware directory"
    items = (
        SourceItem(
            source="device_s1:usr/share/firmware/wifi/C-4345__s-B1",
            dest="usr/share/firmware/wifi/C-4345__s-B1",
            op="copy",
            depends_on_signing=True,
        ),
    )

    def apply(self, ctx, art=None):
        ctx.verify_device_system(ctx.ssh)
        base = "/mnt1/usr/share/firmware/wifi/C-4345__s-B1"
        if ctx.t.get("device", {}).get("board") == "n61":
            # Preserve every native B1 blob; add donor-kernel names on the
            # writable SystemB only after the native directory is copied.
            native_files = tuple(name.replace("barbera", "tempranillo") for name in B1_FILES)
            ctx.ssh.sh(" && ".join(f'test -s "{base}/{name}"' for name in native_files))
        else:
            ctx.ssh.sh(" && ".join(f'test -s "{base}/{name}"' for name in B1_FILES))
        super().apply(ctx, art)
        if ctx.t.get("device", {}).get("board") == "n61":
            system_b = "/mnt6/usr/share/firmware/wifi/C-4345__s-B1"
            aliases = " && ".join(
                f'cp "{system_b}/{src}" "{system_b}/{dst}"'
                for src, dst in zip(native_files, B1_FILES)
            )
            ctx.ssh.sh(aliases)
