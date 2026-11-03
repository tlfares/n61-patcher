"""Wi-Fi B1 firmware adaptation."""
from core.patch import Patch
from core.impl import transform


class KcWifi(Patch):
    id = "kc.wifi"
    layer = "kc"
    feature = "wifi"
    scope = "device"
    requires = ('kc.j96_clean',)
    after = ('kc.pmu_d2186', 'kc.sn2400', 'kc.chestnut_kext', 'kc.mt_native')
    note = "Wi-Fi B1 firmware adaptation"

    def apply(self, ctx, art):
        return transform(ctx, "kc/wifi/hashstore_patch.py", art, "wifi", True)
