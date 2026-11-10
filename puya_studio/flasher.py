"""Programming: SWD through a debug probe (pyOCD + the Puya DFP flash algorithms) and the serial boot loader.

Which probe to use (researched, not yet tried on every chip - see the README hardware checklist):
  * CMSIS-DAP / DAPLink probes: best supported by pyOCD, no driver on Linux (udev rule) or Windows (WinUSB / HID).
  * ST-Link V2 clones: work with pyOCD over libusb; on Windows the WinUSB driver (Zadig) is needed.
  * Serial boot loader (USB-serial adapter): PY32F030 / PY32F003 only. The PY32F002B has NO boot loader: SWD only.

Safety rules in this module:
  * pyOCD's "auto_unlock" is switched off: a read-protected chip is never mass-erased behind your back.
  * Option bytes are only written through `write_option_words`, which the GUI calls after `option_bytes.plan()`
    and a confirmation (typed word for anything that can lock the chip).
"""
import glob
import os
import re
import time

from . import option_bytes, serial_isp, toolchain

PACK_NAME = "Puya.PY32F0xx_DFP.1.2.0-trimmed.pack"
FLASH_KEYS = (0x45670123, 0xCDEF89AB)
OPT_KEYS = (0x08192A3B, 0x4C5D6E7F)
OPT_TRIGGER = 0x40022080            # RM 4.4.2: any 32-bit write here starts the option byte write
UDEV_RULES = """# Puya Studio: debug probes without root (put into /etc/udev/rules.d/49-puya-probes.rules, then: sudo udevadm control --reload && replug)
# ST-Link V2 / V2-1 / V3
SUBSYSTEM=="usb", ATTR{idVendor}=="0483", ATTR{idProduct}=="3748", MODE="0666"
SUBSYSTEM=="usb", ATTR{idVendor}=="0483", ATTR{idProduct}=="374b", MODE="0666"
SUBSYSTEM=="usb", ATTR{idVendor}=="0483", ATTR{idProduct}=="374d", MODE="0666"
SUBSYSTEM=="usb", ATTR{idVendor}=="0483", ATTR{idProduct}=="374e", MODE="0666"
SUBSYSTEM=="usb", ATTR{idVendor}=="0483", ATTR{idProduct}=="374f", MODE="0666"
SUBSYSTEM=="usb", ATTR{idVendor}=="0483", ATTR{idProduct}=="3752", MODE="0666"
SUBSYSTEM=="usb", ATTR{idVendor}=="0483", ATTR{idProduct}=="3753", MODE="0666"
# DAPLink / CMSIS-DAP (ARM mbed, Raspberry Pi debugprobe, many clones)
SUBSYSTEM=="usb", ATTR{idVendor}=="0d28", ATTR{idProduct}=="0204", MODE="0666"
SUBSYSTEM=="usb", ATTR{idVendor}=="2e8a", ATTR{idProduct}=="000c", MODE="0666"
SUBSYSTEM=="usb", ATTR{idVendor}=="c251", ATTR{idProduct}=="f001", MODE="0666"
SUBSYSTEM=="hidraw", ATTRS{idVendor}=="0d28", MODE="0666"
SUBSYSTEM=="hidraw", ATTRS{idVendor}=="c251", MODE="0666"
# USB-serial adapters for the boot loader: add yourself to the dialout group instead:  sudo usermod -aG dialout $USER
"""


class ProgrammerError(Exception):
    pass


# ------------------------------------------------------------------------------------ data files
def data_dir():
    return os.path.join(toolchain.app_dir(), "puya_studio", "data") if getattr(__import__("sys"), "_MEIPASS", None) else \
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


def pack_path():
    return os.path.join(data_dir(), PACK_NAME)


def target_name(chip, flash_kb):
    """pyOCD target (device in the Puya DFP) for a chip and flash size."""
    if chip.id == "py32f002b":
        return "py32f002bx5"
    size = {8: "4", 16: "4", 32: "6", 48: "7", 64: "8"}[flash_kb]        # 8 KB parts use the 16 KB algorithm
    if chip.id == "py32f003" and size == "7":
        size = "6"
    return f"{chip.id}x{size}"


# ------------------------------------------------------------------------------------ probes and ports
def probe_kind(vid_pid_or_name):
    s = (vid_pid_or_name or "").lower()
    if "stlink" in s or "st-link" in s or s.startswith("0483"):
        return "ST-Link"
    if "daplink" in s or "cmsis-dap" in s or "debugprobe" in s:
        return "CMSIS-DAP"
    if "j-link" in s or "jlink" in s:
        return "J-Link"
    return "probe"


