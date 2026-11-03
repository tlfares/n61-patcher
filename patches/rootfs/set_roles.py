# -*- coding: utf-8 -*-
"""Assign System(0x1)/Data(0x40) APFS roles after finalization.

All target volumes must be unmounted before writing roles. Slice numbers
and roles come from the target profile's volumes.roles mapping."""
from core.apfs import Apfs
from core.patch import Patch


class RootfsSetRoles(Patch):
    id = "rootfs.set_roles"
    layer = "rootfs"
    role = "finalize"
    feature = "core"
    scope = "device"
    requires = ("rootfs.finish",)
    note = "s4→System(0x1), s5→Data(0x40)"

    def apply(self, ctx, art=None):
        roles = {int(k): v for k, v in ctx.t["volumes"]["roles"].items()}
        Apfs(ctx).set_roles(roles, write=not ctx.dry_run)
