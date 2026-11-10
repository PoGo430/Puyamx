"""Examples shown in the New Project dialog.

Each example sets up a project (pins are chosen automatically for the package the user picked, so the
wiring text is always right for that package) and supplies the code for the USER CODE sections.
`build(chip_id, ...)` returns (project, user_sections, wiring_lines) or raises Unsupported with the reason.
"""
from dataclasses import dataclass, field

from . import chips, timing
from .project import Project

PWM_SIGNALS = ["TIM3_CH1", "TIM3_CH2", "TIM3_CH3", "TIM3_CH4", "TIM14_CH1", "TIM1_CH1", "TIM1_CH2", "TIM1_CH3", "TIM1_CH4",
               "TIM16_CH1", "TIM17_CH1"]
AVOID = {"SWDIO", "SWCLK", "SWD", "SWC"}


class Unsupported(Exception):
    pass


@dataclass
class Example:
    id: str
    title: str
    description: str
    setup: callable
    code: dict                       # {file: {section: C code}}
    needs: str = ""                  # short text of what the example needs


class Ctx:
    """Helper that picks free pins of the project's package."""

    def __init__(self, project):
        self.p = project
        self.chip = project.chip
        self.ports = project.package_ports()
        self.wiring = []
        self.labels = {}

    def reserved(self):
        c = self.chip
        res = set(c.d["swd"].values()) | {c.d["nrst"]}
        if c.d.get("boot0"):
            res.add(c.d["boot0"])
        return res

    def free(self, port):
        return port in self.ports and port not in self.p.pins and port not in self.reserved()

    def gpio(self, func, label, **opts):
        order = sorted((x for x in self.ports if self.free(x) and not self.is_special(x)), key=lambda x: (x[1] == "F", x[1], int(x[2:])))
        if not order:
            raise Unsupported("no free pin left in this package")
        port = order[0]
        self.p.assign(port, func, label=label, **opts)
        self.labels[label] = port
        return port

    def is_special(self, port):
        a = self.chip.analog_of(port)
        return any(x.startswith(("OSC", "EXT")) for x in a)

    def signals(self, sigs, labels=None, **opts):
        """Assign several alternate-function signals to distinct free pins (small backtracking search)."""
        cands = []
        for s in sigs:
            c = [(port, af) for port, af in self.chip.port_for_signal(s) if self.free(port)]
            if not c:
                raise Unsupported(f"{s} is not available on a free pin of this package")
            cands.append(c)
        order = sorted(range(len(sigs)), key=lambda i: len(cands[i]))
        chosen = {}

        def rec(k, used):
            if k == len(order):
                return True
            i = order[k]
            for port, af in cands[i]:
                if port in used:
                    continue
                chosen[i] = port
                if rec(k + 1, used | {port}):
                    return True
            return False
        if not rec(0, set()):
            raise Unsupported("the needed signals cannot all be placed on this package: " + ", ".join(sigs))
        for i, s in enumerate(sigs):
            lab = (labels or {}).get(s, "")
            self.p.assign(chosen[i], "af:" + s, label=lab, **opts)
            if lab:
                self.labels[lab] = chosen[i]
        return {s: chosen[i] for i, s in enumerate(sigs)}

    def pwm_pin(self, label="PWM_OUT"):
        for s in PWM_SIGNALS:
            if s.split("_")[0] not in self.chip.features["timers"]:
                continue
            try:
                return s, self.signals([s], {s: label})[s]
            except Unsupported:
                continue
        raise Unsupported("no timer output pin available on this package")

    def uart(self, rx=False, label_tx="UART_TX", label_rx="UART_RX"):
        for u in self.chip.features["usart"]:
            sigs = [f"{u}_TX"] + ([f"{u}_RX"] if rx else [])
            try:
                got = self.signals(sigs, {f"{u}_TX": label_tx, f"{u}_RX": label_rx})
                return u, got
            except Unsupported:
                continue
        raise Unsupported("no USART pins available on this package")

    def adc_pin(self, label="POT"):
        for ch, port in sorted(((int(a[6:]), x) for x in self.ports for a in self.chip.analog_of(x) if a.startswith("ADC_IN") and self.free(x))):
            self.p.assign(port, "analog", label=label)
            self.labels[label] = port
            return ch, port
        raise Unsupported("no ADC input pin available on this package")

    def exti_pin(self, label="BTN", edge="falling"):
        order = sorted((x for x in self.ports if self.free(x) and not self.is_special(x)), key=lambda x: (x[1], int(x[2:])))
        for port in order:
            n = int(port[2:])
            allowed = self.chip.exti.get(str(n))
            if allowed and port[1] in allowed and not any(q.startswith("PB") is False and int(q[2:]) == n for q in self.p.pins if q != port and self.p.pins[q]["func"] == "exti"):
                self.p.assign(port, "exti", label=label, pull="up", edge=edge)
                self.labels[label] = port
                return port
        raise Unsupported("no pin with an interrupt line is free on this package")

    def pin_text(self, port):
        for pin in self.chip.pins(self.p.package):
            if port in pin.ports:
                return f"{port} (pin {pin.n})"
        return port


