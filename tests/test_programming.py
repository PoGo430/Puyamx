"""Programming code tested against simulated hardware: option byte handling, the serial boot loader protocol,
the SWD option write sequence, and the flash algorithm pack."""
import pytest

from puya_studio import chips, flasher, option_bytes as ob, serial_isp


# ------------------------------------------------------------------------------------ option bytes
def test_option_words_roundtrip_and_validity():
    c = chips.load("py32f030")
    data = ob.encode(c, ob.defaults(c))
    assert len(data) == 16
    assert int.from_bytes(data[0:4], "little") == 0x4155BEAA            # production value in the RM
    assert int.from_bytes(data[4:8], "little") == 0xFF00_00FF            # SDK: production value from the RM
    d = ob.decode(c, data)
    assert all(d["valid"].values()) and d["words"] == ob.defaults(c)
    assert d["fields"]["user.RDP"] == 0xAA and d["fields"]["user.nBOOT1"] == 1 and d["fields"]["user.NRST_MODE"] == 0
    broken = bytearray(data)
    broken[2] ^= 0xFF
    assert not ob.decode(c, bytes(broken))["valid"]["user"]


def test_f002b_has_four_words_and_no_rdp():
    c = chips.load("py32f002b")
    assert [n for n, a, f in ob.layout(c)] == ["user", "sdk", "boot", "wrp"]
    assert ob.size(c) == 16 and c.option_bytes["rdp"] is None
    d = ob.decode(c, ob.encode(c, ob.defaults(c)))
    assert d["words"]["wrp"] == 0x003F


def test_plan_classifies_dangerous_changes():
    c = chips.load("py32f030")
    cur = ob.defaults(c)
    p = ob.plan(c, cur, cur)
    assert p.empty and not p.dangers
    lock = ob.set_field(c, cur, "user", "RDP", 0x55)
    p = ob.plan(c, cur, lock)
    assert p.needs_typed_confirmation and p.dangers[0].key == "RDP" and "ERASES" in p.dangers[0].text
    assert ob.confirmation_word(c, p) == "LOCK"
    p = ob.plan(c, lock, cur)                                              # unlocking = mass erase
    assert p.needs_typed_confirmation and "mass erase" in p.dangers[0].text
    gpio = ob.set_field(c, cur, "user", "NRST_MODE", 1)
    p = ob.plan(c, cur, gpio)
    assert p.needs_typed_confirmation and p.dangers[0].key == "NRST_MODE"
    assert not ob.plan(c, gpio, cur).dangers                              # back to a reset pin is harmless
    wrp = ob.set_field(c, cur, "wrp", "WRP", 0xFFF0)
    assert ob.plan(c, cur, wrp).needs_typed_confirmation
    sdk = ob.set_field(c, cur, "sdk", "SDK_END", 3)
    assert ob.plan(c, cur, sdk).needs_typed_confirmation
    boot = ob.set_field(c, cur, "user", "nBOOT1", 0)
    p = ob.plan(c, cur, boot)
    assert p.dangers and not p.needs_typed_confirmation                  # caution only
    bor = ob.set_field(c, ob.set_field(c, cur, "user", "BOR_EN", 1), "user", "BOR_LEV", 7)
    assert any(d.key == "BOR" for d in ob.plan(c, cur, bor, vdd=3.3).dangers)
    safe = ob.set_field(c, cur, "user", "IWDG_SW", 1)
    assert ob.plan(c, ob.set_field(c, cur, "user", "IWDG_SW", 0), safe).empty is False


def test_f002b_swd_mode_is_dangerous():
    c = chips.load("py32f002b")
    cur = ob.defaults(c)
    new = ob.set_field(c, cur, "user", "SWD_MODE", 0)
    p = ob.plan(c, cur, new)
    assert any(d.key == "SWD_MODE" and d.level == "lock" for d in p.dangers)


