# iPhone 6 iOS 13.7 experimental port

This fork of [CelestialSayuki/n56-patcher](https://github.com/CelestialSayuki/n56-patcher) adds an **iPhone 6, non-Plus (N61AP / iPhone7,2)** profile to the original iPhone 6 Plus project.

The test iPhone 6 reached SpringBoard, completed activation and downloaded apps from the App Store. The port remains experimental: **Touch ID does not work**, vibration works on the tested device, speaker audio works on that device, while other audio paths remain unverified, and other hardware has not been comprehensively tested. Booting iOS 13 requires the patched USB boot chain and the Mac-side boot bundle.

## Start here

- **[Complete iPhone 6 installation guide and current limitations](docs/N61.md)** — setup, exact firmware inputs, DFU, installation, subsequent boots and recovery.
- [N61 target profile](targets/n61_ios13.py) — default patches and donor versions.
- [Historical upstream iPhone 6 Plus guide](docs/N56-upstream.md) — N56 information, not an N61 compatibility claim.
- [Technical notes from upstream](docs/conclusions.md) and [tool sources](tools/UPSTREAM.md).

Use **`--target n61-ios13` in every command** for an iPhone 6. This fork defaults to `n61-ios13`; select `--target n56-ios13` explicitly for the original iPhone 6 Plus target. **N66 is the iPhone 6s Plus donor, not the iPhone 6 Plus.**

This project creates APFS volumes and writes system files. Read the guide before running an install. It does not bypass Activation Lock. Apple firmware, account data and device-personalized tickets are not distributed here; each user supplies their own firmware and extracts their own ticket. The procedure runs locally without AI.

## Credits and license

The original N56 port, patcher architecture and driver work are by **[CelestialSayuki](https://github.com/CelestialSayuki)** and the contributors credited in the upstream project and tool submodules. This fork retains that history and adds the N61 adaptation and reproducibility documentation.

Code is licensed under [GPL-3.0](LICENSE). Submodules and separately sourced tools retain their own licenses. Apple's firmware is not covered by this license. [Support the original project](DONATE.md).
