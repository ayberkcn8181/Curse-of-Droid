"""Fresh read-only observations for bound installation plans. No writes here."""

from __future__ import annotations

import re
import subprocess

from ..device.profile import from_props
from ..transport.adb import Adb, parse_devices as adb_devices, parse_getprop
from ..transport.fastboot import Fastboot, parse_devices as fastboot_devices
from .artifacts import ArtifactRequirement
from .guard import FileUse, LOGICAL, base_name, command_operation
from .image_size import image_extent
from .plan import InstallTarget, Plan


class DeviceCheckError(Exception):
    pass


def required_risk(tool: str, args: list[str], use: FileUse | None) -> str:
    if use and use.operation in {"flash", "sideload"}:
        return "system-write"
    if tool == "fastboot" and command_operation(tool, args) in {"-w", "erase", "format"}:
        return "data-loss"
    return ""


def execution_blocker(plan: Plan) -> str:
    """Static capability policy; previews/dry runs may still describe a blocked plan."""
    if not plan.target:
        return ""
    for step in plan.steps:
        for command in step.commands:
            if command.tool == "adb" and command.args[:1] == ["sideload"]:
                return ("Automatic sideload is blocked: the standard sideload transport cannot provide fresh "
                        "identity/bootloader properties. A reviewed recovery identity protocol is required.")
            if command.tool == "fastboot" and command.args[:1] == ["-w"]:
                return ("Aggregate fastboot -w is blocked: its implicit userdata/cache/metadata operations "
                        "need a reviewed device-specific wipe workflow.")
            if command.args and (command.args[0].startswith("-") and command.args[0] != "-w"
                                 or command.args[0] in {"set_active", "oem", "flashing", "continue"}):
                return "Bound installation plans cannot override slots/options or run vendor/unlock commands."
    if plan.target.ab not in {"yes", "no"} or plan.target.ab == "yes" and plan.target.current_slot not in {"a", "b"}:
        return "Bound installation plans require a captured A/B layout and active slot."
    return ""