# ---------------------------------------------------------------------------------------------- setups
def s_blink(x):
    x.gpio("gpio_out", "LED", init="low")
    x.wiring.append(f"LED: {x.pin_text(x.labels['LED'])} -> resistor (330 Ohm) -> LED -> GND")


def s_button_led(x):
    x.gpio("gpio_out", "LED")
    x.gpio("gpio_in", "BTN", pull="up")
    x.wiring += [f"LED: {x.pin_text(x.labels['LED'])} -> resistor -> LED -> GND",
                 f"Button: {x.pin_text(x.labels['BTN'])} -> button -> GND (internal pull-up is on)"]


def s_button_irq(x):
    x.gpio("gpio_out", "LED")
    x.exti_pin("BTN")
    x.wiring += [f"LED: {x.pin_text(x.labels['LED'])} -> resistor -> LED -> GND",
                 f"Button: {x.pin_text(x.labels['BTN'])} -> button -> GND"]


def s_uart_hello(x):
    x.gpio("gpio_out", "LED")
    u, got = x.uart(rx=False)
    x.uart_inst = u
    x.wiring += [f"LED: {x.pin_text(x.labels['LED'])} -> resistor -> LED -> GND",
                 f"{u}_TX: {x.pin_text(got[u + '_TX'])} -> RX of a USB-serial adapter; GND to GND; terminal 115200 8N1"]


def s_uart_echo(x):
    u, got = x.uart(rx=True)
    x.uart_inst = u
    x.p.periph[u]["irq_rx"] = True
    x.gpio("gpio_out", "LED")
    x.wiring += [f"{u}_TX: {x.pin_text(got[u + '_TX'])} -> RX of a USB-serial adapter",
                 f"{u}_RX: {x.pin_text(got[u + '_RX'])} -> TX of the adapter; GND to GND; terminal 115200 8N1",
                 f"LED: {x.pin_text(x.labels['LED'])} -> resistor -> LED -> GND (flashes on every received byte)"]


def s_pwm_fade(x):
    sig, port = x.pwm_pin("PWM_OUT")
    t = sig.split("_")[0]
    x.p.periph[t]["freq_hz"] = 1000.0
    x.p.periph[t]["duty"] = {sig.split("_CH")[1]: 0.0}
    x.wiring.append(f"LED: {x.pin_text(port)} ({sig}) -> resistor -> LED -> GND")


def s_pwm_two(x):
    done = 0
    for t in ("TIM3", "TIM1", "TIM14", "TIM16", "TIM17"):
        if t not in x.chip.features["timers"]:
            continue
        n = x.chip.features["timers"][t]["channels"]
        sigs = [f"{t}_CH{i}" for i in range(1, n + 1)]
        for pair in ((sigs[0], sigs[1]),) if len(sigs) > 1 else ():
            try:
                got = x.signals(list(pair), {pair[0]: "PWM_A", pair[1]: "PWM_B"})
            except Unsupported:
                continue
            x.p.periph[t]["freq_hz"] = 2000.0
            x.p.periph[t]["duty"] = {"1": 0.0, "2": 100.0}
            x.wiring += [f"LED A: {x.pin_text(got[pair[0]])} ({pair[0]}) -> resistor -> LED -> GND",
                         f"LED B: {x.pin_text(got[pair[1]])} ({pair[1]}) -> resistor -> LED -> GND"]
            return
    raise Unsupported("needs two channels of one timer on free pins")


def s_timer_irq(x):
    x.gpio("gpio_out", "LED")
    t = "TIM14" if "TIM14" in x.chip.features["timers"] else "TIM1"
    x.p.periph[t] = {"enabled": True, "freq_hz": 2.0, "duty": {}, "irq": True, "prio": 2, "dead_time": 0}
    x.timer = t
    x.wiring.append(f"LED: {x.pin_text(x.labels['LED'])} -> resistor -> LED -> GND ({t} interrupt toggles it at 2 Hz)")


