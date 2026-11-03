import os

from core import log
from core.overlay import SourceItem, SourceOverlay
from patches.impl.rootfs.health_derive import derive_health
from patches.impl.rootfs.health_resources import bundle_resource_paths


CACHE = "System/Library/Caches/com.apple.dyld/dyld_shared_cache_arm64"


class Health(SourceOverlay):
    id = "rootfs.health"
    feature = "health"
    requires = ("rootfs.base_stream", "rootfs.fairplayd_h2", "rootfs.phone_ui_apps")
    note = "Deploy final repair-v7 libraries and patch dyld2 cache handling"
    items = (
        SourceItem(source="ipsw:n66:System/Library/PrivateFrameworks/HealthPluginHost.framework/healthappd",
                   dest="System/Library/PrivateFrameworks/HealthPluginHost.framework/healthappd",
                   op="copy", depends_on_signing=True),
        SourceItem(source="ipsw:n66:System/Library/LaunchDaemons/com.apple.healthappd.plist",
                   dest="System/Library/LaunchDaemons/com.apple.healthappd.plist",
                   op="copy", depends_on_signing=True, check={"plist": True}),
        SourceItem(source="target:" + CACHE, dest=CACHE, op="bytes-patch",
                   depends_on_signing=True, offset=104,
                   before="0100000000000000", after="0000000000000000"),
        SourceItem(source="target:" + CACHE, dest=CACHE, op="bytes-patch",
                   depends_on_signing=True, offset=1705017567,
                   before="eb9880e86f1527e1674347bda9933653d3ccfbf4f35b7afc58d9dc03b4c9f7d9",
                   after="ee66a62a874080f3f2e11f4ee246662faae59cc3fda82a508fd8c64f3ba29d1b"),
    )

    def apply(self, ctx, art=None):
        n66 = ctx.mount_rootfs("n66")
        resources = bundle_resource_paths(n66)
        log.log(f"  Streaming {len(resources)} Health bundle resources...")
        ctx.ssh.mount(ctx.t["mounts"]["system_b"], "/mnt6")
        ctx.ssh.deploy_relative_paths(n66, resources, "/mnt6")
        libraries = derive_health(ctx)
        count = sum(len(files) for _, _, files in os.walk(libraries))
        if count != 50:
            log.die(f"Expected 50 Health donor libraries, found {count}")
        log.log("  Streaming 50 final Health/Phone libraries...")
        ctx.ssh.deploy_path(libraries, "/mnt6", uid=0, gid=0)
        super().apply(ctx, art)
