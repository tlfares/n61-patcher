from pathlib import Path
import hashlib


APPS = ("Health.app", "MobilePhone.app", "Passbook.app")
MACHO_MAGICS = {
    b"\xcf\xfa\xed\xfe", b"\xfe\xed\xfa\xcf",
    b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca",
}


def _is_macho(path):
    with path.open("rb") as stream:
        return stream.read(4) in MACHO_MAGICS


def _different(source, target):
    return not target.is_file() or hashlib.sha256(source.read_bytes()).digest() != \
        hashlib.sha256(target.read_bytes()).digest()


def _settings_scopes(n66):
    n66 = Path(n66)
    scopes = [
        "Applications/Preferences.app",
        "System/Library/PreferenceBundles",
        "System/Library/PrivateFrameworks/Settings",
        "System/Library/ProductDocuments/Notices",
    ]
    frameworks = n66 / "System/Library/PrivateFrameworks"
    names = {path.name for path in frameworks.glob("*Settings*.framework")}
    names.update(path.name for path in frameworks.glob("*Preferences*.framework"))
    scopes.extend("System/Library/PrivateFrameworks/" + name for name in sorted(names))
    return scopes


def settings_resources(n66, j96):
    n66, j96 = Path(n66), Path(j96)
    paths = []
    for scope in _settings_scopes(n66):
        root = n66 / scope
        if not root.exists():
            continue
        for source in sorted(root.rglob("*")):
            if not source.is_file() or source.is_symlink() or "_CodeSignature" in source.parts:
                continue
            relative = source.relative_to(n66)
            if not _is_macho(source) and _different(source, j96 / relative):
                paths.append(relative.as_posix())
    return paths


def settings_binaries(n66, j96):
    n66, j96 = Path(n66), Path(j96)
    paths = []
    for scope in _settings_scopes(n66):
        root = n66 / scope
        if not root.exists():
            continue
        for source in sorted(root.rglob("*")):
            if not source.is_file() or source.is_symlink() or "_CodeSignature" in source.parts:
                continue
            relative = source.relative_to(n66)
            if _is_macho(source) and _different(source, j96 / relative):
                paths.append(relative.as_posix())
    return paths


def boot_ui_resources(n66, j96):
    n66, j96 = Path(n66), Path(j96)
    root = n66 / "System/Library/PrivateFrameworks/ProgressUI.framework"
    paths = []
    for source in sorted(root.rglob("*")):
        if not source.is_file() or source.is_symlink() or "_CodeSignature" in source.parts:
            continue
        relative = source.relative_to(n66)
        if not _is_macho(source) and _different(source, j96 / relative):
            paths.append(relative.as_posix())
    return paths


def app_machos(n66):
    n66 = Path(n66)
    result = []
    for app in APPS:
        for source in sorted((n66 / "Applications" / app).rglob("*")):
            if source.is_file():
                with source.open("rb") as stream:
                    if stream.read(4) in MACHO_MAGICS:
                        result.append(source)
    return result


def app_icon_resources(n66, j96, include_apps=()):
    n66, j96 = Path(n66), Path(j96)
    paths = []
    # Most removable Apple apps live here before first-boot installation;
    # they later move into /var/containers/Bundle/Application/<UUID>/.
    for scope in ("Applications", "private/var/staged_system_apps"):
        root = n66 / scope
        if not root.is_dir():
            continue
        for app in sorted(path for path in root.iterdir()
                          if path.is_dir() and ((j96 / scope / path.name).is_dir()
                                               or path.name in include_apps)):
            for source in sorted(app.rglob("*")):
                if not source.is_file():
                    continue
                name = source.name
                if not (name.startswith("AppIcon") or name == "Assets.car" or
                        ("Icon" in name and ("@3x" in name or "@2x" in name))):
                    continue
                relative = source.relative_to(n66)
                target = j96 / relative
                if not target.exists() or hashlib.sha256(source.read_bytes()).digest() != \
                        hashlib.sha256(target.read_bytes()).digest():
                    paths.append(relative.as_posix())
    return paths


def ui_resource_items(ctx, paths):
    """Use matching 2x resources for N61 while retaining the N56 default."""
    from core.overlay import SourceItem

    profile = ctx.t.get("ui_resource_profile", "n66")
    root = Path(ctx.mount_rootfs(profile))
    items = []
    for path in paths:
        preferred = path.replace("@3x", "@2x") if profile == "n71" else path
        if (root / preferred).is_file():
            source, relative = profile, preferred
        elif (root / path).is_file():
            source, relative = profile, path
        else:
            source, relative = "n66", path
        items.append(SourceItem(source=f"ipsw:{source}:{relative}", dest=relative,
                                op="copy", depends_on_signing=False))
    return tuple(items)
