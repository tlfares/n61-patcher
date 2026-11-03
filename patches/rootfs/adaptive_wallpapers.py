"""N61 appearance-aware JPEG wallpaper overlay."""
from pathlib import Path

from core.patch import Patch
from patches.impl.rootfs.adaptive_wallpapers import prepare


class AdaptiveWallpapers(Patch):
    id = "rootfs.adaptive_wallpapers"
    layer = "rootfs"
    feature = "ui"
    role = "overlay"
    requires = ("rootfs.phone_ui_apps",)
    note = "N61 light/dark JPEG wallpapers derived locally from N71 17H35"

    def apply(self, ctx, art=None):
        if ctx.t.get("wallpaper_format") != "jpeg-adaptive":
            return
        source = ctx.mount_rootfs(ctx.t.get("ui_resource_profile", "n71"))
        output = prepare(source, Path(ctx.wk("adaptive-wallpapers")))
        ctx.ssh.mount(ctx.t["mounts"]["system_b"], "/mnt6")
        ctx.ssh.deploy_path(str(output / "Library/Wallpaper"), "/mnt6/Library/Wallpaper", uid=0, gid=0)
        ctx.ssh.sync()
