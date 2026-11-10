"""The Problems list: checks a project while the user works.

check(project) -> [Problem].  Every problem names its cause (`target`) so that a double click in the
window can jump to the pin / page that has to be changed:
    ("pin", "PA5")  ("clock", None)  ("periph", "USART1")  ("power", None)  ("part", None)
"""
from dataclasses import dataclass

from . import codegen, timing
from .project import identifier

ERROR, WARNING, INFO = "error", "warning", "info"
ORDER = {ERROR: 0, WARNING: 1, INFO: 2}


@dataclass
class Problem:
    severity: str
    text: str
    target: tuple = ("part", None)
    code: str = ""

    def __str__(self):
        return f"{self.severity}: {self.text}"


def check(p):
    c = p.chip
    out = []

    def add(sev, text, target=("part", None), code=""):
        out.append(Problem(sev, text, target, code))

    pins = p.pins
    sigs = p.signals_in_use()
    meta = c.d

    # ---------------------------------------------------------------- clock
    clk = timing.clock_tree(c, p.clock)
    for sev, text in clk.problems:
        add(sev, text, ("clock", None), "clock")
    src = p.clock["source"]
    uses_hse = src == "HSE" or (src == "PLL" and p.clock.get("pll_src") == "HSE")
    if uses_hse:
        for q in c.d["ports"]:
            if "OSC_IN" in c.analog_of(q) or "OSC_OUT" in c.analog_of(q):
                if q in pins and not (p.clock.get("hse_bypass") and "OSC_OUT" in c.analog_of(q)):
                    add(ERROR, f"{q} is the HSE oscillator pin but is used as {describe(pins[q])}", ("pin", q), "hse-pin")
    if p.clock.get("mco") and "MCO" not in sigs:
        add(WARNING, "MCO clock output is switched on but no pin has the MCO function", ("clock", None), "mco-pin")
    if "MCO" in sigs and not p.clock.get("mco"):
        add(WARNING, "a pin is set to MCO but the MCO clock output is not enabled on the Clock page", ("clock", None), "mco-off")

    # ---------------------------------------------------------------- pins
    for sig, ports in sigs.items():
        if len(ports) > 1:
            for q in ports:
                add(ERROR, f"{sig} is assigned to {', '.join(ports)}: a signal can only be on one pin", ("pin", q), "dup-signal")
    for q, d in pins.items():
        if d["func"] == "af" and p.signal_af(q, d["signal"]) is None:
            add(ERROR, f"{q} cannot be {d['signal']} on {c.name}", ("pin", q), "bad-af")
        if q not in p.package_ports():
            add(ERROR, f"{q} does not exist in {p.package}", ("pin", q), "no-pin")
    for pin in c.pins(p.package):
        if pin.shared:
            used = [q for q in pin.ports if q in pins]
            if len(used) > 1:
                for q in used:
                    add(ERROR, f"pin {pin.n} is one pad for {' and '.join(pin.ports)}: only one of them can be used", ("pin", q), "shared-pad")
    names = p.used_names()
    for n, qs in names.items():
        if len(qs) > 1:
            for q in qs:
                add(WARNING, f"the name '{n}' is used by {', '.join(qs)}: the generated macros get the port as a suffix", ("pin", q), "dup-name")
    for q, d in pins.items():
        lab = d.get("label", "")
        if lab and identifier(lab, "") != lab:
            add(INFO, f"the name '{lab}' is written as {identifier(lab, q)} in C", ("pin", q), "name-c")
    swd = meta["swd"]
    for role, q in swd.items():
        if q in pins and not (pins[q]["func"] == "af" and pins[q]["signal"] in (role, "SWD", "SWC")):
            add(WARNING, f"{q} is the debug pin {role}: using it for something else makes the chip hard to reprogram "
                         f"(you need the reset line or the boot loader)", ("pin", q), "swd-pin")
    nrst = meta["nrst"]
    if nrst in pins:
        add(WARNING, f"{nrst} is the reset pin: using it as {describe(pins[nrst])} needs the NRST_MODE option byte "
                     f"(see Programming), and then the chip has no reset input", ("pin", nrst), "nrst-pin")
    b0 = meta.get("boot0")
    if b0 and b0 in pins:
        add(INFO, f"{b0} is the BOOT0 pin: its level at reset selects where the chip starts", ("pin", b0), "boot-pin")
    exti = {}
    for q, d in pins.items():
        if d["func"] == "exti":
            n = int(q[2:])
            allowed = c.exti.get(str(n))
            if not allowed or q[1] not in allowed:
                add(ERROR, f"{q} cannot be an interrupt pin: EXTI line {n} only serves port {', '.join(allowed or [])}", ("pin", q), "exti-port")
            exti.setdefault(n, []).append(q)
    for n, qs in exti.items():
        if len(qs) > 1:
            for q in qs:
                add(ERROR, f"{', '.join(qs)} share the interrupt line {n}: only one of them can interrupt", ("pin", q), "exti-conflict")
    for q, d in pins.items():
        if d["func"] == "af" and d["signal"].startswith("I2C") and d["otype"] != "od":
            add(WARNING, f"{q} is an I2C line and should be open-drain", ("pin", q), "i2c-od")
        if d["func"] == "analog" and not any(a.startswith(("ADC_IN", "COMP")) for a in c.analog_of(q)):
            add(INFO, f"{q} in analog mode has no ADC channel or comparator input (it just disconnects the digital part)", ("pin", q), "analog-none")

    # ---------------------------------------------------------------- peripherals
    for u in c.features["usart"]:
        s = p.periph.get(u)
        tx, rx = f"{u}_TX" in sigs, f"{u}_RX" in sigs
        if s and s.get("enabled"):
            if not (tx or rx):
                add(ERROR, f"{u} is enabled but neither {u}_TX nor {u}_RX is on a pin", ("periph", u), "usart-pins")
            brr, actual, err = timing.usart_brr(clk.pclk or 1, s["baud"])
            if brr is None:
                add(ERROR, f"{u}: {s['baud']} baud is not possible with PCLK {clk.pclk / 1e6:g} MHz (needs at least 16 clocks per bit)", ("periph", u), "baud")
            elif err > 3.0:
                add(ERROR, f"{u}: baud rate error {err:.1f} % ({actual:.0f} instead of {s['baud']}): data will be garbled", ("periph", u), "baud")
            elif err > 1.5:
                add(WARNING, f"{u}: baud rate error {err:.1f} % ({actual:.0f} instead of {s['baud']})", ("periph", u), "baud")
            total = s["bits"] + (0 if s["parity"] == "none" else 1)
            if total not in (8, 9):
                add(ERROR, f"{u}: {s['bits']} data bits with parity '{s['parity']}' is not possible (the frame must be 8 or 9 bits)", ("periph", u), "usart-frame")
            if s.get("irq_rx") and not rx:
                add(WARNING, f"{u}: receive interrupt is on but {u}_RX is not on a pin", ("periph", u), "usart-rx")
        elif tx or rx:
            add(ERROR, f"{u} signals are on pins but {u} is disabled", ("periph", u), "periph-off")
    for sp in c.features["spi"]:
        s = p.periph.get(sp)
        have = {k: f"{sp}_{k}" in sigs for k in ("SCK", "MISO", "MOSI", "NSS")}
        if s and s.get("enabled"):
            if not have["SCK"]:
                add(ERROR, f"{sp} is enabled but {sp}_SCK is not on a pin", ("periph", sp), "spi-sck")
            if not (have["MISO"] or have["MOSI"]):
                add(ERROR, f"{sp} is enabled but neither {sp}_MOSI nor {sp}_MISO is on a pin", ("periph", sp), "spi-data")
            br, actual = timing.spi_prescaler(clk.pclk or 1, s["speed_hz"])
            if actual < s["speed_hz"] * 0.5:
                add(WARNING, f"{sp}: the clock can only be {actual / 1e6:.3f} MHz at PCLK {clk.pclk / 1e6:g} MHz (wanted {s['speed_hz'] / 1e6:g} MHz)", ("periph", sp), "spi-speed")
            if s["mode"] == "slave" and not have["NSS"]:
                add(INFO, f"{sp} is a slave: {sp}_NSS is not on a pin (hardware chip select not used)", ("periph", sp), "spi-nss")
        elif any(have.values()):
            add(ERROR, f"{sp} signals are on pins but {sp} is disabled", ("periph", sp), "periph-off")
    for i2 in c.features["i2c"]:
        s = p.periph.get(i2)
        scl, sda = f"{i2}_SCL" in sigs, f"{i2}_SDA" in sigs
        if s and s.get("enabled"):
            if not (scl and sda):
                add(ERROR, f"{i2} needs both {i2}_SCL and {i2}_SDA on pins", ("periph", i2), "i2c-pins")
            if timing.i2c_timing(clk.pclk or 1, s["speed_hz"]) is None:
                need = 2 if s["speed_hz"] <= 100_000 else 4
                add(ERROR, f"{i2}: PCLK {clk.pclk / 1e6:g} MHz is too low for {s['speed_hz'] // 1000} kHz (needs at least {need} MHz)", ("periph", i2), "i2c-pclk")
            if s["speed_hz"] > 400_000:
                add(ERROR, f"{i2}: {s['speed_hz'] // 1000} kHz is above the 400 kHz fast mode", ("periph", i2), "i2c-speed")
        elif scl or sda:
            add(ERROR, f"{i2} signals are on pins but {i2} is disabled", ("periph", i2), "periph-off")
    adc = p.periph.get("ADC")
    if adc and adc.get("enabled"):
        if not p.adc_channels() and not (adc.get("temp") or adc.get("vref")):
            add(WARNING, "the ADC is enabled but no pin is in analog mode with an ADC channel and no internal channel is switched on", ("periph", "ADC"), "adc-none")
    for t, info in c.features["timers"].items():
        s = p.periph.get(t)
        chans = {k: v for k, v in sigs.items() if k.startswith(t + "_CH")}
        if s and s.get("enabled"):
            bits = info["bits"]
            r = timing.timer_for_freq(clk.tim_clk or 1, s["freq_hz"], bits)
            if r is None:
                add(ERROR, f"{t}: {s['freq_hz']:g} Hz cannot be made from the timer clock {clk.tim_clk / 1e6:g} MHz", ("periph", t), "tim-freq")
            elif r[3] > 1.0:
                add(WARNING, f"{t}: {s['freq_hz']:g} Hz becomes {r[2]:.3f} Hz ({r[3]:.2f} % off)", ("periph", t), "tim-freq")
            for k, v in s.get("duty", {}).items():
                if not 0 <= float(v) <= 100:
                    add(ERROR, f"{t} channel {k}: duty {v} % is outside 0..100", ("periph", t), "duty")
            if s.get("irq") and not r:
                pass
        elif chans:
            add(ERROR, f"{t} outputs are on pins but {t} is disabled", ("periph", t), "periph-off")
    iw = p.periph.get("IWDG")
    if iw and iw.get("enabled"):
        r = timing.iwdg_for_timeout(c.clock["lsi_hz"], iw["timeout_ms"])
        if r is None:
            add(ERROR, f"IWDG: {iw['timeout_ms']} ms is longer than the watchdog can count", ("periph", "IWDG"), "iwdg")
        elif abs(r[2] - iw["timeout_ms"]) / iw["timeout_ms"] > 0.05:
            add(WARNING, f"IWDG: the timeout will be {r[2]:.0f} ms instead of {iw['timeout_ms']} ms", ("periph", "IWDG"), "iwdg")
    # unsupported signals the generator does not configure
    for sig, ports in sigs.items():
        head = sig.split("_")[0]
        if head.startswith(("LPTIM", "RTC", "LED", "IR", "COMP")) or sig.endswith(("_CK", "_CTS", "_RTS", "_NSS")) and head.startswith("USART"):
            for q in ports:
                add(INFO, f"{sig} on {q}: the pin is set up, but this peripheral is not configured by Puya Studio (write its registers in main.c)", ("pin", q), "unconfigured")

    # ---------------------------------------------------------------- power
    idle = p.power.get("idle", "none")
    if idle == "stop" and not any(d["func"] == "exti" for d in pins.values()):
        add(WARNING, "stop mode is selected but no pin can wake the chip up (set a pin to 'GPIO input with interrupt')", ("power", None), "stop-wake")
    if idle in ("sleep", "stop") and iw and iw.get("enabled"):
        add(INFO, "the independent watchdog keeps running in sleep and stop mode and will reset the chip if it is not fed", ("power", None), "iwdg-sleep")

    # ---------------------------------------------------------------- generator limits
    try:
        codegen.Gen(p).files()
    except codegen.GenError as e:
        add(ERROR, f"cannot generate code: {e}", ("part", None), "gen")
    except KeyError as e:
        add(ERROR, f"cannot generate code: missing {e}", ("part", None), "gen")
    out.sort(key=lambda x: ORDER[x.severity])
    return out


def describe(d):
    if d["func"] == "af":
        return d["signal"]
    return {"gpio_in": "GPIO input", "gpio_out": "GPIO output", "analog": "analog", "exti": "interrupt input"}.get(d["func"], d["func"])
