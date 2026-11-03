# -*- coding: utf-8 -*-
"""Adapt the J96 touch personality to the N56/N61 matching name and merged parameters."""
from core.patch import Patch
from core.impl import transform


class KcMtNative(Patch):
    id = "kc.mt_native"
    layer = "kc"
    role = "transform"
    feature = "touch"
    scope = "device"
    requires = ('kc.pmu_d2186', 'kc.chestnut_kext')
    note = "Touch personality J96 to N56/N61"

    def apply(self, ctx, art):
        board = ctx.t["device"].get("board", "n56")
        return transform(ctx, "kc/mt_n56.py", art, "mt", extra=("--board", board))
