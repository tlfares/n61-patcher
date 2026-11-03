"""Patch registry, feature selection, and dependency ordering.

A patch performs one operation in the kc, dt, or rootfs layer. Each binary layer
has one base plus ordered transforms. Rootfs patches stream the base image,
deploy file overlays, or finalize volumes. requires adds dependencies; after
orders patches that are already selected. scope is device or version.

base.apply(ctx) returns a binary path; transform.apply(ctx, art) returns its
replacement. stream/overlay/finalize.apply(ctx) operate through ctx.ssh."""
import importlib.util
import os

from . import log

LAYER_ORDER = ["dt", "kc", "rootfs"]
ROLE_ORDER = {"base": 0, "transform": 1, "stream": 2, "overlay": 3, "finalize": 4}
_REGISTRY = []


class Patch:
    id = None
    layer = None
    feature = "core"
    scope = "version"
    role = "transform"
    requires = ()
    after = ()       # Order only: absent patches are not selected.
    donors = ()
    note = ""
    manual = False   # True: requires manual steps; skipped unless explicitly enabled

    def __init_subclass__(cls, **kw):
        super().__init_subclass__(**kw)
        if cls.id:
            _REGISTRY.append(cls)

    def apply(self, ctx, art=None):
        raise NotImplementedError(f"{self.id} does not implement apply")

    def __repr__(self):
        return f"<{self.id} {self.layer}/{self.role} feat={self.feature}>"


def discover(patches_dir=None):
    """Import modules under patches/ and populate the registry. Idempotent."""
    _REGISTRY.clear()
    patches_dir = patches_dir or os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "patches")
    for layer in sorted(os.listdir(patches_dir)):
        ldir = os.path.join(patches_dir, layer)
        if not os.path.isdir(ldir):
            continue
        for fn in sorted(os.listdir(ldir)):
            if not fn.endswith(".py") or fn.startswith("_"):
                continue
            path = os.path.join(ldir, fn)
            spec = importlib.util.spec_from_file_location(f"n56patch_{layer}_{fn[:-3]}", path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
    return list(_REGISTRY)


def _instances():
    return {c.id: c() for c in _REGISTRY}


def _topo(patches):
    """Stable topological ordering within a layer using requires and optional after."""
    by_id = {p.id: p for p in patches}
    out, seen, temp = [], set(), set()

    def visit(p):
        if p.id in seen:
            return
        if p.id in temp:
            log.die(f"Patch dependency cycle: {p.id}")
        temp.add(p.id)
        for dep in (*p.requires, *p.after):
            if dep in by_id:
                visit(by_id[dep])
        temp.discard(p.id)
        seen.add(p.id)
        out.append(p)

    for p in patches:
        visit(p)
    return out


def select(target):
    """Select patches from a target and return {layer: [ordered patch instances]}.

    Select when patch.feature is in target features or patch.id is explicitly listed.
    kc_patches overrides KC transforms; exclude removes patches; bases selects each layer baseline.
    """
    discover()
    inst = _instances()
    features = set(target.get("features", []))
    want_ids = set(target.get("patches", []))
    kc_picks = target.get("kc_patches")
    if kc_picks is not None:
        want_ids.update(kc_picks)
    exclude = set(target.get("exclude", []))
    bases = target.get("bases", {})

    unknown = (want_ids | exclude) - inst.keys()
    if unknown:
        log.die(f"Unknown patch: {', '.join(sorted(unknown))}")
    if kc_picks is not None:
        invalid = [pid for pid in kc_picks if inst[pid].layer != "kc" or inst[pid].role == "base"]
        if invalid:
            log.die(f"--patches requires KC transform IDs: {', '.join(invalid)}")
    known_features = {p.feature for p in inst.values()}
    unknown_features = features - known_features
    if unknown_features:
        log.die(f"Unknown feature: {', '.join(sorted(unknown_features))}")

    chosen = []
    for p in inst.values():
        if p.id in exclude:
            continue
        if p.role == "base":
            if bases.get(p.layer) == p.id:
                chosen.append(p)
            continue
        if p.layer == "kc" and kc_picks is not None:
            if p.id in kc_picks:
                chosen.append(p)
        elif p.feature in features or p.id in want_ids:
            chosen.append(p)

    # A selected transform brings its prerequisites with it. Explicit excludes
    # and a different base are configuration errors rather than partial builds.
    selected = {p.id for p in chosen}
    pending = list(chosen)
    while pending:
        patch = pending.pop()
        for dep in patch.requires:
            if dep in selected:
                continue
            if dep in exclude or dep not in inst:
                log.die(f"{patch.id} requires {dep}; adjust patches/exclude")
            required = inst[dep]
            if required.role == "base" and bases.get(required.layer) != dep:
                log.die(f"{patch.id} requires base {dep}")
            selected.add(dep)
            chosen.append(required)
            pending.append(required)

    # Require exactly one base per binary layer
    result = {}
    for layer in LAYER_ORDER:
        group = [p for p in chosen if p.layer == layer]
        bases_in = [p for p in group if p.role == "base"]
        if layer in ("dt", "kc") and len(bases_in) != 1:
            names = [b.id for b in bases_in]
            log.die(f"{layer} layer requires exactly one base (current: {names or 'none'}; "
                    f"set it in profile bases['{layer}'])")
        group.sort(key=lambda p: (ROLE_ORDER.get(p.role, 9),))
        group = _topo(group)
        group.sort(key=lambda p: ROLE_ORDER.get(p.role, 9))
        result[layer] = group
    return result


def summary(selection):
    lines = []
    for layer in LAYER_ORDER:
        for p in selection.get(layer, []):
            lines.append(f"  [{layer:6s}] {p.role:9s} {p.feature:9s} {p.id}")
    return "\n".join(lines)
