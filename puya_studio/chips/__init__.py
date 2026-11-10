"""Chip database loader.  Each chip is one JSON file in this folder (written from the
datasheet and reference manual by tools/build_db.py; see "sources" and "notes" inside)."""
import json
import os
import re

_DIR = os.path.dirname(os.path.abspath(__file__))
CHIP_NAMES = ["py32f030", "py32f003", "py32f002b"]
_cache = {}


class Pin:
    """One physical pin of a package."""

    def __init__(self, d):
        self.n = d["n"]
        self.kind = d["kind"]              # io | power | nc
        self.ports = d.get("ports", [])    # one entry, or two for a dual-bonded pad
        self.name = d.get("name") or ("/".join(self.ports) if self.ports else "NC")
        self.notes = d.get("notes", [])
        self.exposed_pad = d.get("exposed_pad", False)

    @property
    def shared(self):
        return len(self.ports) > 1

    @property
    def label(self):
        return self.name if self.kind != "io" else "/".join(self.ports)


class Chip:
    def __init__(self, data):
        self.d = data
        self.id = data["name"].lower()
        self.name = data["name"]
        self.packages = data["packages"]
        self.ports = data["ports"]
        self.peripherals = data["peripherals"]
        self.interrupts = {int(k): v for k, v in data["interrupts"].items()}
        self.features = data["features"]
        self.clock = data["clock"]
        self.memory = data["memory"]
        self.option_bytes = data["option_bytes"]
        self.max_hz = data["max_hz"]
        self.parts = data["parts"]
        self.notes = data.get("notes", [])
        self._alias = data["signal_alias"]

    # -- signals -------------------------------------------------------------
    def canon(self, sig):
        """Name used in the datasheet table -> canonical name (I2C_SCL -> I2C1_SCL, CMP -> COMP)."""
        for a, b in self._alias.items():
            if sig.startswith(a):
                return b + sig[len(a):]
        return sig

    def pins(self, package):
        return [Pin(p) for p in self.packages[package]["pins"]]

    def package_label(self, pid):
        p = self.packages[pid]
        return f"{p['type']} - pinout {p['pinout']} ({p['code']})"

    def af_of(self, port):
        """{af_number: canonical signal} of a port."""
        return {int(k): self.canon(v) for k, v in self.ports[port]["af"].items()}

    def analog_of(self, port):
        return list(self.ports[port].get("analog", []))

    def port_for_signal(self, signal):
        """[(port, af)] where a canonical signal can be routed."""
        out = []
        for p in self.ports:
            for af, s in self.af_of(p).items():
                if s == signal:
                    out.append((p, af))
        return out

    def part(self, name):
        for p in self.parts:
            if p["part"].upper() == name.upper():
                return p
        raise KeyError(name)

    def parts_for_package(self, pid):
        return [p for p in self.parts if p["package"] == pid]

    def reg(self, periph, name):
        return self.peripherals[periph]["regs"][name]

    def reg_addr(self, periph, name):
        return self.peripherals[periph]["base"] + self.peripherals[periph]["regs"][name]["off"]


def load(name):
    name = name.lower()
    if name not in _cache:
        with open(os.path.join(_DIR, name + ".json"), encoding="utf8") as f:
            _cache[name] = Chip(json.load(f))
    return _cache[name]


def all_chips():
    return [load(n) for n in CHIP_NAMES]