class DeviceGate:
    def __init__(self, adb: Adb, fastboot: Fastboot, target: InstallTarget):
        self.adb, self.fastboot, self.target = adb, fastboot, target
        # Inventory reads must list all transports; probes always select the bound serial.
        self.adb_inventory = Adb(adb.exe, adb.runner)
        self.fb_inventory = Fastboot(fastboot.exe, fastboot.runner)

    def _check_selectors(self):
        if self.adb.serial != self.target.serial or self.fastboot.serial != self.target.serial:
            raise DeviceCheckError("transport selector changed since planning")

    def _read(self, tool, *args):
        self._check_selectors()
        try:
            result = tool.run(*args, timeout=10)
        except (OSError, subprocess.SubprocessError):
            raise DeviceCheckError("read-only device probe failed; check USB access and platform-tools") from None
        self._check_selectors()
        if (not result.ok or len(result.stdout) + len(result.stderr) > 1 << 20
                or re.search(r"(?:^|\n)\s*(?:(?:fastboot|adb):\s*)?(?:\(bootloader\)\s*)?(?:FAILED\b|error:)",
                             result.stdout + "\n" + result.stderr, re.I)):
            raise DeviceCheckError("read-only device probe failed or returned unsupported output")
        return result

    def _var(self, name: str) -> str:
        result = self._read(self.fastboot, "getvar", name)
        values = []
        for raw in (result.stdout + "\n" + result.stderr).splitlines():
            line = re.sub(r"^\(bootloader\)\s*", "", raw.strip())
            if line.startswith(name + ":"):
                values.append(line[len(name) + 1:].strip())
        if len(values) != 1 or not values[0] or len(values[0]) > 256:
            raise DeviceCheckError("required fastboot variable is missing, duplicate or malformed")
        return values[0]

    def _bool(self, name: str) -> bool:
        value = self._var(name).lower()
        if value not in {"yes", "no", "true", "false", "1", "0"}:
            raise DeviceCheckError("required fastboot state is unknown")
        return value in {"yes", "true", "1"}

    def _number(self, name: str, *, positive=True) -> int:
        value = self._var(name)
        if not re.fullmatch(r"(?:0[xX][0-9a-fA-F]+|[0-9]+)", value):
            raise DeviceCheckError("required fastboot size/count is malformed")
        number = int(value, 16 if value.lower().startswith("0x") else 10)
        if number > (1 << 63) - 1 or number < (1 if positive else 0):
            raise DeviceCheckError("required fastboot size/count is outside the supported range")
        return number

    def _inventory(self) -> tuple[str, str] | None:
        a = self._read(self.adb_inventory, "devices", "-l")
        f = self._read(self.fb_inventory, "devices")
        matches = [("adb", d.state) for d in adb_devices(a.stdout) if d.serial == self.target.serial]
        matches += [("fastboot", mode) for serial, mode in fastboot_devices(f.stdout) if serial == self.target.serial]
        if len(matches) > 1:
            raise DeviceCheckError("selected serial has ambiguous or duplicate transports")
        return matches[0] if matches else None

    def mode(self) -> str:
        current = self._inventory()
        if current is None:
            return ""
        protocol, state = current
        if protocol == "adb":
            if state not in {"device", "recovery", "sideload"}:
                raise DeviceCheckError("selected ADB device is unauthorized, offline or in an unknown state")
            return "android" if state == "device" else state
        if state not in {"fastboot", "fastbootd"}:
            raise DeviceCheckError("selected fastboot transport has an unknown mode")
        return "fastbootd" if self._bool("is-userspace") else "fastboot"

    def _slots(self):
        count = self._number("slot-count", positive=False)
        if count not in {0, 1, 2} or self.target.ab not in {"yes", "no"}:
            raise DeviceCheckError("slot layout is unknown or unsupported")
        if (count == 2) != (self.target.ab == "yes"):
            raise DeviceCheckError("slot layout changed since planning")
        if count == 2 and (self.target.current_slot not in {"a", "b"}
                           or self._var("current-slot") != self.target.current_slot):
            raise DeviceCheckError("active slot changed or is unknown")

    def _fastboot_identity(self):
        if self._var("serialno") != self.target.serial:
            raise DeviceCheckError("reported serial does not match the installation target")
        if self._var("product").lower() not in {d.lower() for d in self.target.codenames}:
            raise DeviceCheckError("device product does not match the installation target")
        if not self._bool("unlocked"):
            raise DeviceCheckError("bootloader is no longer confirmed unlocked")
        self._slots()

    def _adb_identity(self):
        result = self._read(self.adb, "shell", "getprop")
        keys = re.findall(r"^\[([^\]]+)\]:", result.stdout, re.M)
        if len(keys) != len(set(keys)):
            raise DeviceCheckError("duplicate device properties")
        properties = parse_getprop(result.stdout)
        serials = [properties[k] for k in ("ro.serialno", "ro.boot.serialno") if properties.get(k)]
        if not serials or any(s != self.target.serial for s in serials):
            raise DeviceCheckError("current hardware serial is unknown or does not match the target")
        # Full getprop output alone does not prove A-only: require an explicit
        # negative A/B assertion rather than the profile display's SDK fallback.
        if self.target.ab == "no" and (properties.get("ro.boot.slot_suffix")
                or properties.get("ro.build.ab_update", "").lower() not in {"false", "0", "no"}):
            raise DeviceCheckError("current A-only layout is not explicitly confirmed")
        lock_states = [properties[k] for k in ("ro.userlock", "ro.boot.vbmeta.device_state") if properties.get(k)]
        if any(value != "unlocked" for value in lock_states):
            raise DeviceCheckError("current bootloader properties conflict or report locked")
        if properties.get("ro.boot.flash.locked") not in (None, "0", "false", "no"):
            raise DeviceCheckError("current bootloader lock flag is unknown or locked")
        if not lock_states and "ro.boot.flash.locked" not in properties:
            raise DeviceCheckError("current bootloader lock state is not explicit")
        sdk = properties.get("ro.build.version.sdk", "")
        if sdk and (not sdk.isascii() or not sdk.isdigit() or len(sdk) > 4):
            raise DeviceCheckError("current device SDK property is malformed")
        try:
            profile = from_props(properties)
        except (ValueError, OverflowError):
            raise DeviceCheckError("current device properties are malformed") from None
        if not {d.lower() for d in profile.codenames}.intersection(d.lower() for d in self.target.codenames):
            raise DeviceCheckError("current device codename does not match the target")
        if profile.bootloader_unlocked != "yes":
            raise DeviceCheckError("current bootloader state is unknown or locked")
        if profile.ab != self.target.ab or profile.ab == "unknown":
            raise DeviceCheckError("current A/B layout is unknown or changed")
        if profile.ab == "yes" and profile.current_slot != self.target.current_slot:
            raise DeviceCheckError("current active slot changed")
        if self.target.dynamic_partitions in {"yes", "no"} and profile.dynamic_partitions != self.target.dynamic_partitions:
            raise DeviceCheckError("current dynamic partition layout is unknown or changed")

    def _partition(self, name: str, mode: str) -> tuple[str, int, bool, bool]:
        base = base_name(name)
        slotted = self._bool("has-slot:" + base)
        suffix = name[len(base):]
        if slotted:
            if self.target.ab != "yes" or self.target.current_slot not in {"a", "b"}:
                raise DeviceCheckError("partition needs a known active slot")
            if suffix and suffix != "_" + self.target.current_slot:
                raise DeviceCheckError("partition would write a different slot")
            resolved = base + "_" + self.target.current_slot
        else:
            if suffix:
                raise DeviceCheckError("slot suffix conflicts with the reported physical partition")
            resolved = base
        logical = self._bool("is-logical:" + resolved)
        if logical and (mode != "fastbootd" or self.target.dynamic_partitions != "yes"):
            raise DeviceCheckError("logical partition requires confirmed fastbootd and dynamic layout")
        if base in LOGICAL and logical != (self.target.dynamic_partitions == "yes"):
            raise DeviceCheckError("target partition layout changed since planning")
        if mode == "fastbootd" and self.target.dynamic_partitions == "no":
            raise DeviceCheckError("fastbootd conflicts with the captured legacy layout")
        return resolved, self._number("partition-size:" + resolved), logical, slotted

    def before_manual(self):
        mode = self.mode()
        if mode in {"android", "recovery"}:
            self.before_command("adb", ["get-state"], None, None)
        elif mode in {"fastboot", "fastbootd"}:
            self.before_command("fastboot", ["getvar", "product"], None, None)
        else:
            raise DeviceCheckError("manual installation step needs a fresh device identity")

    def before_command(self, tool: str, args: list[str], use: FileUse | None,
                       artifact: ArtifactRequirement | None) -> list[str]:
        """Return a command with its checked partition resolved to the captured slot."""
        self._check_selectors()
        mode = self.mode()
        if tool == "adb":
            if mode not in {"android", "recovery"}:
                raise DeviceCheckError("current ADB mode cannot provide a fresh installation identity")
            self._adb_identity()
            if self.mode() != mode:
                raise DeviceCheckError("device mode changed during preflight")
            return args
        if mode not in {"fastboot", "fastbootd"}:
            raise DeviceCheckError("selected device is not in a confirmed fastboot mode")
        self._fastboot_identity()
        resolved_args = list(args)
        partition_snapshot = None
        download_limit = None
        operation = args[0].split(":")[0]
        if use and use.operation == "boot":
            if mode != "fastboot":
                raise DeviceCheckError("temporary boot requires bootloader fastboot")
            extent = image_extent(artifact.path)
            download_limit = self._number("max-download-size")
            if extent.sparse or extent.file_bytes > download_limit:
                raise DeviceCheckError("boot image is sparse or exceeds the download limit")
        elif operation in {"flash", "erase", "format"}:
            partition = use.partition if use else args[1]
            partition_snapshot = self._partition(partition, mode)
            resolved, capacity, _, _ = partition_snapshot
            if use:
                extent = image_extent(artifact.path)
                if extent.expanded_bytes > capacity:
                    raise DeviceCheckError("expanded image exceeds the current target partition capacity")
            resolved_args[1] = resolved
        # Do not cache authorization between commands or transitions. Re-read critical
        # identity/state after capacity sizing; a change while probing stops the write.
        if partition_snapshot is not None and self._partition(partition, mode) != partition_snapshot:
            raise DeviceCheckError("partition capacity or layout changed during preflight")
        if download_limit is not None and self._number("max-download-size") != download_limit:
            raise DeviceCheckError("download limit changed during preflight")
        self._fastboot_identity()
        if self.mode() != mode:
            raise DeviceCheckError("device mode changed during preflight")
        return resolved_args
