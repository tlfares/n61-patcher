"""Experimental iOS 14.8 profile for iPhone 6 (N61AP)."""
from copy import deepcopy
from targets.n56_ios14 import TARGET as N56

TARGET = deepcopy(N56)
TARGET.update(
    name="n61-ios14",
    workdir="build/n61-ios14-18H17/current",
    derived_root="ipsw/cache/derived/n61-ios14-18H17",
    trustcache_builder="patches.ios14.impl.rootfs.n61_trustcache",
    disable_locationd=True,
)
TARGET["device"].update(model="n61ap", product="iPhone7,2", touch="multi-touch,n61")
TARGET["source_profiles"]["n56"]["ipsw"] = "iPhone_4.7_12.5.8_16H88_Restore.ipsw"
TARGET["source_profiles"]["n71"] = {
    "build": "18H17",
    "device_class": "n71ap",
    "ipsw": "iPhone_4.7_14.8_18H17_Restore.ipsw",
}
TARGET["ui_resource_profile"] = "n71"
TARGET["derived"].update(
    ibss_src="../extracted/n61ap_ios12/iBSS.n61.patched",
    ibec_dec="../extracted/n61ap_ios12/iBEC.n61.dec",
)
# Start with the device adaptations needed to bring up the system. Optional
# features that embed N56 identities or need hardware validation are opt-in.
TARGET["features"] = [
    "core", "charging", "chestnut", "touch", "wifi", "pmu",
    "sep", "ans", "checkra1n", "ui", "baseband", "adaptive_wallpapers",
]

# Keep the stock wallpaper picker until N61 rendering is checked on-device.
TARGET["exclude"] = ["rootfs.wallpaper"]
