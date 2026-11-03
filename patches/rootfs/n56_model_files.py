from core.overlay import SourceItem, SourceOverlay


class RootfsNativeModelFiles(SourceOverlay):
    id = "rootfs.native_model_files"
    feature = "core"
    scope = "device"
    note = "Copy missing native model resources from SystemA"
    items = ()

    def apply(self, ctx, art=None):
        model = ctx.t["device"]["model"].upper()
        short = model[:3]
        paths = (
            f"System/Library/LaunchDaemons/com.apple.jetsamproperties.{short}.plist",
            f"usr/share/firmware/multitouch/{short}.mtprops",
            f"Library/Audio/Tunings/{short}",
            f"System/Library/Frameworks/MediaToolbox.framework/{short}",
            f"System/Library/PrivateFrameworks/ACTFramework.framework/{short}",
            "System/Library/ProductDocuments/RegulatoryImages",
        )
        self.items = tuple(SourceItem(source="device_s1:" + path, dest=path,
                                      op="copy-if-missing", depends_on_signing=False)
                           for path in paths) + (
            SourceItem(source=f"device_s1:System/Library/Watchdog/ThermalMonitor.bundle/{model}.bundle/Info.plist",
                       dest=f"System/Library/ThermalMonitor/{model}-Info.plist",
                       op="copy-if-missing", depends_on_signing=False,
                       mode=0o644, uid=0, gid=0, check={"plist": True}),
        )
        return super().apply(ctx, art)