# ------------------------------------------------------------------------------------ SWD option write
class FakeFlash(flasher.Access):
    """Just enough of the FLASH peripheral to follow the RM option byte sequence."""

    def __init__(self, chip, locked=True):
        self.c = chip
        self.reg = {}
        self.log = []
        f = lambda n: flasher.flash_reg(chip, n)
        self.addr = {n: f(n) for n in ("CR", "SR", "KEYR", "OPTKEYR", "OPTR", "SDKR", "WRPR", "BTCR") if n in chip.peripherals["FLASH"]["regs"]}
        self.reg[self.addr["CR"]] = (1 << 31) | (1 << 30) if locked else 0
        self.reg[self.addr["SR"]] = 0
        self.keys = {"KEYR": [], "OPTKEYR": []}
        self.optwords = dict.fromkeys(("OPTR", "SDKR", "WRPR", "BTCR"), None)

    def read32(self, a):
        return self.reg.get(a, 0)

    def write32(self, a, v):
        self.log.append((a, v))
        if a == self.addr["KEYR"]:
            self.keys["KEYR"].append(v)
            if self.keys["KEYR"][-2:] == list(flasher.FLASH_KEYS):
                self.reg[self.addr["CR"]] &= ~(1 << 31)
            return
        if a == self.addr["OPTKEYR"]:
            self.keys["OPTKEYR"].append(v)
            if self.keys["OPTKEYR"][-2:] == list(flasher.OPT_KEYS) and not self.reg[self.addr["CR"]] & (1 << 31):
                self.reg[self.addr["CR"]] &= ~(1 << 30)
            return
        for n in self.optwords:
            if n in self.addr and a == self.addr[n]:
                assert not self.reg[self.addr["CR"]] & (1 << 30), "option registers written while locked"
                self.optwords[n] = v
                return
        if a == flasher.OPT_TRIGGER:
            assert self.reg[self.addr["CR"]] & (1 << self.c.reg("FLASH", "CR")["fields"]["OPTSTRT"][0]), "trigger without OPTSTRT"
            self.reg[self.addr["SR"]] |= 1 << self.c.reg("FLASH", "SR")["fields"]["EOP"][0]
            return
        if a == self.addr["SR"]:
            self.reg[a] &= ~v
            return
        self.reg[a] = v


@pytest.mark.parametrize("chip_id", chips.CHIP_NAMES)
def test_option_write_sequence_follows_the_rm(chip_id):
    c = chips.load(chip_id)
    fl = FakeFlash(c)
    words = ob.set_field(c, ob.defaults(c), "user", "BOR_EN", 1)
    flasher.write_option_words(fl, c, words)
    assert fl.keys["KEYR"] == list(flasher.FLASH_KEYS) and fl.keys["OPTKEYR"] == list(flasher.OPT_KEYS)
    assert fl.optwords["OPTR"] == words["user"] and fl.optwords["WRPR"] == words["wrp"]
    order = [a for a, v in fl.log]
    assert order.index(fl.addr["KEYR"]) < order.index(fl.addr["OPTKEYR"]) < order.index(fl.addr["OPTR"]) < order.index(flasher.OPT_TRIGGER)
    if chip_id == "py32f002b":
        assert fl.optwords["BTCR"] == words["boot"]


def test_read_option_words_from_memory():
    c = chips.load("py32f030")

    class Mem(flasher.Access):
        def read_bytes(self, a, n):
            assert a == 0x1FFF0E80
            return ob.encode(c, ob.defaults(c))[:n]
    words, valid = flasher.read_option_words(Mem(), c)
    assert words == ob.defaults(c) and all(valid.values())


# ------------------------------------------------------------------------------------ serial boot loader
class FakeBoot:
    """A boot loader that speaks the protocol: used to test serial_isp without hardware."""

    def __init__(self, flash=64 * 1024, locked=False, pid=0x440, corrupt=False):
        self.corrupt = corrupt
        self.mem = bytearray(b"\xff" * flash)
        self.rx = bytearray()
        self.tx = bytearray()
        self.pid = pid
        self.synced = False
        self.state = "idle"
        self.pending = None
        self.went = None
        self.unlocked = 0
        self.erased = 0
        self.timeout = 1

    def reset_input_buffer(self):
        self.tx.clear()

    def write(self, data):
        self.rx += data
        self.step()

    def read(self, n):
        out = bytes(self.tx[:n])
        del self.tx[:n]
        return out

    def ack(self):
        self.tx.append(0x79)

    def step(self):
        while True:
            if not self.synced:
                if not self.rx:
                    return
                b = self.rx.pop(0)
                if b == 0x7F:
                    self.tx.append(0x79)
                    self.synced = True
                continue
            if self.state == "idle":
                if len(self.rx) < 2:
                    return
                cmd, comp = self.rx[0], self.rx[1]
                del self.rx[:2]
                assert cmd ^ comp == 0xFF
                self.ack()
                if cmd == 0x00:
                    self.tx += bytes([6, 0x31, 0x00, 0x01, 0x02, 0x11, 0x21, 0x31, 0x79])   # N, version, 6 commands... ACK
                elif cmd == 0x02:
                    self.tx += bytes([1]) + self.pid.to_bytes(2, "big") + bytes([0x79])
                elif cmd in (0x11, 0x31, 0x21):
                    self.state, self.pending = "addr", cmd
                elif cmd == 0x44:
                    self.state = "erase"
                elif cmd == 0x92:
                    self.unlocked += 1
                    self.tx.append(0x79)
                else:
                    self.tx[-1] = 0x1F
            elif self.state == "addr":
                if len(self.rx) < 5:
                    return
                a = bytes(self.rx[:4])
                assert self.rx[4] == a[0] ^ a[1] ^ a[2] ^ a[3], "address checksum"
                del self.rx[:5]
                self.addr = int.from_bytes(a, "big")
                self.ack()
                if self.pending == 0x21:
                    self.went = self.addr
                    self.state = "idle"
                else:
                    self.state = "len" if self.pending == 0x11 else "data"
            elif self.state == "len":
                if len(self.rx) < 2:
                    return
                n = self.rx[0] + 1
                assert self.rx[0] ^ self.rx[1] == 0xFF
                del self.rx[:2]
                self.ack()
                off = self.addr - 0x08000000
                self.tx += self.mem[off:off + n]
                self.state = "idle"
            elif self.state == "data":
                if not self.rx:
                    return
                n = self.rx[0] + 1
                if len(self.rx) < n + 2:
                    return
                blk = bytes(self.rx[1:1 + n])
                par = self.rx[0]
                for x in blk:
                    par ^= x
                assert par == self.rx[1 + n], "block parity"
                del self.rx[:n + 2]
                off = self.addr - 0x08000000
                self.mem[off:off + n] = blk if not self.corrupt else bytes([blk[0] ^ 1]) + blk[1:]
                self.ack()
                self.state = "idle"
            elif self.state == "erase":
                if len(self.rx) < 3:
                    return
                assert bytes(self.rx[:3]) == b"\xff\xff\x00"
                del self.rx[:3]
                self.mem[:] = b"\xff" * len(self.mem)
                self.erased += 1
                self.tx.append(0xAA)             # busy for a moment, then ACK
                self.tx.append(0x79)
                self.state = "idle"


