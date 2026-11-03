#!/usr/bin/env python3
"""Build repair-v7 with tagged absolute-pointer relocation support.

Rebuild and compact now relocate the low 56 bits of tagged Swift
_StringObject pointers, preserve the flag byte, and register rebases.
Run rebuild, compact, selector and branch repair while retaining old outputs."""
import time

import prepare_runtime_repair as s1
import prepare_compact_repair as s2
import prepare_selector_repair as s3
import prepare_branch_repair as s4

FULL = s1.FULL
s1.OUT = FULL / 'repair-v7-rebuild'
s2.BASE = FULL / 'repair-v7-rebuild'; s2.OUT = FULL / 'repair-v7-compact'
s3.BASE = FULL / 'repair-v7-compact'; s3.OUT = FULL / 'repair-v7-selector'
s4.V3 = FULL / 'repair-v7-compact'           # fallback source for all 50 libraries
s4.V4 = FULL / 'repair-v7-selector'          # 21 libraries with selector repairs
s4.OUT = FULL / 'repair-v7'

for name, stage in (('rebuild+swiftptr', s1), ('compact+swiftptr', s2),
                    ('selector', s3), ('branch', s4)):
    t = time.time()
    print(f'>>> {name} started', flush=True)
    stage.main()
    print(f'>>> {name} completed in {time.time()-t:.0f}s', flush=True)
print('>>> repair-v7 complete', flush=True)
