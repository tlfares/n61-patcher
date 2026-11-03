#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Inject the N66 AppleChestnutDisplayPMU kext into the J96 prelinked kernel.

The four donor segments occupy zero-filled tails of existing mapped host
segments (CH_TARGETS), with appropriate protections and no new kernel load
commands. Preserve page offsets where possible; the non-page-aligned data
placement also needs precise ADRP and consumer-immediate rewriting.
Relocate internal pointers by their destination-segment delta, resolve external
pointers, register new slide offsets and add the kext prelink dictionary.

Usage: inject_chestnut.py [input output]
Without output paths, report the planned relocation without writing a kernel."""
import struct, sys, os, subprocess, base64

from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from paths import N66, INPUT

J96 = INPUT

# Four actual N66 Chestnut Mach-O segments (name, base VA, file size, VM size, code flag).
#  __TEXT      : contains __cstring, base 0x5d8b980 vmsize 0x723 (file 0x723)
#  __TEXT_EXEC : __text+__stubs, base 0x690e000 vmsize 0xc2c
#  __DATA      : __data(0xc8)+__common(0x88=bss), base 0x7878140 vmsize 0x150; file size only 0xc8
#  __DATA_CONST: got+modinit+modterm+const, base 0x6f6b100 vmsize 0xe18
# fsize is the file-backed byte count; the remainder up to vmsize is zero-filled BSS.
# Order code before data to keep executable and writable mappings separate.
CH_SEGS = [
    ("__TEXT_EXEC",  0xfffffff00690e000, 0xc2c,  0xc2c, True),   # Code
    ("__TEXT",       0xfffffff005d8b980, 0x723,  0x723, False),  # cstring
    ("__DATA_CONST", 0xfffffff006f6b100, 0xe18,  0xe18, False),  # got/vtable
    ("__DATA",       0xfffffff007878140, 0xc8,   0x150, False),  # data/bss (must be writable)
]
OLD_KMOD  = 0xfffffff007878140

# ---- Placement plan (2026-10-21, checked against arm_vm_init) ----
# arm_vm_init maps segment names plus LC vmaddr/vmsize; getsegbynamefromheader uses the first matching name.
# Appended/duplicate segments get no TTE (the source of two L3 translation faults). Place all four Chestnut segments in
# file-backed zero tails of existing prelink/kernel segments, preserving protections and avoiding jettison or LC changes.
# Keep new_va congruent to old_va mod 0x1000 where possible, inside each segment trailing-zero region.
# Host protections: __PLK_TEXT_EXEC r-x, __PRELINK_TEXT r--, __PLK_DATA_CONST r--, kernel __DATA rw-.
# jettison releases only __KLD, __LINKEDIT and legacy __PRELINK; these hosts remain resident.
CH_TARGETS = {
    "__TEXT_EXEC":  0xfffffff006da6000,  # -> __PLK_TEXT_EXEC(r-x) tail, free[0x6da52ac,0x6da8000)
    "__TEXT":       0xfffffff005f19980,  # -> __PRELINK_TEXT(r--)  tail, free[0x5f19124,0x5f1c000)  (Mach header + cstrings)
    "__DATA_CONST": 0xfffffff007002100,  # -> __PLK_DATA_CONST(r--) tail, free[0x7001540,0x7004000)
    # __DATA (including kmod_info) must occupy a writable prelink segment covered by _PrelinkLinkKASLROffsets:
    # Kernel __DATA has no KASLR entries; placing kmod_info there leaves address unslid and causes a jettison panic.
    # Only __PRELINK_DATA qualifies, but kext data/BSS leaves no safe gap with low12=0x140.
    # The only unclaimed tail gap is 0x4a2 bytes at [0x7903b5e,0x7904000), requiring non-page-aligned placement.
    # Precisely recalculate the page and paired ADD/LDR lo12 for 25 ADRPs targeting __DATA.
    # 0x7903b60 is 16-byte aligned; +0x150 ends at 0x7903cb0 in the same 0x7903000 page and tail gap.
    "__DATA":       0xfffffff007903b60,  # -> __PRELINK_DATA(rw-) tail gap [0x7903b5e,0x7904000)
}
KASLR_OFF_BASE = 0xfffffff0059d8000  # _PrelinkLinkKASLROffsets offset base

def parse(path):
    d = open(path, "rb").read()
    ncmds = struct.unpack("<I", d[16:20])[0]
    p = 32; segs = []
    for _ in range(ncmds):
        cmd, sz = struct.unpack("<II", d[p:p+8])
        if cmd == 0x19:
            nm = d[p+8:p+24].split(b"\0")[0].decode()
            vm, vs, fo, fsz = struct.unpack("<QQQQ", d[p+24:p+56])
            segs.append((nm, vm, vs, fo, fsz))
        p += sz
    return d, segs

def mkv2o(segs):
    def f(va):
        for nm, vm, vs, fo, fsz in segs:
            if fsz > 0 and vm <= va < vm+vs:
                return fo+(va-vm)
        return None
    return f

def nm_map(path):
    out = {}
    for line in subprocess.run(["nm","-n",path],capture_output=True,text=True).stdout.splitlines():
        a = line.split()
        if len(a) >= 3:
            try: out[a[2]] = int(a[0],16)
            except: pass
    return out

def rd64(d,o): return struct.unpack("<Q", d[o:o+8])[0]
def iskva(v): return 0xfffffff000000000 <= v < 0xfffffff010000000

# ---------- Build N66 -> J96 external-pointer mappings ----------
def build_resolver(dn, v2on, dj, v2oj, symn, symj):
    def read_vt(d, v2o, va, maxn=600):
        o=v2o(va); out={}; i=0
        while i<maxn:
            v=rd64(d,o+i*8)
            if i>=2 and v==0: break
            out[i]=v; i+=1
        return out
    base_vts = {
        "__ZTV9IOService":(symn.get("__ZTV9IOService"),symj.get("__ZTV9IOService")),
        "__ZTV8OSObject":(symn.get("__ZTV8OSObject"),symj.get("__ZTV8OSObject")),
        "__ZTV15OSMetaClassBase":(symn.get("__ZTV15OSMetaClassBase"),symj.get("__ZTV15OSMetaClassBase")),
        "__ZTV16AppleARMFunction":(0xfffffff006df4500,0xfffffff006dcc500),
    }
    vt_map={}
    for nm,(nva,jva) in base_vts.items():
        vn=read_vt(dn,v2on,nva); vj=read_vt(dj,v2oj,jva)
        assert len(vn)==len(vj), f"vtable {nm} length mismatch"
        for i,a in vn.items():
            b=vj.get(i)
            if a and b and iskva(a): vt_map.setdefault(a,b)
    name_map={}
    revn={}
    for nm,va in symn.items(): revn.setdefault(va,nm)
    for va,nm in revn.items():
        if nm in symj: name_map.setdefault(va,symj[nm])
    arm_pairs={
        0xfffffff006df4500:0xfffffff006dcc500, 0xfffffff00602250c:0xfffffff005fbe50c,
        0xfffffff006022578:0xfffffff005fbe4dc, 0xfffffff006022550:0xfffffff005fbe508,
        0xfffffff006022554:0xfffffff005fbf07c, 0xfffffff00602254c:0xfffffff005fbe54c,
        0xfffffff006022680:0xfffffff005fbe680, 0xfffffff006df5058:0xfffffff006dcd058,
        0xfffffff0077ec3c8:0xfffffff0077f03c8, 0xfffffff0077ec3b8:0xfffffff0077f03b8,
    }
    def resolve(t):
        if t in vt_map: return vt_map[t],"vtable"
        if t in name_map: return name_map[t],"symbol"
        if t in arm_pairs: return arm_pairs[t],"armfunc"
        return None,None
    return resolve, revn

def main():
    dn, sn = parse(N66); v2on = mkv2o(sn)
    dj, sj = parse(J96); v2oj = mkv2o(sj)
    symn = nm_map(N66); symj = nm_map(J96)
    resolve, revn = build_resolver(dn,v2on,dj,v2oj,symn,symj)

    # ---- Plan placements in host-segment tail gaps specified by CH_TARGETS ----
    layout = []   # (name, old_va, fsize, vmsize, iscode, new_va, delta)
    for nm, ova, fsize, vmsize, iscode in CH_SEGS:
        new_va = CH_TARGETS[nm]
        delta = new_va - ova
        if nm == "__DATA":
            # __DATA may be non-page-aligned; ADRPs targeting it get exact page/lo12 rewriting.
            # Require 8-byte alignment for scaled 64-bit loads/stores and keep the entire range in one ADRP page.
            assert delta % 8 == 0, f"{nm} delta must be 8-byte aligned (scaled load/store lo12)"
            assert (new_va & ~0xfff) == ((new_va+vmsize-1) & ~0xfff), \
                f"{nm} placement {new_va:#x}+{vmsize:#x} crosses a page and cannot use one ADRP"
        else:
            assert delta % 0x1000 == 0, f"{nm} delta is not page-aligned (new/old low12 must match)"
        # Placement must be file-backed with valid VM/file offsets; zero-tail coverage is checked before writing.
        assert v2oj(new_va) is not None and v2oj(new_va+vmsize-1) is not None, \
            f"{nm} placement {new_va:#x} is not file-backed by a host segment"
        layout.append([nm, ova, fsize, vmsize, iscode, new_va, delta])

    def seg_of_old(va):   # Find the segment containing VA across its full vmsize
        for nm,ova,fsize,vmsize,iscode,nva,delta in layout:
            if ova <= va < ova+vmsize: return (nm,delta)
        return None
    def seg_of_page(page):  # Find the unique segment intersecting this ADRP page
        for nm,ova,fsize,vmsize,iscode,nva,delta in layout:
            if page < ova+vmsize and page+0x1000 > ova: return (nm,delta)
        return None
    def remap_internal(va):
        r=seg_of_old(va)
        return va+r[1] if r else None

    print("=== Chestnut placement layout (tail gaps) ===")
    for nm,ova,fsize,vmsize,iscode,nva,delta in layout:
        print(f"  {nm:12} old={ova:#x} -> new={nva:#x} fsize={fsize:#x} vmsize={vmsize:#x} delta={delta:#x} ({'code' if iscode else 'data'})")

    # ---- Build relocated bytes for each segment ----
    own_ranges=[(ova,vmsize) for _,ova,_,vmsize,_,_,_ in layout]
    def is_own(a): return any(b<=a<b+s for b,s in own_ranges)
    stats={"internal":0,"external_ok":0,"external_fail":0,"adrp":0}
    fails={}
    kaslr_new=[]   # New KASLR offsets (u32 relative to KASLR_OFF_BASE)
    seg_bytes={}   # name -> relocated bytearray of length fsize

    # __DATA placement delta; non-page-aligned targets require exact ADRP page and consumer lo12 rewriting.
    data_delta = [e for e in layout if e[0]=="__DATA"][0][6]

    def set_adrp_page(buf, i, w, new_page, new_pc):
        """Point ADRP at offset i to new_page; new_pc is its relocated runtime address."""
        newimm = ((new_page & ~0xfff) - (new_pc & ~0xfff)) >> 12
        n21 = newimm & 0x1fffff
        nlo=n21&3; nhi=(n21>>2)&0x7ffff
        w2=(w & ~((0x3<<29)|(0x7ffff<<5))) | (nlo<<29) | (nhi<<5)
        struct.pack_into("<I",buf,i,w2)

    def patch_data_consumers(buf, ai, rd, adrp_page, fsize, new_data_page):
        """Rewrite lo12 consumers of the ADRP at ai (register rd, old __DATA page).
        Stop after the first ADD using rd as its source: the register then holds
        a complete address, so later loads/stores are dereferences, not page
        consumers. Without an ADD, rewrite page-relative load/store immediates
        until an ADD or register redefinition. Return the number changed."""
        def reloc_lo12(w,j,scale):
            imm12=(w>>10)&0xfff
            old_t=adrp_page+imm12*scale
            new_t=old_t+data_delta
            assert (new_t&~0xfff)==(new_data_page&~0xfff), \
                f"adrp@{ova+ai:#x} consumer@{ova+j:#x} target {new_t:#x} escapes new page {new_data_page:#x}"
            noff=new_t&0xfff
            assert noff%scale==0, "load/store lo12 is not scale-aligned"
            return (w&~(0xfff<<10))|((noff//scale)<<10)
        n=0
        for j in range(ai+4, min(ai+4*16, fsize), 4):
            w=struct.unpack("<I",buf[j:j+4])[0]
            is_adrp=(w&0x9f000000)==0x90000000
            is_add =(w&0xff800000)==0x91000000        # ADD (imm, 64-bit)
            is_ls  =(w&0x3b000000)==0x39000000        # LDR/STR (unsigned imm)
            # Stop if rd is redefined by another ADRP.
            if is_adrp and (w&0x1f)==rd: break
            if is_add and ((w>>5)&0x1f)==rd:
                assert ((w>>22)&1)==0, f"adrp@{ova+ai:#x} paired ADD uses an unsupported shift"
                struct.pack_into("<I",buf,j,reloc_lo12(w,j,1)); n+=1
                break   # The address is complete; do not change subsequent accesses through this register.
            if is_ls and ((w>>5)&0x1f)==rd:
                struct.pack_into("<I",buf,j,reloc_lo12(w,j,1<<((w>>30)&3))); n+=1
                continue
            # Stop when an ADD rewrites rd without consuming its page base.
            if is_add and (w&0x1f)==rd and ((w>>5)&0x1f)!=rd: break
        return n

    data_adrp_fixed=0; data_cons_fixed=0
    for nm,ova,fsize,vmsize,iscode,nva,delta in layout:
        o=v2on(ova); buf=bytearray(dn[o:o+fsize])
        if iscode:
            # Re-encode every ADRP: new_imm = old_imm + ((delta_tgt - delta_code)>>12)
            for i in range(0,fsize,4):
                w=struct.unpack("<I",buf[i:i+4])[0]
                if (w&0x9f000000)==0x90000000:
                    pc=ova+i
                    rd=w&0x1f
                    immlo=(w>>29)&3; immhi=(w>>5)&0x7ffff
                    imm=((immhi<<2)|immlo)
                    if imm&(1<<20): imm-=(1<<21)
                    page=(pc&~0xfff)+(imm<<12)
                    tgt=seg_of_page(page)
                    assert tgt, f"adrp@{pc:#x} page {page:#x} is out of range"
                    if tgt[0]=="__DATA" and (data_delta & 0xfff)!=0:
                        # For non-page-aligned placement, recalculate the new __DATA page and every paired lo12.
                        new_pc = pc + delta           # This code-segment delta is page-aligned.
                        new_data_page = (page + data_delta) & ~0xfff
                        set_adrp_page(buf, i, w, new_data_page, new_pc)
                        data_cons_fixed += patch_data_consumers(buf, i, rd, page, fsize, new_data_page)
                        data_adrp_fixed += 1
                        stats["adrp"]+=1
                        continue
                    dtgt=tgt[1]
                    newimm=imm+((dtgt-delta)>>12)
                    newimm21=newimm & 0x1fffff
                    nlo=newimm21&3; nhi=(newimm21>>2)&0x7ffff
                    w2=(w & ~((0x3<<29)|(0x7ffff<<5))) | (nlo<<29) | (nhi<<5)
                    struct.pack_into("<I",buf,i,w2)
                    stats["adrp"]+=1
            if data_adrp_fixed:
                print(f"  Non-page-aligned __DATA: rewrote {data_adrp_fixed} ADRPs and {data_cons_fixed} ADD/LDR/STR lo12 consumers")
        elif nm in ("__DATA","__DATA_CONST"):
            # Data: relocate each 8-byte absolute pointer
            for i in range(0,fsize,8):
                v=struct.unpack("<Q",buf[i:i+8])[0]
                if not iskva(v): continue
                slot_new=nva+i
                if is_own(v):
                    newv=remap_internal(v)
                    stats["internal"]+=1
                    kaslr_new.append(slot_new-KASLR_OFF_BASE)
                else:
                    newv,how=resolve(v)
                    if newv is None:
                        stats["external_fail"]+=1; fails[v]=fails.get(v,0)+1; continue
                    stats["external_ok"]+=1
                    kaslr_new.append(slot_new-KASLR_OFF_BASE)
                struct.pack_into("<Q",buf,i,newv)
        seg_bytes[nm]=buf

    # ---- Explicitly relocate kmod_info pointer fields ----
    # kmod_info is packed to 4 bytes; its pointers at offsets 4 mod 8 evade the 8-byte scan above.
    # Layout (arm64, packed): ... reference_count@144, reference_list@148,
    #   address@156, size@164, hdr_size@172, start@180, stop@188。
    # kmod_info starts at __DATA (= OLD_KMOD); address/start/stop are internal pointers.
    data_entry=[e for e in layout if e[0]=="__DATA"][0]
    _,d_ova,_,_,_,d_nva,d_delta=data_entry
    kmo = OLD_KMOD - d_ova   # kmod_info offset within __DATA (=0)
    buf = seg_bytes["__DATA"]
    km_fixed=0
    for fld_off in (156, 180, 188):   # address, start, stop
        pos = kmo + fld_off
        v = struct.unpack("<Q", buf[pos:pos+8])[0]
        if not iskva(v):
            continue
        if is_own(v):
            newv = remap_internal(v)
        else:
            newv, _how = resolve(v)
            if newv is None:
                raise SystemExit(f"Unresolved kmod_info pointer {v:#x} at field +{fld_off}")
        struct.pack_into("<Q", buf, pos, newv)
        kaslr_new.append((d_nva + pos) - KASLR_OFF_BASE)   # This slot requires a slide.
        km_fixed += 1
    print(f"  Relocated kmod_info pointer fields: {km_fixed}")

    print("\n=== Relocation statistics ===")
    print("  Internal data pointers:",stats["internal"]," external resolved:",stats["external_ok"]," failures:",stats["external_fail"],
          " ADRPs rewritten:",stats["adrp"])
    if fails:
        for v,c in sorted(fails.items()): print("     FAIL",hex(v),"x",c,revn.get(v,""))
        raise SystemExit("Unresolved external pointers; aborting")
    print("  New KASLR offsets:",len(kaslr_new),"entries")

    # ---- Rewrite the Chestnut kext Mach-O header inside __TEXT ----
    # The header starts at __TEXT. Change LC_SEGMENT vmaddr/fileoff, preserving vmsize/filesize.
    out_path = sys.argv[2] if len(sys.argv)>2 else None
    if not out_path:
        print("\n(dry-run; supply output paths to write)")
        return

    in_path = sys.argv[1]
    dj_in,sj_in = parse(in_path)
    dj_in=bytearray(dj_in)
    v2o_in = mkv2o(sj_in)   # Use the actual input KC segment table for file offsets (its layout should match J96 raw).

    # Rewrite LC_SEGMENT vmaddr/fileoff and section addr/offset in the Chestnut __TEXT header.
    # Each segment uses its host placement, with fileoff = v2o_in(new_va).
    txt=seg_bytes["__TEXT"]
    hdr_ncmds=struct.unpack("<I",txt[16:20])[0]; pp=32
    seg_newva={nm:nva for nm,_,_,_,_,nva,_ in layout}
    for _ in range(hdr_ncmds):
        c,s=struct.unpack("<II",txt[pp:pp+8])
        if c==0x19:
            segnm=txt[pp+8:pp+24].split(b"\0")[0].decode()
            if segnm in seg_newva:
                nva=seg_newva[segnm]
                struct.pack_into("<Q",txt,pp+24,nva)                 # vmaddr
                struct.pack_into("<Q",txt,pp+24+16,v2o_in(nva))      # fileoff
                nsect=struct.unpack("<I",txt[pp+64:pp+68])[0]; q=pp+72
                for _2 in range(nsect):
                    sa=struct.unpack("<Q",txt[q+32:q+40])[0]
                    d=nva-seg_oldva[segnm]
                    struct.pack_into("<Q",txt,q+32,sa+d)             # addr
                    so=struct.unpack("<I",txt[q+48:q+52])[0]
                    if so!=0:
                        struct.pack_into("<I",txt,q+48,v2o_in(sa+d)) # offset
                    q+=80
        pp+=s

    # ---- Write each relocated segment into its host file-backed zero tail ----
    # Do not append file data or load commands: arm_vm_init already maps these hosts with correct protections.
    # Require all-zero destination bytes before writing to preserve existing contents.
    for nm,ova,fsize,vmsize,iscode,nva,delta in layout:
        fo = v2o_in(nva)
        assert fo is not None, f"{nm} placement {nva:#x} has no file offset"
        region_old = dj_in[fo:fo+fsize]
        assert all(b==0 for b in region_old), \
            f"{nm} placement {nva:#x}(fo {fo:#x}) is not zero-filled ({sum(1 for b in region_old if b)} nonzero bytes)"
        dj_in[fo:fo+fsize] = seg_bytes[nm]
        print(f"  Write {nm:12} vm={nva:#x} fo={fo:#x} len={fsize:#x} ({'code r-x' if iscode else 'data'})")

    # ---- Update _PrelinkLinkKASLROffsets and add the kext dictionary ----
    patch_prelink_info(dj_in, kaslr_new, layout)

    open(out_path,"wb").write(dj_in)
    print("  Written:",out_path, "size", hex(len(dj_in)))

# Old Chestnut segment bases for relative section-address calculation
seg_oldva={"__TEXT":0xfffffff005d8b980,"__TEXT_EXEC":0xfffffff00690e000,
           "__DATA":0xfffffff007878140,"__DATA_CONST":0xfffffff006f6b100}

def add_kernel_segment(d, name, vm, vmsize, fo, fsize, prot=5):
    """Append one LC_SEGMENT_64 with no sections to the kernel Mach-O load commands."""
    ncmds=struct.unpack("<I",d[16:20])[0]
    sizeofcmds=struct.unpack("<I",d[20:24])[0]
    lc_end=32+sizeofcmds
    seg=struct.pack("<II16sQQQQiiII",0x19,0x48,name,vm,vmsize,fo,fsize,prot,prot,0,0)
    assert len(seg)==0x48
    d[lc_end:lc_end+0x48]=seg  # Overwrite header padding (at least 0x5a8 bytes confirmed).
    struct.pack_into("<I",d,16,ncmds+1)
    struct.pack_into("<I",d,20,sizeofcmds+0x48)

def patch_prelink_info(d, kaslr_new, layout):
    PI_FO=0x1eb4000; PI_VS=0x260000
    region=bytes(d[PI_FO:PI_FO+PI_VS])
    # Remove trailing zeros and edit only the actual plist contents.
    end=len(region)
    while end>0 and region[end-1]==0: end-=1
    txt=region[:end]
    # 1) KASLR blob: append offsets and increment the count by N
    k=txt.find(b"_PrelinkLinkKASLROffsets")
    a=txt.find(b"<data>",k)+6; b=txt.find(b"</data>",k)
    blob=bytearray(base64.b64decode(txt[a:b]))
    cnt=struct.unpack("<I",blob[:4])[0]
    for off in kaslr_new:
        blob+=struct.pack("<I",off)
    struct.pack_into("<I",blob,0,cnt+len(kaslr_new))
    newb64=base64.b64encode(blob)
    txt=txt[:a]+newb64+txt[b:]
    # 2) Prepend the Chestnut kext dictionary to _PrelinkInfoDictionary
    kd=make_kext_dict(layout)
    arr=txt.find(b"<array>",txt.find(b"_PrelinkInfoDictionary"))
    ins=arr+len(b"<array>")
    txt=txt[:ins]+kd+txt[ins:]
    # 3) Check the size remains <= PI_VS, then zero-pad
    assert len(txt)<=PI_VS, "PRELINK_INFO exceeds segment size %#x > %#x"%(len(txt),PI_VS)
    out=txt+b"\0"*(PI_VS-len(txt))
    d[PI_FO:PI_FO+PI_VS]=out
    print(f"  PRELINK_INFO new contents {len(txt):#x} / {PI_VS:#x}")

def make_kext_dict(layout):
    L={nm:(nva,fsize,vmsize) for nm,ova,fsize,vmsize,iscode,nva,delta in layout}
    text_va=L["__TEXT"][0]          # kext Mach-O header = __TEXT base = _PrelinkExecutableLoadAddr
    kmod=L["__DATA"][0]             # kmod_info starts at the __DATA base
    d=('<dict>'
       '<key>CFBundleIdentifier</key><string>com.apple.driver.AppleChestnutDisplayPMU</string>'
       '<key>CFBundleName</key><string>AppleChestnutDisplayPMU</string>'
       '<key>CFBundleVersion</key><string>1</string>'
       '<key>CFBundlePackageType</key><string>KEXT</string>'
       '<key>CFBundleExecutable</key><string>AppleChestnutDisplayPMU</string>'
       '<key>OSBundleRequired</key><string>Root</string>'
       '<key>IOKitPersonalities</key><dict>'
         '<key>AppleChestnutDisplayPMU</key><dict>'
           '<key>IOClass</key><string>AppleChestnutDisplayPMU</string>'
           '<key>IONameMatch</key><string>display-pmu,chestnut</string>'
           '<key>IOProviderClass</key><string>AppleARMIICDevice</string>'
           '<key>IOPlatformQuiesceAction</key><integer size="64">0x17ae8</integer>'
         '</dict>'
       '</dict>'
       '<key>OSBundleLibraries</key><dict>'
         '<key>com.apple.kpi.libkern</key><string>8.0</string>'
         '<key>com.apple.kpi.mach</key><string>8.0</string>'
         '<key>com.apple.kpi.unsupported</key><string>8.0</string>'
         '<key>com.apple.kpi.iokit</key><string>8.0</string>'
         '<key>com.apple.kpi.bsd</key><string>8.0</string>'
         '<key>com.apple.driver.AppleARMPlatform</key><string>1.0.0</string>'
       '</dict>'
       f'<key>_PrelinkExecutableLoadAddr</key><integer size="64">{text_va:#x}</integer>'
       f'<key>_PrelinkExecutableSourceAddr</key><integer size="64">{text_va:#x}</integer>'
       f'<key>_PrelinkExecutableSize</key><integer size="64">{L["__TEXT"][1]:#x}</integer>'
       f'<key>_PrelinkKmodInfo</key><integer size="64">{kmod:#x}</integer>'
       '<key>_PrelinkBundlePath</key><string>/System/Library/Extensions/AppleChestnutDisplayPMU.kext</string>'
       '</dict>')
    return d.encode()

if __name__=="__main__":
    main()
