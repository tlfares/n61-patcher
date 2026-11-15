"""按名称管理独立系统卷，记录实际安装布局。"""
import json
from pathlib import Path
import re

from . import log
from .apfs import Apfs, NAME_OFF
from .volume_inventory import inventory


def volume_name(volume):
    return volume[2][NAME_OFF:NAME_OFF + 256].split(b"\0")[0].decode()


def named_volume(volumes, name):
    matches = [v for v in volumes if volume_name(v) == name]
    if len(matches) > 1:
        log.die(f"存在多个 {name} 卷")
    return matches[0] if matches else None


def bind_volumes(ctx, system, data):
    minimum = ctx.t["volumes"].get("min_slice", 1)
    if system is None or data is None:
        log.die("请先运行 volumes 读取布局；离线构建可同时指定 --system 和 --data")
    if not minimum <= system <= 100 or not minimum <= data <= 100 or system == data:
        log.die(f"System/Data 需要不同的卷号，范围为 s{minimum}–s100")
    ctx.t["mounts"].update(system_b=system, data_b=data)
    ctx.t["root_part"] = system
    args = re.sub(r"rd=disk0s1s\d+\s*", "", ctx.t["bootargs"]).strip()
    ctx.t["bootargs"] = f"rd=disk0s1s{system} {args}"


def restore_layout(ctx):
    path = Path(ctx.wk("layout.json"))
    if path.is_file():
        layout = json.loads(path.read_text())
        if layout["target"] != ctx.t["name"] or layout["build"] != ctx.t["build"]:
            log.die("工作目录属于另一系统目标，请更换 --workdir")
        bind_volumes(ctx, layout["system"], layout["data"])


