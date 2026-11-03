# Tool sources

Install full Xcode on macOS first (`n56-jb-info` and `create_systembag` require
the iPhoneOS SDK), then run these commands from the repository root:

```sh
python3 -m pip install -r requirements.txt
python3 tools/setup.py
```

| Upstream submodule | Purpose | Local path |
| --- | --- | --- |
| [SSHRD_Script](https://github.com/verygenericname/SSHRD_Script) | gaster, irecovery, iBoot64Patcher, KPlooshFinder, sshpass, iproxy | `tools/SSHRD_Script/Darwin/` |
| [img4lib](https://github.com/xerub/img4lib) | IMG4 extraction and packaging | `tools/img4lib/img4` |
| [dualra1n](https://github.com/dualra1n/dualra1n) | Kernel64Patcher, kairos, dtree_patcher; iOS 14 fsck and apfs.fs | `tools/dualra1n/binaries/Darwin/`; copied to `donors/projects/dualra1n-bin/apfsios14` |
| [gaster](https://github.com/verygenericname/gaster) | DFU exploit and iBoot decryption; built from source | `tools/SSHRD_Script/Darwin/gaster` |
| [devicetree-parse](https://github.com/khanhduytran0/devicetree-parse) | DeviceTree extraction and repacking | `tools/devicetree-parse/devicetree-repack` |

Versions are pinned by submodule gitlinks; inspect them with `git submodule status`.
Setup fetches the required tools and builds img4 locally with upstream lzfse and
macOS CommonCrypto. dualra1n uses a sparse checkout of the Darwin tools and licenses.

Setup also downloads the official [checkra1n 0.12.4](https://checkra.in/releases/)
DMG, verifies its SHA-256 and extracts the userland into `donors/checkra1n/`.
See `tools/fetch_checkra1n.py`. Extra local tools may be placed in `tools/bin/`.