def s_adc_pot(x):
    ch, port = x.adc_pin("POT")
    u, got = x.uart()
    x.uart_inst = u
    x.adc_ch = ch
    x.p.periph["ADC"] = {"enabled": True, "resolution": 12, "sample": 7, "temp": False, "vref": False, "continuous": False}
    x.wiring += [f"Potentiometer wiper: {x.pin_text(port)} (ADC_IN{ch}); ends to VCC and GND",
                 f"{u}_TX: {x.pin_text(got[u + '_TX'])} -> RX of a USB-serial adapter; terminal 115200 8N1"]


def s_adc_temp(x):
    u, got = x.uart()
    x.uart_inst = u
    x.p.periph["ADC"] = {"enabled": True, "resolution": 12, "sample": 7, "temp": True, "vref": True, "continuous": False}
    x.wiring.append(f"{u}_TX: {x.pin_text(got[u + '_TX'])} -> RX of a USB-serial adapter; terminal 115200 8N1 (no other parts)")


def s_i2c_scan(x):
    x.signals(["I2C1_SCL", "I2C1_SDA"], {"I2C1_SCL": "SCL", "I2C1_SDA": "SDA"})
    u, got = x.uart()
    x.uart_inst = u
    x.wiring += [f"SCL: {x.pin_text(x.labels['SCL'])}, SDA: {x.pin_text(x.labels['SDA'])} -> your I2C device(s), 4.7 kOhm pull-ups to VCC",
                 f"{u}_TX: {x.pin_text(got[u + '_TX'])} -> RX of a USB-serial adapter; terminal 115200 8N1"]


def s_spi_loopback(x):
    got = x.signals(["SPI1_SCK", "SPI1_MISO", "SPI1_MOSI"], {"SPI1_SCK": "SCK", "SPI1_MISO": "MISO", "SPI1_MOSI": "MOSI"})
    x.gpio("gpio_out", "LED")
    x.p.periph["SPI1"].update({"speed_hz": 1_000_000})
    x.wiring += [f"Connect MOSI {x.pin_text(got['SPI1_MOSI'])} to MISO {x.pin_text(got['SPI1_MISO'])} with a wire (SCK {x.pin_text(got['SPI1_SCK'])} stays free)",
                 f"LED: {x.pin_text(x.labels['LED'])} -> resistor -> LED -> GND (on = loop-back test passed)"]


def s_sleep_wake(x):
    x.gpio("gpio_out", "LED")
    x.exti_pin("BTN")
    x.wiring += [f"LED: {x.pin_text(x.labels['LED'])} -> resistor -> LED -> GND",
                 f"Button: {x.pin_text(x.labels['BTN'])} -> button -> GND (wakes the chip from sleep)"]


def s_stop_wake(x):
    s_sleep_wake(x)
    x.wiring.append("Measure the supply current while the LED is off: the chip is in stop mode.")


def s_watchdog(x):
    x.gpio("gpio_out", "LED")
    x.gpio("gpio_in", "BTN", pull="up")
    x.p.periph["IWDG"] = {"enabled": True, "timeout_ms": 1000}
    x.wiring += [f"LED: {x.pin_text(x.labels['LED'])} -> resistor -> LED -> GND",
                 f"Button: {x.pin_text(x.labels['BTN'])} -> button -> GND (hold it: the watchdog stops being fed and the chip resets)"]


def s_clock_mco(x):
    if "MCO" not in {s for p in x.ports for s in x.chip.af_of(p).values()}:
        raise Unsupported("no MCO pin")
    got = x.signals(["MCO"], {"MCO": "MCO_OUT"})
    x.p.clock["mco"] = {"src": "SYSCLK", "div": 8}
    x.wiring.append(f"MCO: {x.pin_text(got['MCO'])}: SYSCLK / 8 square wave; measure with a scope or frequency counter")


# ---------------------------------------------------------------------------------------------- code
def uart_banner(u):
    return f"    {u}_puts(\"\\r\\n{{name}} ready\\r\\n\");"


C = {}
C["blink"] = {"main.c": {"3": "        LED_TOGGLE();\n        delay_ms(500);"}}
C["blink_millis"] = {"main.c": {"PV_main": "static uint32_t last;", "3": """        if (millis() - last >= 250) {
            last = millis();
            LED_TOGGLE();
        }"""}}
C["button_led"] = {"main.c": {"3": """        if (BTN_READ() == 0) {     /* pressed (pulled to GND) */
            LED_HIGH();
        } else {
            LED_LOW();
        }"""}}
