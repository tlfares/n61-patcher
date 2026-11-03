from core.overlay import SourceItem, SourceOverlay


class Apticket(SourceOverlay):
    id = "rootfs.apticket"
    feature = "core"
    scope = "device"
    note = "Native APTicket -> mobileactivationd collectSIK path"
    items = (
        SourceItem(source="derive:im4m", dest="System/Library/Caches/apticket.der",
                   op="copy", depends_on_signing=False,
                   mode=0o644, uid=0, gid=0),
    )

    def derive(self, ctx, name, item):
        return ctx.im4m()
