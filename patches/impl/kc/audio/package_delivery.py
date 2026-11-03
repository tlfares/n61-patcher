#!/usr/bin/env python3
"""Package a standalone macOS DFU boot chain."""
import hashlib
from pathlib import Path
import shutil
import subprocess
import zipfile

HERE = Path(__file__).resolve().parent
from paths import ROOT, WORK, OUTPUT
IMAGES = ('boot_iBSS.img4', 'boot_iBEC.img4', 'boot_DT.img4',
          'boot_TC.img4', 'boot_KC.img4')


def package():
    launch = HERE / 'launch'
    (launch / 'bin').mkdir(parents=True, exist_ok=True)
    (launch / 'images').mkdir(exist_ok=True)
    for name in IMAGES:
        shutil.copyfile(OUTPUT / name, launch / 'images' / name)
    tools = ROOT / 'tools/SSHRD_Script/Darwin'
    for name in ('gaster', 'irecovery'):
        destination = launch / 'bin' / name
        if destination.exists():
            destination.unlink()
        shutil.copyfile(tools / name, destination)
        destination.chmod(0o755)
        subprocess.run(['/usr/bin/codesign', '--force', '--sign', '-', str(destination)], check=True)
    shutil.copyfile(HERE / 'launch_boot.sh', launch / 'boot.sh')
    (launch / 'boot.command').write_text(
        '#!/bin/bash\nROOT="$(cd "$(dirname "$0")" && pwd)"\n'
        'exec /bin/bash "$ROOT/boot.sh" "$@"\n')
    for name in ('boot.sh', 'boot.command'):
        (launch / name).chmod(0o755)
    (launch / 'README.md').write_text(
        '# N56 audio boot bundle\n\n'
        'Put the N56 in DFU, connect USB and open `boot.command`. The script prepares DFU and sends '
        'iBSS, iBEC, DeviceTree, TrustCache and the audio kernelcache.\n\n'
        'From Terminal, run `bash boot.sh` in this folder. To check files only, use `bash boot.sh --verify`.\n\n'
        'Boot logs are saved in `logs/`. The tools and all five images are included in this bundle.\n')
    entries = ['boot.sh', 'boot.command', 'bin/gaster', 'bin/irecovery']
    entries += ['images/' + name for name in IMAGES]
    manifest = ''.join(hashlib.sha256((launch / name).read_bytes()).hexdigest()
                       + '  ' + name + '\n' for name in entries)
    (launch / 'manifest.sha256').write_text(manifest)
    archive = HERE / 'N56-audio-DFU.zip'
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as output:
        for path in sorted(launch.rglob('*')):
            if path.is_file() and 'logs' not in path.relative_to(launch).parts:
                output.write(path, 'N56-audio-DFU/' + str(path.relative_to(launch)))
    print('Standalone boot chain:', launch)
    print('Archive:', archive)


if __name__ == '__main__':
    package()
