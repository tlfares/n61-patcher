"""DRV2604 vibration driver."""
from core.patch import Patch
from core.impl import transform


class KcVibration(Patch):
    id = "kc.vibration"
    layer = "kc"
    feature = "vibration"
    scope = "device"
    requires = ('kc.j96_clean',)
    after = ('kc.pmu_d2186', 'kc.sn2400', 'kc.chestnut_kext', 'kc.mt_native', 'kc.wifi')
    note = "DRV2604 vibration driver"

    def apply(self, ctx, art):
        return transform(ctx, "kc/vibration/transplant.py", art, "vibration", True)
