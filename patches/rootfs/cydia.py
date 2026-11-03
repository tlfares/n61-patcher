from core.patch import Patch
from patches.impl.rootfs.cydia import install


class RootfsCydia(Patch):
    id = "rootfs.cydia"
    layer = "rootfs"
    role = "overlay"
    scope = "version"
    feature = "checkra1n"
    requires = ("rootfs.base_stream", "rootfs.checkra1n_bootstrap")
    note = "Core bootstrap and Cydia; complete dpkg configuration at first boot"

    def apply(self, ctx, art=None):
        ctx.ssh.mount(ctx.t["mounts"]["system_b"], "/mnt6")
        install(ctx)
