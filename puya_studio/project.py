"""Project model: chip choice, clock, pin assignments, peripheral settings.

A project is a plain dict (JSON file `project.pstudio` in the project folder).
Pin assignment never needs a popup: `assign()`/`clear()` are plain functions the
side panel, the Delete key and the right-click reset all call.
"""
import copy
import json
import os
import re

from . import chips, timing

PIN_FUNCS = ("unused", "gpio_in", "gpio_out", "analog", "exti", "af")
SPEEDS = ["low", "medium", "high", "veryhigh"]            # OSPEEDR 0..3
PULLS = ["none", "up", "down"]
EXTI_EDGES = ["rising", "falling", "both"]
FILE_NAME = "project.pstudio"
VERSION = 1


def identifier(text, fallback):
    s = re.sub(r"[^A-Za-z0-9_]", "_", (text or "").strip())
    if not s:
        return fallback
    if s[0].isdigit():
        s = "_" + s
    return s


def pin_defaults(func="unused"):
    return {"func": func, "label": "", "pull": "none", "speed": "low", "otype": "pp", "init": "low",
            "signal": None, "edge": "falling"}


def periph_defaults(chip, name):
    """Default settings of a peripheral the first time it is switched on."""
    if name.startswith("USART"):
        return {"enabled": True, "baud": 115200, "bits": 8, "parity": "none", "stop": 1, "irq_rx": False, "prio": 2}
    if name.startswith("SPI"):
        return {"enabled": True, "mode": "master", "speed_hz": 1_000_000, "cpol": 0, "cpha": 0, "bits": 8,
                "first": "msb", "irq": False, "prio": 2}
    if name.startswith("I2C"):
        return {"enabled": True, "speed_hz": 100_000, "irq": False, "prio": 2}
    if name == "ADC":
        return {"enabled": True, "resolution": 12, "sample": 7, "temp": False, "vref": False, "continuous": False}
    if name.startswith("TIM"):
        return {"enabled": True, "freq_hz": 1000.0, "duty": {}, "irq": False, "prio": 2, "dead_time": 0}
    if name == "IWDG":
        return {"enabled": False, "timeout_ms": 1000}
    if name.startswith("LPTIM"):
        return {"enabled": True}
    return {"enabled": True}


def signal_peripheral(sig):
    """Canonical signal -> peripheral instance it belongs to (USART1_TX -> USART1)."""
    head = sig.split("_")[0]
    if head in ("EVENTOUT", "MCO", "IR", "RTC", "SWDIO", "SWCLK", "SWD", "SWC", "LED"):
        return head if head in ("IR", "RTC", "LED") else None
    return head


