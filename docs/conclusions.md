# Upstream N56 iOS 13.7 technical conclusions

These are the translated technical notes for the original **iPhone 6 Plus (N56AP / iPhone7,1)** port, which boots iOS 13.7 alongside iOS 12.5.8 SystemA. They preserve the upstream findings; they are **not a validation report for the N61 fork**. See [N61.md](N61.md) for the iPhone 6 status.

## Boot chain and system components

- Order: gaster → iBSS → iBEC → DeviceTree → TrustCache → KernelCache → `bootx`. Images are wrapped with the device's own IM4M.
- Sources: kernel and base rootfs from J96 17H35; Health, Phone, Wallet and iPhone Settings resources from N66 17H35; model files, baseband and Wi-Fi firmware from the device's SystemA 16H88.
- Volume layout: s1 System (iOS 12), s2 Data, s3 Baseband Data (role `0x80`), s4 SystemB (role `0x1`), s5 DataB (role `0x40`).
- The boot TrustCache must match the installed mrm cache and added binaries. Rebuild it after changes to mrm or Mach-O files.
- A restore changes the APTicket. Run `extract-im4m` again afterwards.
- Do not mount the source DMG with `noowners` before writing the device: that can turn ownership into `501:20`.

## PMU and Oscar

- The final N56 approach adapts iOS 13 `AppleD2207PMU` to the N56 register layout, keeps RTC enabled and disables the watchdog personality.
- GPIO corrections: preserve mask `0x1d → 0x05` at `0xfffffff006da049c`; change output-2 encoding `0x40 → 0x10` at `0xfffffff006da04d0`.
- Oscar firmware, `oscard`, `locationd` and CoreMotion must all come from iOS 13. Mixing iOS 12 firmware and `oscard` produced no activity-recognition callbacks.
- AppleOscar, AppleOnboardSerial and SoC GPIO use J96 17H35. AppleSamsungSerial's UFCON selections use native N56 values (`0x1f1`, `0x1c1`, `0x1c1`, mask `0xff`), implemented in `patches/kc/pmu_d2186.py`.
- Transplanting tvOS 13's native `AppleD2186PMU` was abandoned: it reached userland but caused widespread Wi-Fi, Bluetooth, baseband and sensor regressions.
- Reducing the event range from 14 to 13 did not repair timesync. The range remains 14 bytes.

## Hardware userland

- Wi-Fi needs both the `kc.wifi` hash patches and SystemA's `usr/share/firmware/wifi/C-4345__s-B1/` files: `barbera.trx`, `barbera.clmb`, `barbera.txcb` and `P-barbera_M-CORO_V-m__m-5.1.txt`.
- Baseband operation requires the CommCenter product table in the dyld cache to recognize N56; native Mav10 firmware in both `usr/standalone/firmware/Baseband/` and `usr/local/standalone/firmware/Baseband/`; N66 `Carrier Bundles/iPhone/`; s3 role `0x80`; and the modified dyld cache's cdhash in the TrustCache.
- Health library extraction removes stubs and invalidates direct branches between libraries. Redirect those branches to existing stubs, and deploy resources, binaries and cdhashes together.
- `installd` needs a fix for an empty Application container collection before the first free-signed app can install.
- `backupd`'s `Null backup UDID` exception comes from `-[MBServiceCache addBackup:lastModified:]`. At file offset `0x127dc4`, changing `200900b4 → a00500b4` returns early for records without a UDID while preserving valid database writes.

## SEP and DataB encryption