C["button_irq"] = {"interrupts.c": {"IRQ_EXTI{n}": "        LED_TOGGLE();"}, "main.c": {"3": "        enter_sleep();    /* the LED toggles in the interrupt */"}}
C["uart_hello"] = {"main.c": {"PV_main": "static uint32_t n;", "2": "    {u}_puts(\"\\r\\nHello from {chip}!\\r\\n\");",
                              "3": """        {u}_puts("count = ");
        {u}_print_u32(n++);
        {u}_puts("\\r\\n");
        LED_TOGGLE();
        delay_ms(1000);"""}}
C["uart_echo"] = {"main.c": {"2": "    {u}_puts(\"echo ready\\r\\n\");", "3": """        int c = {u}_getc_nb();
        if (c >= 0) {
            {u}_putc((char) c);
            LED_TOGGLE();
        }"""}}
C["pwm_fade"] = {"main.c": {"PV_main": "static int level, dir = 1;", "3": """        PWM_OUT_SET_DUTY((uint16_t) level);   /* 0..1000 permille */
        level += dir * 5;
        if (level >= 1000) { level = 1000; dir = -1; }
        if (level <= 0) { level = 0; dir = 1; }
        delay_ms(5);"""}}
C["pwm_two"] = {"main.c": {"PV_main": "static int level, dir = 1;", "3": """        PWM_A_SET_DUTY((uint16_t) level);          /* A goes up while B goes down */
        PWM_B_SET_DUTY((uint16_t) (1000 - level));
        level += dir * 5;
        if (level >= 1000) { level = 1000; dir = -1; }
        if (level <= 0) { level = 0; dir = 1; }
        delay_ms(5);"""}}
C["timer_irq"] = {"interrupts.c": {"IRQ_{timer}_update": "        LED_TOGGLE();"}, "main.c": {"3": "        enter_sleep();    /* everything happens in the timer interrupt */"}}
C["adc_pot"] = {"main.c": {"3": """        {u}_puts("ADC_IN{ch} = ");
        {u}_print_u32(adc_read({ch}));
        {u}_puts(" (0..4095)\\r\\n");
        delay_ms(500);"""}}
C["adc_temp"] = {"main.c": {"3": """        {u}_puts("temperature sensor raw = ");
        {u}_print_u32(adc_read({ts}));
        {u}_puts(", VREFINT raw = ");
        {u}_print_u32(adc_read({vr}));
        {u}_puts("\\r\\n");
        delay_ms(1000);"""}}
C["i2c_scan"] = {"main.c": {"2": "    {u}_puts(\"\\r\\nI2C scan\\r\\n\");", "3": """        uint8_t a, found = 0;
        for (a = 8; a < 120; a++) {
            if (i2c1_probe(a) == 0) {
                {u}_puts("found 0x");
                {u}_print_hex(a, 2);
                {u}_puts("\\r\\n");
                found++;
            }
        }
        {u}_puts(found ? "scan done\\r\\n" : "nothing found\\r\\n");
        delay_ms(3000);"""}}
C["spi_loopback"] = {"main.c": {"3": """        uint8_t i, ok = 1;
        for (i = 0; i < 16; i++) {
            if (spi1_transfer((uint8_t) (0xA0 + i)) != (uint8_t) (0xA0 + i)) { ok = 0; }
        }
        LED_WRITE(ok);
        delay_ms(500);"""}}
C["sleep_wake"] = {"interrupts.c": {"IRQ_EXTI{n}": "        LED_TOGGLE();"}, "main.c": {"3": """        delay_ms(2000);      /* LED shows every wake-up; between presses the core sleeps */
        enter_sleep();"""}}
C["stop_wake"] = {"interrupts.c": {"IRQ_EXTI{n}": "        /* only wakes the chip */"}, "main.c": {"3": """        LED_HIGH();
        delay_ms(200);
        LED_LOW();
        enter_stop();        /* wakes up when the button is pressed */"""}}
C["watchdog"] = {"main.c": {"2": "    LED_HIGH();\n    delay_ms(200);\n    LED_LOW();      /* one flash after every start / reset */",
                            "3": """        if (BTN_READ() != 0) {    /* released: keep feeding the watchdog */
            IWDG_KICK();
        }
        delay_ms(100);"""}}
C["clock_mco"] = {"main.c": {"3": "        __NOP();"}}