def list_probes():
    """[{uid, name, kind}] of connected debug probes (needs pyocd; returns [] when it is not installed)."""
    try:
        from pyocd.probe.aggregator import DebugProbeAggregator
        probes = DebugProbeAggregator.get_all_connected_probes(blocking=False)
    except Exception:
        return []
    out = []
    for p in probes:
        name = f"{getattr(p, 'vendor_name', '')} {getattr(p, 'product_name', '')}".strip()
        out.append({"uid": p.unique_id, "name": name or p.description, "kind": probe_kind(name or p.description)})
    return out


def list_serial_ports():
    try:
        from serial.tools import list_ports
        return [{"device": p.device, "name": f"{p.device}  {p.description}"} for p in list_ports.comports()]
    except Exception:
        return []


# ------------------------------------------------------------------------------------ register access
class Access:
    """Word access to the chip: the real one wraps a pyOCD target; tests use a fake."""

    def read32(self, addr):
        raise NotImplementedError

    def write32(self, addr, value):
        raise NotImplementedError

    def read_bytes(self, addr, n):
        out = bytearray()
        for a in range(addr, addr + n, 4):
            out += self.read32(a).to_bytes(4, "little")
        return bytes(out[:n])


class PyocdAccess(Access):
    def __init__(self, target):
        self.t = target

    def read32(self, addr):
        return self.t.read32(addr)

    def write32(self, addr, value):
        self.t.write32(addr, value)

    def read_bytes(self, addr, n):
        return bytes(self.t.read_memory_block8(addr, n))


def flash_reg(chip, name):
    return chip.reg_addr("FLASH", name)


def wait_not_busy(acc, chip, timeout=3.0):
    sr = flash_reg(chip, "SR")
    bsy = 1 << chip.reg("FLASH", "SR")["fields"]["BSY"][0]
    end = time.time() + timeout
    while acc.read32(sr) & bsy:
        if time.time() > end:
            raise ProgrammerError("flash stays busy")
        time.sleep(0.001)


def unlock_flash(acc, chip):
    cr = flash_reg(chip, "CR")
    lock = 1 << chip.reg("FLASH", "CR")["fields"]["LOCK"][0]
    if acc.read32(cr) & lock:
        acc.write32(flash_reg(chip, "KEYR"), FLASH_KEYS[0])
        acc.write32(flash_reg(chip, "KEYR"), FLASH_KEYS[1])
    if acc.read32(cr) & lock:
        raise ProgrammerError("flash could not be unlocked (reset the chip and try again)")


def unlock_option_bytes(acc, chip):
    cr = flash_reg(chip, "CR")
    ol = 1 << chip.reg("FLASH", "CR")["fields"]["OPTLOCK"][0]
    if acc.read32(cr) & ol:
        acc.write32(flash_reg(chip, "OPTKEYR"), OPT_KEYS[0])
        acc.write32(flash_reg(chip, "OPTKEYR"), OPT_KEYS[1])
    if acc.read32(cr) & ol:
        raise ProgrammerError("option bytes could not be unlocked")


def read_option_words(acc, chip):
    """-> (words {name: value16}, valid {name: bool})"""
    raw = acc.read_bytes(chip.option_bytes["address"], option_bytes.size(chip))
    d = option_bytes.decode(chip, raw)
    return d["words"], d["valid"]


def write_option_words(acc, chip, words, log=lambda s: None, reload=True):
    """RM 4.4.2: unlock, write the FLASH_OPTR/SDKR/BTCR/WRPR registers, OPTSTRT, trigger write, wait, EOP, reload."""
    cr_f = chip.reg("FLASH", "CR")["fields"]
    sr_f = chip.reg("FLASH", "SR")["fields"]
    unlock_flash(acc, chip)
    unlock_option_bytes(acc, chip)
    wait_not_busy(acc, chip)
    for name, v in words.items():
        reg = option_bytes.WORD_REG[name]
        acc.write32(flash_reg(chip, reg), v & 0xFFFF)
        log(f"FLASH_{reg} = 0x{v & 0xFFFF:04X}")
    acc.write32(flash_reg(chip, "CR"), acc.read32(flash_reg(chip, "CR")) | (1 << cr_f["OPTSTRT"][0]))
    acc.write32(OPT_TRIGGER, 0xFFFFFFFF)
    wait_not_busy(acc, chip, timeout=5.0)
    end = time.time() + 2.0
    while not acc.read32(flash_reg(chip, "SR")) & (1 << sr_f["EOP"][0]):
        if time.time() > end:
            raise ProgrammerError("the option byte write did not finish (no EOP)")
        time.sleep(0.001)
    acc.write32(flash_reg(chip, "SR"), 1 << sr_f["EOP"][0])
    if reload:
        acc.write32(flash_reg(chip, "CR"), acc.read32(flash_reg(chip, "CR")) | (1 << cr_f["OBL_LAUNCH"][0]))      # reloads the option bytes (a reset)


