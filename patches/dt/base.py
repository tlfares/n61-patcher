"""Build N56 iOS 13 DeviceTree from native N56 and N66 donor trees."""
from core.patch import Patch
from core.impl import run_impl


class DtBase(Patch):
    id = "dt.base"
    layer = "dt"
    role = "base"
    feature = "core"
    scope = "version"
    note = "Generate the native iOS 13 DeviceTree from the native and N66 donor trees"

    def apply(self, ctx, art=None):
        run_impl(ctx, "dt/dt_patch.py", ["--repack", ctx.tool("devicetree-repack"),
                                        "--out", ctx.work], output_dir=ctx.work)
        board = ctx.t.get("device", {}).get("board", "n56")
        return ctx.wk(f"DeviceTree.{board}_native.bin")
