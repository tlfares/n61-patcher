"""Download and verify the core bootstrap and Cydia packages used by checkra1n Loader."""
import hashlib
from pathlib import Path
import shutil
import subprocess
import urllib.request

from core import log
from core.context import IPSW_DIR

BASE = "https://assets.checkra.in/loader/ios"
CORE = f"{BASE}/core/3bda4c4ddb50d7c89eec6260f42f7ba91535de64/strap.tar.lzma"
CYDIA = f"{BASE}/cydia/0d1e4d2daec4c4b528e918df6c20281d24a90950/cydia.tar.lzma"
STATUS = f"{BASE}/cydia/0d1e4d2daec4c4b528e918df6c20281d24a90950/cydia.status"
ARCHIVES = (
    (CORE, "d18b3fdd82e3b9f188ccff1a3fcb9a67eb1eda2c42164f109cff0c1973f01708"),
    (CYDIA, "400abcb7cf3586ae6ebbba17eeea2b2b06c35523383fa45c2d7bcad19f6b0712"),
)
PENDING = "/.n56-cydia-pending"


def fetch(url, digest=None):
    path = Path(IPSW_DIR) / "cache/cydia" / url.rsplit("/", 1)[1]
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        log.log(f"Downloading {path.name}...")
        partial = path.with_suffix(path.suffix + ".part")
        with urllib.request.urlopen(url, timeout=120) as source, partial.open("wb") as dest:
            shutil.copyfileobj(source, dest)
        partial.replace(path)
    if digest and hashlib.sha256(path.read_bytes()).hexdigest() != digest:
        path.unlink()
        log.die(f"{path.name} failed verification and was removed")
    return path


def install(ctx):
    ssh = ctx.ssh
    for url, digest in ARCHIVES:
        archive = fetch(url, digest)
        log.log(f"Extracting {archive.name} into SystemB...")
        lzma = subprocess.Popen(["/usr/bin/bsdtar", "-cf", "-", f"@{archive}"], stdout=subprocess.PIPE)
        consumer = subprocess.Popen(ssh.ssh_argv() + ["/usr/bin/tar --numeric-owner -xpf - -C /mnt6"],
                                    stdin=lzma.stdout, stderr=subprocess.PIPE)
        lzma.stdout.close()
        _, err = consumer.communicate()
        if lzma.wait() or consumer.returncode:
            log.die(f"Failed to extract {archive.name}\n{(err or b'').decode(errors='replace')}")
    status = fetch(STATUS)
    # The core archive's final stanza may have no empty trailing line.
    # Keep the first Cydia Package field in its own Debian control stanza.
    core_status = ssh.sh("cat /mnt6/Library/dpkg/status")
    combined = core_status.rstrip() + b"\n\n" + status.read_bytes().lstrip()
    ssh.sh("cat > /mnt6/Library/dpkg/status", data=combined)
    ssh.sh(f"touch /mnt6{PENDING}")
    ssh.sync()
