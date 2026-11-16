# n61-patcher — experimental iOS 14.8

This branch ports iOS 14.8 (18H17) to the iPhone 6 (N61AP / iPhone7,2).
One test device reached Setup Assistant, passed activation, and reached the
Home Screen. This is a tethered, experimental port; successful setup does not
mean all hardware or system features work.

**Current test status (2026-11-16):** confirmed working on the test phone:
activation, Home Screen, adaptive still wallpapers, corrected stock app icons,
vibration, and basic Wi-Fi connectivity. The camera preview is black on both
cameras; slow-motion crashes Camera; microphone recording does not work; the
Phone and Weather apps did not open in the latest checks. Battery percentage
and screen brightness were reported working again. Shutdown can hang, and a
recent local patch set returned the device to Recovery. That patch set is not
in this branch because it has not been validated. See the detailed
[test matrix and limitations](docs/N61-iOS14.md#test-status-and-limitations).

- [iOS 14.8 setup, tested configuration, and limitations](docs/N61-iOS14.md)
- [iOS 13.7 on the default branch](https://github.com/tlfares/n61-patcher/blob/master/README.md)
- [Upstream iPhone 6 Plus project](https://github.com/CelestialSayuki/n56-patcher)

This project uses firmware and tickets supplied by the owner of the device.
Complete Apple activation normally in Setup Assistant.