class Project:
    def __init__(self, chip_id="py32f030", part=None, package=None):
        self.chip = chips.load(chip_id)
        self.part = part
        self.package = package or sorted(self.chip.packages)[0]
        self.flash_kb = None
        self.ram_kb = None
        self.vdd = 3.3
        self.clock = timing.default_clock(self.chip)
        self.pins = {}              # port -> pin settings (only ports that are not "unused")
        self.periph = {}            # instance name -> settings
        self.power = {"idle": "none", "stop_wake": "exti", "stop_lpr": False}
        self.irq = {"prio": {}, "extra": {}}       # priorities per interrupt name; extra interrupts to enable (name -> priority)
        self.name = "project"
        self.set_default_memory()

    # ------------------------------------------------------------------ memory / part / package
    def set_default_memory(self):
        parts = self.chip.parts_for_package(self.package)
        if parts:
            big = max(parts, key=lambda p: p["flash_kb"])
            self.flash_kb, self.ram_kb = big["flash_kb"], big["ram_kb"]
            self.part = big["part"]

    def set_part(self, part):
        p = self.chip.part(part)
        self.part, self.package = p["part"], p["package"]
        self.flash_kb, self.ram_kb = p["flash_kb"], p["ram_kb"]
        self.drop_pins_not_in_package()

    def set_package(self, package):
        """Manual choice of the package variant (keeps flash/RAM if the chip has them, else the largest)."""
        self.package = package
        match = [p for p in self.chip.parts_for_package(package) if p["flash_kb"] == self.flash_kb]
        if match:
            self.part = match[0]["part"]
        else:
            self.set_default_memory()
        self.drop_pins_not_in_package()

    def set_memory(self, flash_kb):
        for p in self.chip.parts_for_package(self.package):
            if p["flash_kb"] == flash_kb:
                self.flash_kb, self.ram_kb, self.part = p["flash_kb"], p["ram_kb"], p["part"]
                return
        raise ValueError(f"{flash_kb} KB flash does not exist for this package")

    def package_ports(self):
        return {port for pin in self.chip.pins(self.package) for port in pin.ports}

    def drop_pins_not_in_package(self):
        ports = self.package_ports()
        for p in list(self.pins):
            if p not in ports:
                del self.pins[p]

    # ------------------------------------------------------------------ pin functions
    def functions_for(self, port):
        """All things a port can do: list of dicts {id, label, signal}.  `id` is what assign() takes."""
        out = [{"id": "unused", "label": "Unused", "signal": None},
               {"id": "gpio_in", "label": "GPIO input", "signal": None},
               {"id": "gpio_out", "label": "GPIO output", "signal": None},
               {"id": "exti", "label": "GPIO input with interrupt (EXTI)", "signal": None}]
        analog = self.chip.analog_of(port)
        if analog or True:
            out.append({"id": "analog", "label": "Analog" + (f" ({', '.join(analog)})" if analog else ""), "signal": None})
        for af, sig in sorted(self.chip.af_of(port).items()):
            out.append({"id": f"af:{sig}", "label": f"{sig}  (AF{af})", "signal": sig, "af": af})
        return out

    def signal_af(self, port, signal):
        for af, sig in self.chip.af_of(port).items():
            if sig == signal:
                return af
        return None

    def assign(self, port, func, **opts):
        """Set what a port does.  func: unused | gpio_in | gpio_out | analog | exti | af:<SIGNAL>."""
        if port not in self.chip.ports:
            raise KeyError(port)
        if func == "unused":
            return self.clear(port)
        d = self.pins.get(port) or pin_defaults()
        d = dict(d)
        d["signal"] = None
        if func.startswith("af:"):
            sig = func[3:]
            if self.signal_af(port, sig) is None:
                raise ValueError(f"{port} cannot be {sig}")
            d["func"], d["signal"] = "af", sig
            d["speed"] = d["speed"] if d["speed"] != "low" else "medium"
            if sig.startswith("I2C"):
                d["otype"] = "od"                       # I2C lines are open-drain (external pull-ups)
            self.ensure_periph(signal_peripheral(sig))
        elif func in ("gpio_in", "gpio_out", "analog", "exti"):
            d["func"] = func
        else:
            raise ValueError(func)
        d.update({k: v for k, v in opts.items() if k in pin_defaults()})
        self.pins[port] = d
        self.prune_auto_periph()

    def clear(self, port):
        self.pins.pop(port, None)
        self.prune_auto_periph()

    def ensure_periph(self, inst):
        if not inst:
            return
        inst = {"I2C": "I2C1", "LPTIM": "LPTIM1"}.get(inst, inst)
        if inst not in self.periph:
            s = periph_defaults(self.chip, inst)
            s["auto"] = True
            self.periph[inst] = s
        elif not self.periph[inst].get("enabled"):
            self.periph[inst]["enabled"] = True

    def prune_auto_periph(self):
        used = {signal_peripheral(p["signal"]) for p in self.pins.values() if p["func"] == "af" and p["signal"]}
        for inst, s in list(self.periph.items()):
            if s.get("auto") and inst not in used and inst not in ("ADC", "IWDG"):
                del self.periph[inst]

    def signals_in_use(self):
        """{signal: [ports]} for pins set to an alternate function."""
        out = {}
        for port, p in self.pins.items():
            if p["func"] == "af":
                out.setdefault(p["signal"], []).append(port)
        return out

    def adc_channels(self):
        """Sorted list of (channel number, port) for pins in analog mode that have an ADC channel."""
        res = []
        for port, p in self.pins.items():
            if p["func"] == "analog":
                for a in self.chip.analog_of(port):
                    if a.startswith("ADC_IN"):
                        res.append((int(a[6:]), port))
        return sorted(res)

    # ------------------------------------------------------------------ names
    def pin_name(self, port):
        p = self.pins.get(port)
        return identifier(p["label"] if p else "", port)

    def used_names(self):
        names = {}
        for port in sorted(self.pins):
            n = self.pin_name(port)
            names.setdefault(n, []).append(port)
        return names

    # ------------------------------------------------------------------ persistence
    def to_dict(self):
        return {"version": VERSION, "name": self.name, "chip": self.chip.id, "part": self.part,
                "package": self.package, "flash_kb": self.flash_kb, "ram_kb": self.ram_kb, "vdd": self.vdd,
                "clock": self.clock, "pins": self.pins, "periph": self.periph, "power": self.power, "irq": self.irq}

    @classmethod
    def from_dict(cls, d):
        p = cls(d["chip"], d.get("part"), d.get("package"))
        p.name = d.get("name", "project")
        p.part, p.flash_kb, p.ram_kb = d.get("part"), d.get("flash_kb"), d.get("ram_kb")
        p.vdd = d.get("vdd", 3.3)
        p.clock = {**timing.default_clock(p.chip), **d.get("clock", {})}
        p.pins = {k: {**pin_defaults(), **v} for k, v in d.get("pins", {}).items()}
        p.periph = d.get("periph", {})
        p.power = {**p.power, **d.get("power", {})}
        p.irq = {"prio": d.get("irq", {}).get("prio", {}), "extra": d.get("irq", {}).get("extra", {})}
        return p

    def save(self, folder):
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, FILE_NAME), "w", encoding="utf8") as f:
            json.dump(self.to_dict(), f, indent=1, sort_keys=True)
            f.write("\n")

    @classmethod
    def load(cls, folder):
        with open(os.path.join(folder, FILE_NAME), encoding="utf8") as f:
            return cls.from_dict(json.load(f))

    def copy(self):
        return Project.from_dict(copy.deepcopy(self.to_dict()))