- The device runs iOS 12 sepOS. It rejects the iOS 13 kernel's default class-M requests (tags 7/8) and v1 request body with error `-13`.
- The container keybag is wrapped with SEP/hardware keys, not encrypted using the container UUID. It cannot be recreated by treating that UUID as a key.
- The compatibility path selects the retained v0 encoder and the old tag 1/2 format: SKS 49 creates media keys, SKS 50 unwraps them, and SKS 9/15/16 handle per-file keys. It also skips class-M migration.
- `patches/impl/kc/legacy_data.json` contains ten regions: a 316-byte bridge at `0xfffffff005f31c40`, seven AppleSEPKeyStore call/branch changes, and APFS changes at `0xfffffff006904154` and `0xfffffff00690429c`. Without them, AKS unwrap returns `0xe007c00d` and DataB does not mount.
- The iOS 12 ramdisk's `MKBKeyBagCreateSystem` creates the new DataB `systembag.kb`. iOS 13 `keybagd --init` loads it but does not generate it.
- Systembag creation must preserve existing `BAG1` wrapping material by setting `KBSaveSystemBagHandle`'s fifth argument to 1. Otherwise it replaces device-global EffaceableStorage records and affects DataA.
- Do not mount native s2 or manually mount encrypted s5 in the ramdisk. Use the patcher's controlled initialization sequence.
- The ramdisk starts without SEP loaded (`seputil --ping` reports `ping failed`). Calling `newfs_apfs -P` in that state hangs DataB creation and locks the container; even a read-only s1 mount can then time out. Restarting is required. The flow was changed to load SEP before volume creation; upstream marked this revised clean-install ordering as awaiting fresh-install validation.

## checkra1n

- The flow does not boot through PongoOS. KPF modifies the raw kernel at build time and userland is installed in SystemB.
- KPF must run on the original J96 kernel before generic boot patches and hardware transforms are merged. Running it after generic patches fails at `amfi_sha1`.
- Five shellcode function pointers are changed to offsets relative to their table entries so they follow the kernel slide.
- `Missing kernel_cache_addr` occurs because the kernel task's `TASK_DYLD_INFO` is empty. The kernel publishes an offsetcache during BSD initialization:
  - Hook J96's inline `IOKitBSDInit` path at `0xfffffff007490e78` (file offset `0x48ce78`); the separately exported `0xfffffff00766d548` function is not on that runtime path.
  - `_kernel_task` is at `0xfffffff007091ab8`; `vm_kernel_slide` is at `0xfffffff007096268`.
  - Task `all_image_info_addr=0x3c8` points at the blob; `all_image_info_size=0x3d0` stores the slide according to the protocol.
  - Flags are `0`, capability is `3`, and the blob contains seven keys in 344 bytes.
- Userland includes `/binpack`, the `com.n56.checkra1n` launch job and an automatically started `loaderd`. Device USB SSH listens on port 44; the host forwards it with `iproxy 2222 44`.

## TrustCache pairing

In the upstream comparison, clean-build KC, iBSS and DeviceTree matched the on-device bundle byte for byte. Removing `serial=3` changed the embedded iBEC boot arguments. Two TrustCache builds both contained 2,238 entries and were identical to each other, but differed from the device TrustCache in three userland entries:

| Build cdhash | File | Difference from the device |
| --- | --- | --- |
| `fbcae34e…` | Generated mrm cache | Device mrm had `2c08a843…` and lacked some App Extension entries; remaining keys and values matched |
| `b55f90e8…` | `/binpack/usr/bin/n56-jb-info` | File was absent on the device |
| `aa9ddae2…` | `/Applications/loader.app/loader` | File cdhash matched, but the device TrustCache lacked it because Loader was installed after boot |

The device also had `718d4f0c…` and `94f03f31…`, with no matching file found in its `/binpack`, Loader or checkra1n directories. Their source was not identified.

A new TrustCache must be paired with the rootfs generated by the same build. Fresh installation generates mrm and TrustCache together. An existing installation should keep its paired bundle: replacing only the TrustCache can omit its mrm cdhash and cause launchd to reject it. After a restore, extract a new IM4M and generate a new matched installation and bundle.

## Installation steps added to the pipeline

- Systembag: encrypted-mode `rootfs.finish` loads SEP, mounts DataB (tries `-o protect`, then a normal mount), and uses `tools/systembag/create_systembag.c` with the ramdisk MobileKeyBag `PRESERVE_BAG1` patch. The helper and patch were compared with the earlier implementation. Upstream reconstructed the mount/load ordering from prior records and marked that ordering as awaiting fresh-install validation.
- Cydia: `rootfs.cydia` downloads the Loader's `strap.tar.lzma` and `cydia.tar.lzma` with pinned SHA-256 values and extracts them to SystemB. On first boot, `n56-init.sh` runs `dpkg --configure -a` and `uicache`; its log is `/var/log/n56-cydia.log`. Success creates `/.bootstrapped`.
