"""Option bytes: decode, plan a change with a safety classification, encode.

Layout (RM, FLASH chapter "Flash option bytes"): every word holds a 16-bit value in bits 15:0 and its
complement in bits 31:16.  When written through the FLASH_OPTR / SDKR / BTCR / WRPR registers (SWD) the
hardware makes the complement itself; through the serial boot loader the host has to write the
complement too (`encode`).

`plan()` tells which of the changes could lock the chip or make it hard to reach again; the programming
dialogs ask for a typed confirmation for those (level "lock") and a normal yes/no for "caution".
"""
from dataclasses import dataclass, field

WORD_REG = {"user": "OPTR", "sdk": "SDKR", "wrp": "WRPR", "boot": "BTCR"}


@dataclass
class Danger:
    level: str            # "lock" (could lock the chip / needs typed confirmation) | "caution"
    key: str
    text: str


@dataclass
class Plan:
    changes: dict = field(default_factory=dict)       # {"word.FIELD": (old, new)}
    dangers: list = field(default_factory=list)

    @property
    def needs_typed_confirmation(self):
        return any(d.level == "lock" for d in self.dangers)

    @property
    def empty(self):
        return not self.changes


def layout(chip):
    """[(word name, address, {field: (lsb, width)})] in address order."""
    ob = chip.option_bytes
    return sorted(((n, w["addr"], {k: tuple(v) for k, v in w["fields"].items()}) for n, w in ob["words"].items()), key=lambda x: x[1])


def layout_dict(chip):
    return {n: f for n, a, f in layout(chip)}


def size(chip):
    last = max(w["addr"] for w in chip.option_bytes["words"].values())
    return last - chip.option_bytes["address"] + 4


def decode(chip, data):
    """data: bytes read from the option byte address -> {"words": {name: value16}, "valid": {name: bool}, "fields": {word.FIELD: v}}"""
    out = {"words": {}, "valid": {}, "fields": {}}
    base = chip.option_bytes["address"]
    for name, addr, fields in layout(chip):
        off = addr - base
        w = int.from_bytes(data[off:off + 4], "little")
        lo, hi = w & 0xFFFF, w >> 16
        out["words"][name] = lo
        out["valid"][name] = (lo ^ hi) == 0xFFFF
        for fn, (lsb, width) in fields.items():
            out["fields"][f"{name}.{fn}"] = (lo >> lsb) & ((1 << width) - 1)
    return out


def encode(chip, values):
    """{word name: value16} -> bytes (with the complements) for the whole option byte area; reserved words are 0xFF."""
    base = chip.option_bytes["address"]
    buf = bytearray(b"\xff" * size(chip))
    for name, addr, fields in layout(chip):
        v = values[name] & 0xFFFF
        buf[addr - base:addr - base + 4] = (v | ((~v & 0xFFFF) << 16)).to_bytes(4, "little")
    return bytes(buf)


def set_field(chip, words, name, field_name, value):
    """Return a copy of `words` with one field changed."""
    for n, addr, fields in layout(chip):
        if n == name:
            lsb, width = fields[field_name]
            mask = ((1 << width) - 1) << lsb
            new = dict(words)
            new[name] = (words[name] & ~mask) | ((value << lsb) & mask)
            return new
    raise KeyError(name)


def defaults(chip):
    """Production values (low 16 bits) from the RM."""
    return {n: w["production"] & 0xFFFF for n, w in chip.option_bytes["words"].items()}


def plan(chip, old, new, vdd=3.3):
    """Compare two {word: value16} dicts and classify the risk of the change."""
    ob = chip.option_bytes
    p = Plan()
    oldf = decode_fields(chip, old)
    newf = decode_fields(chip, new)
    for k in newf:
        if oldf[k] != newf[k]:
            p.changes[k] = (oldf[k], newf[k])
    rdp = ob.get("rdp")
    if rdp and "user.RDP" in p.changes:
        o, n = p.changes["user.RDP"]
        open_ = rdp["unprotected"]
        if o == open_ and n != open_:
            p.dangers.append(Danger("lock", "RDP", "Switches ON read-out protection. The debug port can no longer read the chip, and turning it off "
                                                   "again ERASES the whole flash. Make sure you have the firmware elsewhere."))
        elif o != open_ and n == open_:
            p.dangers.append(Danger("lock", "RDP", "Switches OFF read-out protection: the chip performs a mass erase (the whole flash is lost)."))
        else:
            p.dangers.append(Danger("caution", "RDP", "Changes the read-out protection value."))
    if "user.NRST_MODE" in p.changes:
        o, n = p.changes["user.NRST_MODE"]
        if "SWD_MODE" in ob["words"]["user"]["fields"]:
            pass
        if n == 1 and chip.id != "py32f002b":
            p.dangers.append(Danger("lock", "NRST_MODE", f"Turns the reset pin {chip.d['nrst']} into a GPIO: the chip then has no hardware reset input, and the programmer "
                                                         "cannot reset it under connect."))
        elif chip.id == "py32f002b":
            p.dangers.append(Danger("lock", "NRST_MODE", f"Changes what {chip.d['nrst']} does (reset or GPIO / SWD): a wrong combination can make the chip unreachable for the probe."))
    if "user.SWD_MODE" in p.changes:
        p.dangers.append(Danger("lock", "SWD_MODE", "Moves or disables the SWD debug pins. If the new setting is not what your probe is wired to, the chip can no longer be programmed through SWD."))
    for k in ("wrp.WRP",):
        if k in p.changes:
            o, n = p.changes[k]
            if (n ^ o) & ~n & ((1 << ob["words"]["wrp"]["fields"]["WRP"][1]) - 1):
                p.dangers.append(Danger("lock", "WRP", "Write-protects flash sectors: they cannot be programmed or erased until the protection is removed."))
            else:
                p.dangers.append(Danger("caution", "WRP", "Removes write protection from flash sectors."))
    if "sdk.SDK_STRT" in p.changes or "sdk.SDK_END" in p.changes:
        p.dangers.append(Danger("lock", "SDK", "Changes the SDK area (flash that the debug port cannot read). Read protection of that area is permanent until a mass erase."))
    for k in ("boot.BOOT0", "boot.nBOOT1", "boot.BOOT_SIZE", "user.nBOOT1"):
        if k in p.changes:
            p.dangers.append(Danger("caution", k, "Changes where the chip starts after reset (flash / system memory / SRAM / load-flash area)."))
    if "user.IWDG_SW" in p.changes and p.changes["user.IWDG_SW"][1] == 0:
        p.dangers.append(Danger("caution", "IWDG_SW", "The independent watchdog will start by itself after every reset; the program must feed it from the first moment."))
    if "user.BOR_EN" in p.changes or "user.BOR_LEV" in p.changes:
        lev = newf.get("user.BOR_LEV", 0)
        thr = 1.8 + 0.2 * lev
        if newf.get("user.BOR_EN", 0) and thr + 0.1 >= vdd:
            p.dangers.append(Danger("caution", "BOR", f"The brown-out threshold ({thr:.1f} V) is close to or above the supply voltage {vdd} V: the chip would stay in reset."))
    return p


def decode_fields(chip, words):
    out = {}
    for name, addr, fields in layout(chip):
        for fn, (lsb, width) in fields.items():
            out[f"{name}.{fn}"] = (words[name] >> lsb) & ((1 << width) - 1)
    return out


def confirmation_word(chip, plan_):
    """The word the user has to type for a dangerous change."""
    return "LOCK" if any(d.key in ("RDP", "SDK", "WRP") for d in plan_.dangers if d.level == "lock") else "RISK"
