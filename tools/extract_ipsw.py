#!/usr/bin/env python3
"""Derive build inputs from local IPSWs into ipsw/cache/derived/.

Run tools/setup.py first. No firmware inputs or generated outputs are committed.
"""
import argparse
from pathlib import Path
import shutil
import subprocess
import tempfile
import zipfile

REPO = Path(__file__).resolve().parents[1]
IMG4 = REPO / 'tools/img4lib/img4'
DT_PARSE = REPO / 'tools/devicetree-parse/devicetree-parse'
OUT = REPO / 'ipsw/cache/derived'
N56 = 'iPhone_5.5_12.5.8_16H88_Restore.ipsw'
N61 = 'iPhone_4.7_12.5.8_16H88_Restore.ipsw'
N66 = 'iPhone_5.5_13.7_17H35_Restore.ipsw'
J96 = 'iPad_64bit_TouchID_13.7_17H35_Restore.ipsw'
N56_ROOTFS = '038-87140-057.dmg'
N61_ROOTFS = '038-87263-058.dmg'
WIFI = 'usr/share/firmware/wifi/C-4345__s-B1'
WIFI_FILES = ('barbera.trx', 'barbera.clmb', 'barbera.txcb')
def native_outputs(board):
    board = board.lower()
    if board not in ('n56', 'n61'):
        raise ValueError(f'unsupported native board: {board}')
    return (
    f'extracted/{board}ap_ios12/kernelcache.release.iphone7.decompressed',
    f'extracted/{board}ap_ios12/DeviceTree.{board}ap.jsonc',
    *(f'wifi/{board}/C-4345__s-B1/{name}' for name in WIFI_FILES),
    )


SHARED_OUTPUTS = (
    'extracted/n66ap_ios13/kernelcache.release.n66.decompressed',
    'extracted/n66ap_ios13/DeviceTree.n66ap.jsonc',
    'extracted/j96ap_ios13/kernelcache.release.ipad5',
    'extracted/j96ap_ios13/038-68261-036.dmg.trustcache',
)
OUTPUTS = native_outputs('n56') + SHARED_OUTPUTS


def run(*cmd):
    subprocess.run([str(c) for c in cmd], check=True)


def extract_member(ipsw, member, work):
    path = work / Path(member).name
    with zipfile.ZipFile(ipsw) as archive, archive.open(member) as source, open(path, 'wb') as dest:
        shutil.copyfileobj(source, dest, 8 * 1024 * 1024)
    return path


def copy_member(ipsw, member, dest, work):
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(extract_member(ipsw, member, work), dest)


def make_kernel(ipsw, member, dest, work):
    src = extract_member(ipsw, member, work)
    dest.parent.mkdir(parents=True, exist_ok=True)
    run(IMG4, '-i', src, '-o', dest)


def make_devicetree(ipsw, member, dest, work):
    im4p = extract_member(ipsw, member, work)
    binary = work / (im4p.stem + '.bin')
    run(IMG4, '-i', im4p, '-o', binary)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with open(dest, 'wb') as f:
        subprocess.run([str(DT_PARSE), str(binary)], stdout=f, check=True)


def copy_wifi(ipsw, dest, work, rootfs_entry=N56_ROOTFS):
    dmg = extract_member(ipsw, rootfs_entry, work)
    mountpoint = work / 'n56-rootfs'
    mountpoint.mkdir()
    run('hdiutil', 'attach', '-readonly', '-nobrowse', '-mountpoint', mountpoint, dmg)
    try:
        dest.mkdir(parents=True, exist_ok=True)
        # The iPhone 6 (n61) uses the same B1 chipset with the older
        # "tempranillo" firmware names. The transplanted iOS 13 kernel
        # looks up the iPhone 7 (barbera) names, so preserve payload bytes
        # and publish them under the expected keys.
        has_tempranillo = (mountpoint / WIFI / 'tempranillo.trx').exists()
        board_names = ({name: name.replace('barbera', 'tempranillo')
                        for name in WIFI_FILES} if has_tempranillo
                       else {name: name for name in WIFI_FILES})
        for name, source_name in board_names.items():
            shutil.copyfile(mountpoint / WIFI / source_name, dest / name)
    finally:
        run('hdiutil', 'detach', mountpoint)