class IndependentInstallation:
    def __init__(self, ctx):
        self.ctx = ctx
        self.mounted = []

    @property
    def session(self):
        return self.ctx.ssh

    @property
    def encrypted_data(self):
        return self.ctx.t.get("data_protection", "encrypted") == "encrypted"

    def mount(self, slice_no, mountpoint, ro=False, protected=False):
        self.session.mount_install_volume(slice_no, mountpoint, ro=ro, protected=protected)
        if mountpoint not in self.mounted:
            self.mounted.append(mountpoint)

    def prepare(self, create=False):
        self.session.verify_ramdisk()
        if not getattr(self.ctx, "donor_dir", None):
            self.mount(self.ctx.t["mounts"]["system12"], "/mnt1", ro=True)
            mounts = self.session.sh("/sbin/mount").decode()
            if not any("disk0s1s1 on /mnt1 " in line and "read-only" in line for line in mounts.splitlines()):
                log.die("SystemA 需要只读挂载")
        self.ctx.verify_device_system(self.session)
        if create and self.encrypted_data:
            self.session.require_sep()
        self.select_volumes(create=create)

    def select_volumes(self, create=False):
        if getattr(self.ctx, "slot", None):
            return self.select_slot_volumes()
        config = self.ctx.t["volumes"]
        apfs = Apfs(self.ctx)
        volumes = apfs.volumes()
        selected = {kind: named_volume(volumes, name) for kind, name in config["names"].items()}
        replace_build = config.get("replace_build")
        if replace_build:
            pair = tuple(selected[kind][0] if selected[kind] else None for kind in ("system", "data"))
            if pair != tuple(config["replace_pair"]):
                log.die("Expected the existing iPhone 6 SystemB/DataB pair on s4/s5")
        for volume in selected.values():
            if volume and volume[0] < config["min_slice"]:
                log.die(f"{volume_name(volume)} 位于保留卷 s{volume[0]}")
        # 旧的独立卷路径不深度识别：不挂载加密的 DataB（卷名由配置约定，类型未知时只校验名字）。
        infos = inventory(self.ctx, self.session, volumes)
        system = selected["system"]
        required_system = config.get("require_existing_system")
        if required_system is not None:
            if system is None or system[0] != required_system:
                log.die("Recovery requires the existing iOS 14 SystemB on s4")
            if not any(v.slice == required_system and v.build == self.ctx.t["build"] for v in infos):
                log.die("Recovery requires iOS 14.8 to have already been copied to SystemB")
        if system:
            info = next(v for v in infos if v.slice == system[0])
            # 刚由 volumes 建好、还没写系统的卷读不到版本文件，识别为 Unknown，按卷名认。
            if info.kind not in ("System", "Unknown") or info.encrypted:
                log.die(f"{info.name} 需要是未加密的系统卷")
            if info.build and info.build != self.ctx.t["build"] and not (create and info.build == replace_build):
                log.die(f"{info.name} 为 iOS {info.version} ({info.build})，目标为 {self.ctx.t['os_version']}")
        data = selected["data"]
        if data:
            info = next(v for v in infos if v.slice == data[0])
            if info.kind not in ("Data", "Unknown") or info.build and info.build != self.ctx.t["build"] and not (create and info.build == replace_build):
                log.die(f"{info.name} 与目标系统的数据卷不符")
        missing = sum(volume is None for volume in selected.values())
        limit = apfs.volume_capacity()
        if max((v[0] for v in volumes), default=0) + missing > limit:
            log.die("APFS 容器末尾没有足够的卷槽位")
        for kind, volume in selected.items():
            if volume is None:
                name = config["names"][kind]
                if not create:
                    log.die(f"缺少 {name}，请先执行 volumes")
                apfs.append_volume(name, encrypted=kind == "data" and self.encrypted_data)
        volumes = apfs.volumes()
        selected = {kind: named_volume(volumes, name) for kind, name in config["names"].items()}
        if any(v is None for v in selected.values()):
            log.die("独立卷创建未完成")
        encrypted = apfs.enc_state(selected["data"][2]) == "encrypted"
        if encrypted != self.encrypted_data:
            mode = "encrypted" if self.encrypted_data else "none"
            log.die(f'{config["names"]["data"]} 需要使用 {mode} 保护模式')
        bind_volumes(self.ctx, selected["system"][0], selected["data"][0])
        if create and replace_build:
            current = next(v for v in infos if v.slice == system[0]).build
            if current != self.ctx.t["build"]:
                self.reset_legacy_pair(legacy_identified=current == replace_build)
        self.save_layout()
        return selected["system"][0], selected["data"][0]

    def reset_legacy_pair(self, legacy_identified):
        """Clear the verified legacy pair, with both mounts checked before deleting."""
        self.mount_system()
        self.mount_data()
        for index, mountpoint in ((4, "/mnt6"), (5, "/mnt7")):
            self.session.sh(f'/sbin/mount | grep -q "^/dev/disk0s1s{index} on {mountpoint} "')
        marker = "/mnt6/.n61-ios14-replacement"
        if legacy_identified:
            self.session.sh(f"touch {marker} && sync")
        else:
            self.session.sh(f"test -f {marker}")
        # Some data vaults cannot be removed by the ramdisk. Move their
        # containing tree out of the active data paths on the same volume.
        quarantine = "/mnt7/.n61-ios13-quarantine"
        self.session.sh(
            f'mkdir -p "{quarantine}" || exit 1; '
            'for path in /mnt7/.[!.]* /mnt7/..?* /mnt7/*; do '
            f'case "$path" in /mnt7/keybags|/mnt7/.n61-ios13-MobileAsset|{quarantine}) continue;; esac; '
            '/bin/rm -rf "$path" && continue; '
            f'dest="{quarantine}/${{path##*/}}"; '
            'test ! -e "$dest" && test ! -L "$dest" && '
            '/bin/mv "$path" "$dest" && test ! -e "$path" && test ! -L "$path" || exit 1; '
            'done',
            timeout=3600,
        )
        self.session.sh(
            'for path in /mnt6/.[!.]* /mnt6/..?* /mnt6/*; do '
            f'case "$path" in {marker}) continue;; esac; '
            '/bin/rm -rf "$path" || exit 1; done',
            timeout=3600,
        )
        self.session.sync()

    def select_slot_volumes(self):
        """宗卷槽位模式：卷号由槽位记录给出，卷必须已存在（由宗卷页面先创建并格式化）。"""
        slot = self.ctx.slot
        apfs = Apfs(self.ctx)
        present = {v[0]: v for v in apfs.volumes()}
        for index, label in ((slot["system"], "System"), (slot["data"], "Data")):
            if index not in present:
                log.die(f"s{index} 不存在：请先在宗卷页面为 {slot['version']} {label} 分配并创建分区")
        encrypted = apfs.enc_state(present[slot["data"]][2]) == "encrypted"
        if encrypted != self.encrypted_data:
            log.die(f"s{slot['data']} 的保护模式与目标不符")
        # 非原机分区（s1、s2 之外）的卷名必须与槽位一致，编号对上但卷不是我们的就拒绝。
        from .slots_device import slot_volume_name
        for index, kind in ((slot["system"], "Sys"), (slot["data"], "Data")):
            if index in (1, 2):
                continue
            name = present[index][2][NAME_OFF:NAME_OFF + 256].split(b"\0")[0].decode()
            expected = slot_volume_name(slot["version"], kind)
            if name != expected:
                log.die(f"s{index} 的卷名为 {name}，与槽位 {expected} 不符；拒绝使用")
        # 槽位的权限由 core/slots.py 管理；这里不再使用目标的保留卷下限。
        self.ctx.t["volumes"]["min_slice"] = 1
        bind_volumes(self.ctx, slot["system"], slot["data"])
        self.save_layout()
        return slot["system"], slot["data"]

    def mount_system(self):
        self.mount(self.ctx.t["mounts"]["system_b"], "/mnt6")

    def mount_data(self):
        if self.encrypted_data:
            self.session.require_sep()
        self.mount(self.ctx.t["mounts"]["data_b"], "/mnt7", protected=self.encrypted_data)

    def save_layout(self):
        mounts = self.ctx.t["mounts"]
        layout = dict(target=self.ctx.t["name"], build=self.ctx.t["build"],
                      system=mounts["system_b"], data=mounts["data_b"])
        Path(self.ctx.wk("layout.json")).write_text(json.dumps(layout, indent=2) + "\n")

    def close(self):
        while self.mounted:
            mountpoint = self.mounted[-1]
            self.session.sh(f"/sbin/umount {mountpoint}")
            self.mounted.pop()
