#!/usr/bin/env python3
"""Build repair-v6 by restoring cross-library calls optimized by dyld.

The shared cache replaces calls to stubs with branch islands outside the
extracted image. Those offsets fault after extraction. Resolve each of the
401 affected calls in 50 libraries to one of seven exported symbols, then
retarget it to an existing local stub. Reuse selector-fixed repair-v4
libraries where present and repair-v3 otherwise, then sign and package."""
import json
from pathlib import Path
import re
import shutil
import struct
import subprocess

from runtime_libraries import CacheIndex
from prepare_runtime_repair import PROJECT, check_layout, trust_cache
import branch_stubs as bs

HERE = Path(__file__).resolve().parent
FULL = HERE / 'full'
V3 = FULL / 'repair-v3'
V4 = FULL / 'repair-v4'
OUT = FULL / 'repair-v6'
CACHE = '/Volumes/YukonH17H35.N66OS/System/Library/Caches/com.apple.dyld/dyld_shared_cache_arm64'


def fix_library(data, cache_base, resolver):
    """Retarget external bl instructions to local stubs; return (data, fixed count, unresolved)."""
    data = bytearray(data)
    segs, sym2stub = bs.library_stubs(data)

    def foff(vm):
        s = next(x for x in segs if x['vm'] <= vm < x['vm'] + x['filesize'])
        return s['file'] + vm - s['vm']

    branches, span = bs.out_of_image_branches(data)
    fixed, unresolved = 0, []
    for addr, target in branches:
        symbol, addend = resolver.symbol(cache_base + target)
        if symbol is None or addend != 0 or symbol not in sym2stub:
            unresolved.append((hex(addr), symbol.decode('latin1') if symbol else None, addend))
            continue
        stub = sym2stub[symbol]
        disp = stub - addr
        assert -(1 << 27) <= disp < (1 << 27) and disp % 4 == 0, f'bl out of range at {addr:#x}'
        opcode = 0x94000000 | ((disp >> 2) & 0x03ffffff)
        struct.pack_into('<I', data, foff(addr), opcode)
        fixed += 1
    return data, fixed, unresolved


def main():
    OUT.mkdir(exist_ok=True)
    cache = CacheIndex(CACHE)
    resolver = bs.Resolver(cache)
    manifest = json.loads((V4 / 'manifest.json').read_text())
    raw = (V4 / 'trustcache.raw').read_bytes()
    results, payloads = {}, {}
    total_fixed = 0
    for index, library in enumerate(manifest['cdhashes'], 1):
        relative = library.lstrip('/')
        source = V4 / 'libraries' / relative
        if not source.exists():
            source = V3 / 'libraries' / relative
        image = cache.images.get(library)
        assert image is not None, f'Cache is missing {library}'
        data, fixed, unresolved = fix_library(source.read_bytes(), image.address, resolver)
        assert not unresolved, f'{library}: unresolved branches {unresolved}'
        total_fixed += fixed
        destination = OUT / 'libraries' / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
        subprocess.run(['codesign', '--remove-signature', str(destination)], check=True, capture_output=True)
        subprocess.run(['codesign', '-s', '-', '-f', '--digest-algorithm=sha256', str(destination)],
                       check=True, capture_output=True)
        check_layout(destination)
        signature = subprocess.run(['codesign', '-dvvvv', str(destination)], check=True,
                                   capture_output=True, text=True).stderr
        digest = re.search(r'CandidateCDHash sha256=([0-9a-f]{40})', signature)[1]
        manifest['cdhashes'][library] = digest
        raw = trust_cache(raw, bytes.fromhex(digest))
        payloads[relative] = destination
        results[library] = fixed
        if index % 10 == 0:
            print(f'Branch repairs {index}/{len(manifest["cdhashes"])}; {total_fixed} calls fixed.', flush=True)

    for name in ('images', 'bin'):
        shutil.copytree(V4 / name, OUT / name, dirs_exist_ok=True)
    for name in ('mrm.plist', 'mrm.plist.sig', 'cache-source.plist', 'boot.sh'):
        shutil.copy2(V4 / name, OUT / name)
    for name in ('mrm.plist', 'mrm.plist.sig'):
        payloads['System/Library/Caches/com.apple.xpc.launchd/' + name] = OUT / name
    (OUT / 'trustcache.raw').write_bytes(raw)
    subprocess.run([str(PROJECT / 'projects/img4lib/img4'), '-i', str(OUT / 'trustcache.raw'), '-A',
                    '-o', str(OUT / 'images/boot_TC.img4'), '-M', str(PROJECT / 'extracted/IM4M.bin'),
                    '-T', 'rtsc'], check=True, capture_output=True)
    total = sum(path.stat().st_size for path in payloads.values())
    manifest.update(stage='restore cache de-stubbed cross-image branches', files=sorted(payloads),
                    installed_bytes=total, cache_source=str(OUT / 'cache-source.plist'),
                    boot='bash phone_apps_bringup/20261029/full/repair-v6/boot.sh',
                    branch_repairs=results)
    (OUT / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    with (OUT / 'manifest.sha256').open('w') as stream:
        subprocess.run(['shasum', '-a', '256',
                        *['images/' + p.name for p in sorted((OUT / 'images').iterdir())],
                        'bin/gaster', 'bin/irecovery', 'boot.sh'], cwd=OUT, check=True, stdout=stream)
    print(f'repair-v6 complete: {total_fixed} cross-library calls fixed, {total / 1048576:.1f} MiB.', flush=True)


if __name__ == '__main__':
    main()
