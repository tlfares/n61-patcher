#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""append_watchtower.py <orig_im4p_or_img4> <my_complzss> <out>

An iOS kernelcache IM4P payload contains complzss (0x180-byte header plus the
compressed stream), followed by watchtower data (a 0xC000-byte Mach-O here).
img4 -P recompression preserves that trailer, but img4 -R and mkcomplzss do not.
Without it iBoot stops at "validate kernelcache". Extract the original trailer
and append it to the generated complzss payload."""
import struct, sys

def biggest_octet(path):
    d = open(path, "rb").read()
    def rdlen(p):
        l = d[p]; p += 1
        if l & 0x80:
            nb = l & 0x7f; L = int.from_bytes(d[p:p+nb], "big"); p += nb
        else:
            L = l
        return L, p
    assert d[0] == 0x30, "Not an ASN.1 SEQUENCE"
    L, p = rdlen(1); end = p + L
    octs = []
    def walk(a, b):
        pp = a
        while pp < b:
            tag = d[pp]; Ln, q = rdlen(pp+1)
            if tag == 0x04:
                octs.append(d[q:q+Ln])
            elif tag == 0x30:
                walk(q, q+Ln)
            pp = q + Ln
    walk(p, end)
    return max(octs, key=len)

def watchtower(payload):
    assert payload[:8] == b"complzss", "Original payload is not complzss"
    csize = struct.unpack(">I", payload[16:20])[0]
    tail = payload[0x180 + csize:]
    return tail

def main():
    orig, mine, out = sys.argv[1], sys.argv[2], sys.argv[3]
    wt = watchtower(biggest_octet(orig))
    mydata = open(mine, "rb").read()
    open(out, "wb").write(mydata + wt)
    sys.stderr.write(f"append_watchtower: +{len(wt)} bytes -> {out} (total {len(mydata)+len(wt)})\n")

if __name__ == "__main__":
    main()
