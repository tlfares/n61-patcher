import os

from core import log
from core.overlay import SourceOverlay
from patches.impl.rootfs.phone_ui import (
    APPS,
    app_icon_resources,
    boot_ui_resources,
    settings_binaries,
    settings_resources,
)


class PhoneUiApps(SourceOverlay):
    id = "rootfs.phone_ui_apps"
    feature = "ui"
    requires = ("rootfs.base_stream", "rootfs.fairplayd_h2")
    note = "N66 17H35 Health/Phone/Wallet and matching iPhone UI resources"

    def apply(self, ctx, art=None):
        n66 = ctx.mount_rootfs("n66")
        j96 = ctx.mount_rootfs("j96")
        resources_source = ctx.mount_rootfs(ctx.t.get("ui_resource_profile", "n66"))
        ssh = ctx.ssh
        ssh.mount(ctx.t["mounts"]["system_b"], "/mnt6")

        for app in APPS:
            source = os.path.join(n66, "Applications", app)
            if not os.path.isdir(source):
                log.die(f"N66 17H35 is missing {app}")
            log.log(f"  Deploying {app}")
            ssh.deploy_path(source, "/mnt6/Applications/" + app)

        resources = settings_resources(resources_source, j96)
        log.log(f"  Deploying {len(resources)} iPhone Settings resources")
        ssh.deploy_relative_paths(resources_source, resources, "/mnt6")

        binaries = settings_binaries(n66, j96)
        log.log(f"  Deploying {len(binaries)} N66 Settings bundle binaries")
        ssh.deploy_relative_paths(n66, binaries, "/mnt6")

        boot_ui = boot_ui_resources(resources_source, j96)
        log.log(f"  Deploying {len(boot_ui)} iPhone boot UI resources")
        ssh.deploy_relative_paths(resources_source, boot_ui, "/mnt6")

        icons = app_icon_resources(resources_source, j96, include_apps=APPS)
        log.log(f"  Replacing {len(icons)} iPhone app icon resources")
        ssh.deploy_relative_paths(resources_source, icons, "/mnt6")

        wallpaper_paths = ("Library/Wallpaper/Live/iPhone",
                           "Library/Wallpaper/Stills/iPhone",
                           "Library/Wallpaper/Wallpapers~iphone.plist",
                           "Library/Wallpaper/DefaultWallpapers.plist") \
            if ctx.t.get("install_wallpapers", True) else ()
        for relative in wallpaper_paths:
            source = os.path.join(resources_source, relative)
            ssh.deploy_path(source, "/mnt6/" + relative)

        ssh.sh("rm -f /mnt6/usr/libexec/n56-register-apps "
               "/mnt6/usr/libexec/n56-app-identifiers.plist "
               "/mnt6/System/Library/LaunchDaemons/com.n56.phone-apps.register.plist "
               "/mnt6/System/Library/LaunchDaemons/com.n56.phone-apps.frameworks.plist")
        ssh.sync()
