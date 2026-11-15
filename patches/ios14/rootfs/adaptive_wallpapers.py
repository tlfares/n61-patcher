"""Install N61-sized light and dark still wallpapers as JPEGs."""
from core.patch import Patch
from patches.ios14.impl.rootfs.adaptive_wallpapers import prepare


class AdaptiveWallpapers(Patch):
    id = "rootfs.adaptive_wallpapers"
    layer = "rootfs"
    role = "overlay"
    feature = "adaptive_wallpapers"
    requires = ("rootfs.base_stream",)
    note = "Install iOS 14 light and dark JPEG wallpapers for the iPhone 6 display"

    def apply(self, ctx, art=None):
        root = prepare(ctx.mount_rootfs("n71"), ctx.wk("adaptive-wallpapers"))
        session = ctx.ssh
        session.mount(ctx.t["mounts"]["system_b"], "/mnt6")
        session.deploy_path(str(root / "Library/Wallpaper"), "/mnt6/Library/Wallpaper",
                            uid=0, gid=0)
        session.sync()