# ------------------------------------------------------------------------------------ SWD session
class Swd:
    """pyOCD session for one chip: `with Swd(chip, 64, uid) as s: s.program(path)`."""

    def __init__(self, chip, flash_kb, uid=None, speed=1_000_000, mode="attach", log=lambda s: None):
        self.chip, self.flash_kb, self.uid, self.speed, self.mode, self.log = chip, flash_kb, uid, speed, mode, log
        self.session = None

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, *a):
        self.close()

    def open(self):
        try:
            from pyocd.core.helpers import ConnectHelper
        except ImportError as e:
            raise ProgrammerError("pyOCD is not installed") from e
        opts = {"target_override": target_name(self.chip, self.flash_kb), "pack": [pack_path()], "frequency": self.speed,
                "connect_mode": self.mode, "auto_unlock": False, "resume_on_disconnect": True, "warning.cortex_m_default": False}
        self.log(f"connecting ({opts['target_override']}, {self.speed // 1000} kHz, mode {self.mode})")
        try:
            self.session = ConnectHelper.session_with_chosen_probe(unique_id=self.uid, options=opts, auto_open=False, blocking=False)
            if self.session is None:
                raise ProgrammerError("no debug probe found (plug it in; on Linux install the udev rule from Help > Probe setup)")
            self.session.open()
        except ProgrammerError:
            raise
        except Exception as e:
            raise ProgrammerError(f"cannot connect: {e}. Try 'connect under reset', check VCC/GND/SWDIO/SWCLK and whether the chip is "
                                  f"read-protected or has its debug pins reassigned.") from e
        self.target = self.session.target
        self.acc = PyocdAccess(self.target)

    def close(self):
        if self.session:
            try:
                self.session.close()
            finally:
                self.session = None

    def info(self):
        uid = self.acc.read_bytes(self.chip.memory["uid_base"], 12)
        words, valid = read_option_words(self.acc, self.chip)
        return {"target": target_name(self.chip, self.flash_kb), "uid": uid.hex(), "option_words": words, "option_valid": valid,
                "read_protected": self.is_read_protected(words)}

    def is_read_protected(self, words):
        rdp = self.chip.option_bytes.get("rdp")
        return bool(rdp and (words["user"] & 0xFF) != rdp["unprotected"])

    def program(self, path, chip_erase="sector", verify=True, progress=None, base=0x08000000):
        from pyocd.flash.file_programmer import FileProgrammer
        ext = os.path.splitext(path)[1].lower()
        fmt = "hex" if ext in (".hex", ".ihex") else "elf" if ext == ".elf" else "bin"
        prog = FileProgrammer(self.session, chip_erase=chip_erase, smart_flash=True, trust_crc=False,
                              progress=(lambda f: progress(f)) if progress else None)
        self.log(f"programming {os.path.basename(path)} ({fmt})")
        kw = {"base_address": base} if fmt == "bin" else {}
        prog.program(path, file_format=fmt, **kw)
        if verify:
            self.log("verify: the flash algorithm compared every sector while programming")

    def erase_chip(self):
        self.target.mass_erase()

    def reset_run(self):
        self.target.reset()

    def write_options(self, words):
        write_option_words(self.acc, self.chip, words, self.log)


# ------------------------------------------------------------------------------------ serial boot loader
def isp_flash(chip, port_device, data, baud=115200, log=lambda s: None, progress=None, erase=True):
    if chip.id == "py32f002b":
        raise ProgrammerError("the PY32F002B has no serial boot loader: use a debug probe (SWD)")
    port = serial_isp.open_port(port_device, baud)
    try:
        serial_isp.enter_bootloader(port)
        isp = serial_isp.Isp(port, log)
        isp.sync()
        pid = isp.identify()
        if pid not in serial_isp.KNOWN_IDS:
            raise ProgrammerError(f"unknown boot loader ID 0x{pid:04X}")
        log(f"boot loader v{isp.version >> 4}.{isp.version & 15}, ID 0x{pid:04X}")
        isp.program(data, erase=erase, progress=progress)
        isp.go()
    finally:
        serial_isp.leave_bootloader(port)
        port.close()


def firmware_bytes(path):
    with open(path, "rb") as f:
        return f.read()