EXAMPLES = [
    Example("blink", "Blink", "Toggles an LED once a second.", s_blink, C["blink"], "1 pin"),
    Example("blink_millis", "Blink with millis()", "Blinks without blocking: uses millis() instead of delay_ms().", s_blink, C["blink_millis"], "1 pin"),
    Example("button_led", "Button controls LED", "The LED is on while the button is pressed.", s_button_led, C["button_led"], "2 pins"),
    Example("button_irq", "Button interrupt", "A button press toggles the LED from an EXTI interrupt; the core sleeps in between.", s_button_irq, C["button_irq"], "2 pins"),
    Example("uart_hello", "UART: Hello World", "Prints a counter over the serial port once a second.", s_uart_hello, C["uart_hello"], "UART TX"),
    Example("uart_echo", "UART: echo (interrupt)", "Sends every received character back; receiving uses an interrupt and a ring buffer.", s_uart_echo, C["uart_echo"], "UART TX+RX"),
    Example("pwm_fade", "PWM: fade an LED", "A timer output fades an LED up and down.", s_pwm_fade, C["pwm_fade"], "1 timer pin"),
    Example("pwm_two", "PWM: two channels", "Two PWM channels of one timer fade in opposite directions.", s_pwm_two, C["pwm_two"], "2 timer pins"),
    Example("timer_irq", "Timer interrupt", "A timer interrupt toggles an LED at 2 Hz.", s_timer_irq, C["timer_irq"], "1 pin"),
    Example("adc_pot", "ADC: read a potentiometer", "Prints the ADC value of an analog pin over the serial port.", s_adc_pot, C["adc_pot"], "ADC pin + UART"),
    Example("adc_temp", "ADC: internal sensors", "Prints raw temperature-sensor and VREFINT readings (no external parts).", s_adc_temp, C["adc_temp"], "UART TX"),
    Example("i2c_scan", "I2C: bus scan", "Finds I2C devices and prints their addresses over the serial port.", s_i2c_scan, C["i2c_scan"], "I2C + UART"),
    Example("spi_loopback", "SPI: loop-back test", "Sends bytes on MOSI and reads them back on MISO (wire them together).", s_spi_loopback, C["spi_loopback"], "SPI pins + 1 pin"),
    Example("sleep_wake", "Sleep and wake up", "The core sleeps (WFI) and a button wakes it up.", s_sleep_wake, C["sleep_wake"], "2 pins"),
    Example("stop_wake", "Stop mode and wake up", "Lowest-power stop mode; a button wakes the chip up.", s_stop_wake, C["stop_wake"], "2 pins"),
    Example("watchdog", "Independent watchdog", "Feeds the IWDG; hold the button to see the chip reset.", s_watchdog, C["watchdog"], "2 pins"),
    Example("clock_mco", "Clock output (MCO)", "Outputs SYSCLK/8 on a pin so you can measure the clock.", s_clock_mco, C["clock_mco"], "MCO pin"),
]
BY_ID = {e.id: e for e in EXAMPLES}


def subst(text, mapping):
    """Replace {key} placeholders (C braces stay untouched)."""
    for k, v in mapping.items():
        text = text.replace("{" + k + "}", str(v))
    return text


def supported(example, chip_id, part=None, package=None):
    """-> (True, "") or (False, reason)"""
    try:
        build(example.id, chip_id, part, package)
        return True, ""
    except Unsupported as e:
        return False, str(e)


def build(example_id, chip_id, part=None, package=None, flash_kb=None):
    """-> (project, user_sections, wiring_lines)"""
    ex = BY_ID[example_id]
    p = Project(chip_id)
    if part:
        p.set_part(part)
    elif package:
        p.set_package(package)
    if flash_kb:
        p.set_memory(flash_kb)
    p.name = ex.id
    x = Ctx(p)
    ex.setup(x)
    fmt = {"chip": p.chip.name, "name": ex.title, "u": getattr(x, "uart_inst", "usart1").lower(),
           "ch": getattr(x, "adc_ch", 0), "timer": getattr(x, "timer", "TIM14"), "ts": p.chip.adc["internal"]["TS_VIN"],
           "vr": p.chip.adc["internal"]["VREFINT"]}
    sections = {}
    for fname, secs in ex.code.items():
        for name, body in secs.items():
            if "{n}" in name:                                   # one handler section per EXTI line
                for port, d in p.pins.items():
                    if d["func"] == "exti":
                        sections.setdefault(fname, {})[name.replace("{n}", port[2:])] = body.replace("{n}", port[2:]) + "\n"
                continue
            body = subst(body, fmt)
            name = subst(name, fmt)
            sections.setdefault(fname, {})[name] = body + "\n"
    return p, sections, x.wiring
