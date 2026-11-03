from core.overlay import SourceItem, SourceOverlay


CACHE = "System/Library/Caches/com.apple.dyld/dyld_shared_cache_arm64"
EDITS = (
    (553028640,
     "00" * 162,
     "0102190219021902190219021902190219021902010219021902680203021902090200006a0000006a00130219021902190219020b0215023b023d02190219021902190219020d02fd011902190219026e001902190219021902fb0105023302ff01070235026e0019021902190219020f02190219021902190219023f026c006c00f50117023702190219021902190243023902f30111024502f101f7014102f901"),
    (552611880, "086c0051", "08440051"),
    (552611884, "1f190171", "1f410171"),
    (552611896, "e90100b0", "290300b0"),
    (552611900, "29593091", "29813091"),
    (1709334847,
     "76f6c93b3c903448176ae5d2fbecdb04596613e0441ffc8058f850a123db7d5a",
     "ae4a995247dc34ced4af27c2ce23eea91f386297c49a9cb8febf30744fc122e8"),
    (1709338079,
     "dde9e59c2e01920493e04c4a6e1c2ba8b7978fc2698389f595d35df3f0c0ebc1",
     "710f6a212e3650bf4ed678b768b7ae53912347b3199db7ca7a54f17c78494ced"),
)


def edits_for_board(board):
    """Select Mav10 for native N56/N61 without changing device identity.

    libTelephonyUtilDynamic's TelephonyRadiosGetProduct returns 0x11 for
    N56AP and 0x1a for N61AP. The table is indexed by product - 0x11;
    the upstream table leaves N61's slot 9 at the unknown-model branch.
    Both boards use the existing Mav10 branch (halfword 0x0201).
    """
    if board != "n61":
        return EDITS
    table = bytearray.fromhex(EDITS[0][2])
    table[18:20] = bytes.fromhex("0102")
    result = list(EDITS)
    result[0] = (EDITS[0][0], EDITS[0][1], table.hex())
    # SHA-256 slot for the modified 4 KiB table page in J96 17H35.
    result[-1] = (EDITS[-1][0], EDITS[-1][1],
                  "443d51841ba41a50ac16dfecd0c75ce9219ec32c9df87d3500a24d97e33fd3ff")
    return tuple(result)


class BasebandCompatibility(SourceOverlay):
    id = "rootfs.baseband_compatibility"
    feature = "baseband"
    scope = "version"
    note = "Native CommCenter product mapping, Mav10 firmware and iPhone carrier bundles"
    items = tuple(
        SourceItem(source="target:" + CACHE, dest=CACHE, op="bytes-patch",
                   depends_on_signing=True, offset=offset, before=before, after=after)
        for offset, before, after in EDITS
    ) + (
        SourceItem(source="device_s1:usr/local/standalone/firmware/Baseband/Mav10",
                   dest="usr/local/standalone/firmware/Baseband/Mav10",
                   op="copy", depends_on_signing=True),
        SourceItem(source="device_s1:usr/local/standalone/firmware/Baseband/Mav10",
                   dest="usr/standalone/firmware/Baseband/Mav10",
                   op="copy", depends_on_signing=True),
        SourceItem(source="ipsw:n66:System/Library/Carrier Bundles/iPhone",
                   dest="System/Library/Carrier Bundles/iPhone",
                   op="copy", depends_on_signing=True),
    )

    def apply(self, ctx, art=None):
        self.items = tuple(
            SourceItem(source="target:" + CACHE, dest=CACHE, op="bytes-patch",
                       depends_on_signing=True, offset=offset, before=before, after=after)
            for offset, before, after in edits_for_board(ctx.t["device"]["board"])
        ) + type(self).items[len(EDITS):]
        super().apply(ctx, art)