def test_isp_program_and_verify():
    port = FakeBoot()
    isp = serial_isp.Isp(port)
    isp.sync()
    assert isp.identify() == 0x440
    data = bytes(range(256)) * 5 + b"abc"
    n = isp.program(data)
    assert n == len(data) + 1                                              # padded to a word
    assert port.erased == 1 and bytes(port.mem[:len(data)]) == data
    isp.go()
    assert port.went == 0x08000000


def test_isp_detects_a_wrong_flash_content():
    port = FakeBoot(corrupt=True)
    isp = serial_isp.Isp(port)
    isp.sync()
    with pytest.raises(serial_isp.IspError, match="verify failed at 0x08000000"):
        isp.program(b"\x01\x02\x03\x04")


def test_isp_no_answer():
    class Dead:
        def write(self, d): pass
        def read(self, n): return b""
        def reset_input_buffer(self): pass
    with pytest.raises(serial_isp.IspError, match="did not answer"):
        serial_isp.Isp(Dead()).sync()


def test_isp_unlock_and_f002b_refusal():
    port = FakeBoot()
    isp = serial_isp.Isp(port)
    isp.sync()
    isp.unlock_read_protection()
    assert port.unlocked == 1
    with pytest.raises(flasher.ProgrammerError, match="no serial boot loader"):
        flasher.isp_flash(chips.load("py32f002b"), "COM1", b"x")


# ------------------------------------------------------------------------------------ pack / probes
def test_pack_has_a_device_for_every_part_and_flash_size():
    pyocd = pytest.importorskip("pyocd")
    from pyocd.target import TARGET
    from pyocd.target.pack import pack_target
    pack_target.PackTargets.populate_targets_from_pack(flasher.pack_path())
    for c in chips.all_chips():
        for part in c.parts:
            name = flasher.target_name(c, part["flash_kb"])
            assert name in TARGET, (part["part"], name)


def test_pack_flash_geometry_matches_the_database():
    import zipfile, re
    z = zipfile.ZipFile(flasher.pack_path())
    pdsc = z.read("Puya.PY32F0xx_DFP.pdsc").decode()
    for c in chips.all_chips():
        for part in c.parts:
            name = flasher.target_name(c, part["flash_kb"])
            m = re.search(r'<device Dname="%s"(.*?)</device>' % re.escape(name.replace("py32", "PY32").replace("f0", "F0").replace("x", "x")), pdsc, re.S | re.I)
            assert m, name
            rom = int(re.search(r'name="IROM1"[^>]*size="(0x[0-9A-Fa-f]+)"', m.group(1)).group(1), 16)
            ram = int(re.search(r'name="IRAM1"[^>]*size="(0x[0-9A-Fa-f]+)"', m.group(1)).group(1), 16)
            if part["flash_kb"] != 8:
                assert rom == part["flash_kb"] * 1024 and ram == part["ram_kb"] * 1024 or c.id == "py32f003" and part["flash_kb"] in (48,), (part, rom, ram)


def test_udev_rules_and_probe_kinds():
    assert "0483" in flasher.UDEV_RULES and "0d28" in flasher.UDEV_RULES and "MODE=" in flasher.UDEV_RULES
    assert flasher.probe_kind("STMicroelectronics STLINK-V2") == "ST-Link"
    assert flasher.probe_kind("ARM DAPLink CMSIS-DAP") == "CMSIS-DAP"
    assert isinstance(flasher.list_probes(), list)
