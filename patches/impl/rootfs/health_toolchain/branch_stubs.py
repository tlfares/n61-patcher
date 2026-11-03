"""Restore cross-library direct branches optimized by the dyld shared cache.

The cache replaces calls to stubs with branch islands outside the extracted
library. Resolve each external call to its exported symbol, then retarget
it to the matching existing __stubs entry within that library."""
import struct

from capstone import Cs, CS_ARCH_ARM64, CS_MODE_ARM
from runtime_libraries import segments, commands, bindings

_md = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
_md.detail = True


def _q(data, off):
    return struct.unpack_from('<Q', data, off)[0]


class Resolver:
    """Resolve cached addresses to final exported names using the source cache."""

    def __init__(self, cache):
        self.cache = cache
        self.addr2sym = {}
        for img in cache.images.values():
            for name, addr in img.exports.items():
                self.addr2sym.setdefault(addr, bytes(name))

    def _follow_island(self, addr, depth=0):
        """Follow branch islands and stubs; return the final code address."""
        if depth > 8:
            return addr
        fo = self.cache.file_offset(addr)
        ins = list(_md.disasm(self.cache.data[fo:fo + 12], addr))
        if len(ins) >= 3 and ins[0].mnemonic == 'adrp' and ins[2].mnemonic == 'br':
            page = ins[0].operands[1].imm
            if ins[1].mnemonic == 'add':
                target = page + ins[1].operands[2].imm
            elif ins[1].mnemonic == 'ldr':
                target = _q(self.cache.data, self.cache.file_offset(page + ins[1].operands[1].mem.disp))
            else:
                return addr
            return self._follow_island(target, depth + 1)
        return addr

    def symbol(self, cache_target):
        """Resolve a cached branch target to (symbol, addend); nonzero addends point inside a function."""
        final = self._follow_island(cache_target)
        # Strip a leading branch veneer, often b #self+4.
        if final in self.addr2sym:
            return self.addr2sym[final], 0
        fo = self.cache.file_offset(final)
        ins = list(_md.disasm(self.cache.data[fo:fo + 4], final))
        if ins and ins[0].mnemonic == 'b' and ins[0].operands[0].imm == final + 4:
            if final + 4 in self.addr2sym:
                return self.addr2sym[final + 4], 0
        loc = self.cache.section_at(final)
        if loc:
            img, _ = loc
            best = None
            for name, addr in img.exports.items():
                if addr <= final and (best is None or addr > best[1]):
                    best = (bytes(name), addr)
            if best:
                return best[0], final - best[1]
        return None, final


def library_stubs(data):
    """Map library symbol names to __stubs VM addresses."""
    segs = segments(data)
    dyld = next(p for k, p, _ in commands(data) if k == 0x80000022)
    imports = {}
    for field in (16, 24, 32):
        start, size = struct.unpack_from('<II', data, dyld + field)
        if size:
            for r in bindings(data, start, size):
                imports[segs[r['segment']]['vm'] + r['offset']] = bytes(r['symbol'])

    def foff(vm):
        s = next(x for x in segs if x['vm'] <= vm < x['vm'] + x['filesize'])
        return s['file'] + vm - s['vm']

    sym2stub = {}
    for seg in segs:
        for sec in seg['sections']:
            if sec['name'] != '__stubs':
                continue
            for addr in range(sec['vm'], sec['vm'] + sec['size'], 12):
                ins = list(_md.disasm(data[foff(addr):foff(addr) + 12], addr))
                if len(ins) >= 2 and ins[0].mnemonic == 'adrp' and ins[1].mnemonic == 'ldr':
                    got = ins[0].operands[1].imm + ins[1].operands[1].mem.disp
                    if got in imports:
                        sym2stub[imports[got]] = addr
    return segs, sym2stub


def out_of_image_branches(data):
    """Return (instruction VM, external target VM) pairs in the library VM address space."""
    segs = segments(data)
    span = max(s['vm'] + s['size'] for s in segs)
    tsec = next((sc for s in segs for sc in s['sections'] if sc['name'] == '__text'), None)
    if not tsec:
        return [], span
    fo = next(s['file'] + tsec['vm'] - s['vm'] for s in segs if s['vm'] <= tsec['vm'] < s['vm'] + s['filesize'])
    out = []
    for i in _md.disasm(data[fo:fo + tsec['size']], tsec['vm']):
        if i.mnemonic == 'bl' and i.operands and i.operands[0].type == 2:
            t = i.operands[0].imm
            if not (0 <= t < span):
                out.append((i.address, t))
    return out, span