def decrypt_iboot(ipsw, gaster, patcher, out=OUT, board='n56'):
    """Decrypt iBSS/iBEC and patch iBSS using the attached device in DFU."""
    board = board.lower()
    if board not in ('n56', 'n61'):
        raise ValueError(f'unsupported native board: {board}')
    dest = out / f'extracted/{board}ap_ios12'
    dest.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        ibss = extract_member(ipsw, f'Firmware/dfu/iBSS.{board}.RELEASE.im4p', work)
        ibec = extract_member(ipsw, f'Firmware/dfu/iBEC.{board}.RELEASE.im4p', work)
        run(gaster, 'pwn')
        run(gaster, 'decrypt', ibss, work / 'iBSS.dec')
        run(gaster, 'decrypt', ibec, dest / f'iBEC.{board}.dec')
        subprocess.run([str(patcher), str(work / 'iBSS.dec'), str(dest / f'iBSS.{board}.patched')], check=False)
        if not (dest / f'iBSS.{board}.patched').exists():
            raise SystemExit('iBoot64Patcher did not generate iBSS')


def generate(native, n66, j96, out=OUT, native_board='n56', rootfs_entry=None):
    native_board = native_board.lower()
    if native_board not in ('n56', 'n61'):
        raise ValueError(f'unsupported native board: {native_board}')
    rootfs_entry = rootfs_entry or (N56_ROOTFS if native_board == 'n56' else N61_ROOTFS)
    if not rootfs_entry:
        raise ValueError(f'{native_board} rootfs entry is required')
    extracted = out / 'extracted'
    native_dir = extracted / f'{native_board}ap_ios12'
    native_dt = f'DeviceTree.{native_board}ap.im4p'
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        make_kernel(native, 'kernelcache.release.iphone7', native_dir / 'kernelcache.release.iphone7.decompressed', work)
        make_devicetree(native, f'Firmware/all_flash/{native_dt}', native_dir / f'DeviceTree.{native_board}ap.jsonc', work)
        make_kernel(n66, 'kernelcache.release.n66', extracted / 'n66ap_ios13/kernelcache.release.n66.decompressed', work)
        make_devicetree(n66, 'Firmware/all_flash/DeviceTree.n66ap.im4p', extracted / 'n66ap_ios13/DeviceTree.n66ap.jsonc', work)
        copy_member(j96, 'kernelcache.release.ipad5', extracted / 'j96ap_ios13/kernelcache.release.ipad5', work)
        copy_member(j96, 'Firmware/038-68261-036.dmg.trustcache', extracted / 'j96ap_ios13/038-68261-036.dmg.trustcache', work)
        copy_wifi(native, out / f'wifi/{native_board}/C-4345__s-B1', work, rootfs_entry)


def main():
    ipsw = REPO / 'ipsw'
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--n56-ipsw', type=Path, default=ipsw / N56)
    parser.add_argument('--native-ipsw', type=Path, default=None,
                        help='override the native iOS 12 IPSW for the selected board')
    parser.add_argument('--native-board', choices=('n56', 'n61'), default='n56')
    parser.add_argument('--native-rootfs-entry', default=None)
    parser.add_argument('--n66-ipsw', type=Path, default=ipsw / N66)
    parser.add_argument('--j96-ipsw', type=Path, default=ipsw / J96)
    parser.add_argument('--out', type=Path, default=OUT)
    args = parser.parse_args()
    native_ipsw = args.native_ipsw or (args.n56_ipsw if args.native_board == 'n56' else ipsw / N61)
    generate(native_ipsw, args.n66_ipsw, args.j96_ipsw, args.out,
             args.native_board, args.native_rootfs_entry)
    print('derived inputs ready:', args.out.resolve())


if __name__ == '__main__':
    main()
