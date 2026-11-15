"""Build the iOS 14.8 trust cache for the N61 boot profile."""
from pathlib import Path
import struct

from core.tools import run
from core.trustcache import TrustCache
from patches.ios14.impl.rootfs import baseband_product, launchd_cache


def build(ctx):
    trust = TrustCache(ctx)
    stock = ctx.wk("trustcache.ios14.stock.raw")
    run([ctx.tool("img4"), "-i", ctx.donor("trustcache"), "-o", stock])
    header, entries = trust._entries(Path(stock).read_bytes())

    def add(digest, kind=TrustCache.HASH_SHA256):
        entries.setdefault(digest, digest + bytes((kind, 0)))

    if launchd_cache.selected(ctx, "rootfs.baseband_product", "baseband"):
        stock_cache = Path(ctx.mount_rootfs("j96")) / baseband_product.CACHE
        add(baseband_product.page_hash_edit(stock_cache))

    if launchd_cache.required(ctx):
        cache = launchd_cache.build(ctx)
        add(trust._cdhash(cache["plist"], cache["sig"]))
    if launchd_cache.fairplay_selected(ctx):
        add(*trust._cdhash_any(Path(ctx.mount_rootfs("n66")) / "usr/sbin/fairplayd.H2"))
    if launchd_cache.checkra1n_selected(ctx):
        from patches.ios14.impl.rootfs.checkra1n import prepare
        from patches.shared.impl.rootfs.cydia import machos

        for path in (*prepare(ctx)["machos"], *machos(ctx)):
            add(*trust._cdhash_any(path))

    output = Path(ctx.wk("trustcache.ios14.full.raw"))
    output.write_bytes(header + struct.pack("<I", len(entries)) +
                       b"".join(entries[digest] for digest in sorted(entries)))
    return str(output)
