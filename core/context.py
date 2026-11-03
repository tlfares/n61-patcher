"""Shared runtime context: target profile, firmware paths, tools, and SSH.

ctx.t holds the target dictionary; ctx.src/ctx.tool/ctx.donor resolve inputs.
ctx.work contains generated outputs. core.ramdisk injects the SSH session."""
import importlib.util
import hashlib
import json
import os
import plistlib
import shutil
import subprocess
import sys
import time
import zipfile

from . import log

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))   # n56-patcher/
TARGETS_DIR = os.path.join(REPO, "targets")
IPSW_DIR = os.path.join(REPO, "ipsw")     # User-downloaded IPSWs; excluded from Git
DERIVED_DIR = os.path.join(IPSW_DIR, "cache", "derived")   # Build inputs derived from IPSWs
STATE_DIR = os.path.join(REPO, "state")   # Local device state, including the ticket extracted after a restore


def load_target(name):
    """Load targets/<name>.py and return its TARGET dictionary."""
    if os.path.isabs(name):
        path = name if name.endswith(".py") else name + ".py"
    else:
        # Target names allow hyphens (n56-ios13); filenames use underscores (n56_ios13.py)
        fn = name if name.endswith(".py") else name + ".py"
        path = os.path.join(TARGETS_DIR, fn)
        if not os.path.exists(path):
            path = os.path.join(TARGETS_DIR, fn.replace("-", "_"))
    if not os.path.exists(path):
        log.die(f"Target profile not found: {path}")
    spec = importlib.util.spec_from_file_location("n56_target", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if not hasattr(mod, "TARGET"):
        log.die(f"{path} does not define TARGET")
    t = mod.TARGET
    t.setdefault("_path", path)
    return t


class Context:
    def __init__(self, target, workdir=None, dry_run=False):
        self.t = load_target(target) if isinstance(target, str) else target
        self.dry_run = dry_run

        src = os.environ.get("N56_DONORS", self.t.get("source_root", "donors"))
        self.source_root = src if os.path.isabs(src) else os.path.join(REPO, src)
        self.source_root = os.path.normpath(self.source_root)
        if not os.path.isdir(self.source_root):
            log.die(f"Donor directory does not exist: {self.source_root}")

        self.derived_root = DERIVED_DIR

        self.work = workdir or os.path.join(REPO, "build",
                                            f"{self.t['name']}-{time.strftime('%Y%m%d-%H%M%S')}")
        self.work = os.path.abspath(self.work)
        os.makedirs(self.work, exist_ok=True)
        self._ssh = None   # Injected after core.ramdisk establishes a session
        self._source_mounts = {}
        self._input_hashes = {}
        self._device_system_verified = False

    # ---- Path resolution ----
    def src(self, rel):
        """Absolute path inside the local donor directory."""
        p = os.path.join(self.source_root, rel)
        return p

    def req(self, rel):
        """Resolve a required donor path; fail if it does not exist."""
        p = self.src(rel)
        if not os.path.exists(p):
            log.die(f"Missing required file: {p}")
        return p

    def tool(self, key):
        rel = self.t["tools"].get(key)
        if rel is None:
            log.die(f"Tool is not declared by the target: {key}")
        if isinstance(rel, (list, tuple)):
            for candidate in rel:
                path = os.path.join(REPO, candidate)
                if os.path.exists(path):
                    return path
            log.die(f"Missing tool {key}: {', '.join(rel)}")
        return self.local(rel)

    def local(self, rel):
        """Path to a source file or tool in this repository."""
        path = os.path.join(REPO, rel)
        if not os.path.exists(path):
            log.die(f"Missing local file: {path}")
        return path

    def ensure_derived(self):
        """Generate missing derived inputs from local IPSWs."""
        sys.path.insert(0, os.path.join(REPO, "tools"))
        try:
            import extract_ipsw
        finally:
            sys.path.pop(0)
        native = self.t.get("native_profile", "n56")
        outputs = extract_ipsw.native_outputs(native) + extract_ipsw.SHARED_OUTPUTS
        if all(os.path.exists(os.path.join(DERIVED_DIR, rel)) for rel in outputs):
            return
        log.log("Generating build inputs from IPSWs…")
        rootfs_entry = self.t.get("source_profiles", {}).get(native, {}).get("rootfs_entry")
        extract_ipsw.generate(self.ipsw_input(native), self.ipsw_input("n66"),
                              self.ipsw_input("j96"), native_board=native,
                              rootfs_entry=rootfs_entry)

    def derived(self, key):
        rel = self.t["derived"].get(key)
        if rel is None:
            log.die(f"Derived input is not declared by the target: {key}")
        path = os.path.join(DERIVED_DIR, rel)
        if key in ("ibss_src", "ibec_dec"):
            if not os.path.exists(path):
                self._decrypt_iboot()
            return path
        self.ensure_derived()
        return path

    def _decrypt_iboot(self):
        sys.path.insert(0, os.path.join(REPO, "tools"))
        try:
            import extract_ipsw
        finally:
            sys.path.pop(0)
        log.log("Decrypting iBSS/iBEC: the device must be in DFU…")
        native = self.t.get("native_profile", "n56")
        extract_ipsw.decrypt_iboot(self.ipsw_input(native), self.tool("gaster"),
                                   self.tool("iBoot64Patcher"),
                                   board=self.t.get("device", {}).get("board", native))

    def donor(self, key):
        if key in self.t.get("derived", {}):
            return self.derived(key)
        rel = self.t["donors"].get(key)
        if rel is None:
            log.die(f"Donor is not declared by the target: {key}")
        return self.req(rel)

    def im4m(self):
        """This device's IM4M (state/IM4M.bin).

        The onboard APTicket changes after a restore. Run extract-im4m before personalizing components with -M.
        """
        local = os.path.join(STATE_DIR, "IM4M.bin")
        if not os.path.exists(local):
            log.die("Missing state/IM4M.bin: run extract-im4m first")
        return local

    def im4m_is_fresh(self):
        return os.path.exists(os.path.join(STATE_DIR, "IM4M.bin"))

    def wk(self, name):
        """Path to a generated output in the working directory."""
        return os.path.join(self.work, name)

    def set_ipsw_input(self, kind, path):
        self.t.setdefault("ipsw_inputs", {})[kind] = os.path.abspath(path)

    def ipsw_input(self, kind):
        path = self.t.get("ipsw_inputs", {}).get(kind)
        if not path:
            name = self.t.get("source_profiles", {}).get(kind, {}).get("ipsw")
            if not name:
                log.die(f"{kind} profile does not declare an IPSW filename")
            path = os.path.join(IPSW_DIR, name)
        if not os.path.isfile(path):
            log.die(f"Cannot find {kind} IPSW: {path}")
        expected = self.t.get("source_profiles", {}).get(kind, {})
        with zipfile.ZipFile(path) as archive:
            try:
                restore = plistlib.loads(archive.read("Restore.plist"))
            except KeyError:
                log.die(f"{kind} input is not a valid IPSW: {path}")
        build = restore.get("ProductBuildVersion")
        if build is None:
            build = restore.get("BuildIdentities", [{}])[0].get("Info", {}).get("BuildNumber")
        if expected.get("build") and build != expected["build"]:
            log.die(f"{kind} IPSW build is {build}; this profile requires {expected['build']}")
        self._record_input_hash(kind + "_ipsw", path)
        return path

    def _record_input_hash(self, name, path):
        if name in self._input_hashes:
            return self._input_hashes[name]
        digest = hashlib.sha256()
        with open(path, "rb") as stream:
            for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
                digest.update(chunk)
        value = digest.hexdigest()
        self._input_hashes[name] = value
        with open(self.wk("input-manifest.json"), "w") as out:
            json.dump(self._input_hashes, out, indent=2, sort_keys=True)
            out.write("\n")
        return value

    def rootfs_dmg(self, kind):
        """Use a cached rootfs DMG, or extract it from the IPSW into ipsw/cache/."""
        entry = self.t.get("source_profiles", {}).get(kind, {}).get("rootfs_entry")
        if not entry:
            log.die(f"{kind} profile does not declare rootfs_entry")
        donor_key = kind + "_rootfs_dmg"
        directory = os.path.join(IPSW_DIR, "cache")
        path = os.path.join(directory, os.path.basename(entry))
        if os.path.exists(path):
            self._record_input_hash(donor_key, path)
            return path
        os.makedirs(directory, exist_ok=True)
        ipsw = self.ipsw_input(kind)
        with zipfile.ZipFile(ipsw) as archive:
            try:
                info = archive.getinfo(entry)
            except KeyError:
                log.die(f"{kind} IPSW does not contain {entry}")
            log.log(f"Extracting rootfs DMG from {kind} IPSW…")
            partial = path + ".part"
            with archive.open(info) as source, open(partial, "wb") as dest:
                shutil.copyfileobj(source, dest, 8 * 1024 * 1024)
            os.replace(partial, path)
        self._record_input_hash(donor_key, path)
        return path

    def verify_device_system(self, ssh):
        if self._device_system_verified:
            return
        ssh.mount(self.t["mounts"]["system12"], "/mnt1", ro=True)
        path = "/mnt1/System/Library/CoreServices/SystemVersion.plist"
        try:
            version = plistlib.loads(ssh.sh(f'cat "{path}"'))
        except Exception as exc:
            log.die(f"Cannot read the SystemA version: {exc}")
        actual = version.get("ProductBuildVersion")
        native = self.t.get("native_profile", "n56")
        expected = self.t.get("source_profiles", {}).get(native, {}).get("build")
        if expected and actual != expected:
            log.die(f"SystemA build is {actual}; this profile requires {expected}")
        self._device_system_verified = True

    def mount_rootfs(self, kind):
        if kind in self._source_mounts:
            return self._source_mounts[kind]
        dmg = self.rootfs_dmg(kind)
        mountpoint = self.wk(os.path.join("mounts", kind))
        os.makedirs(mountpoint, exist_ok=True)
        subprocess.run(["hdiutil", "attach", "-readonly", "-owners", "on", "-nobrowse",
                        "-mountpoint", mountpoint, dmg], check=True, capture_output=True)
        mounts = subprocess.run(["/sbin/mount"], check=True, capture_output=True, text=True).stdout
        line = next((line for line in mounts.splitlines() if f" on {mountpoint} " in line), "")
        if not line or "noowners" in line:
            subprocess.run(["hdiutil", "detach", mountpoint], capture_output=True)
            log.die(f"{kind} rootfs is not mounted with ownership enabled")
        version_path = os.path.join(mountpoint, "System/Library/CoreServices/SystemVersion.plist")
        version = plistlib.load(open(version_path, "rb"))
        actual = version.get("ProductBuildVersion")
        expected = self.t.get("source_profiles", {}).get(kind, {}).get("build")
        if expected and actual != expected:
            subprocess.run(["hdiutil", "detach", mountpoint], capture_output=True)
            log.die(f"{kind} rootfs build is {actual}; this profile requires {expected}")
        self._source_mounts[kind] = mountpoint
        return mountpoint

    def close_source_mounts(self):
        for mountpoint in reversed(list(self._source_mounts.values())):
            subprocess.run(["hdiutil", "detach", mountpoint], capture_output=True)
        self._source_mounts.clear()

    # ---- SSH (available after the ramdisk session is injected)----
    @property
    def ssh(self):
        if self._ssh is None:
            log.die("No ramdisk SSH session; run the ramdisk stage first")
        return self._ssh
