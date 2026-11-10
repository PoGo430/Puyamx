"""Run the generated init code in a Cortex-M0 simulator (Unicorn) against a register stub and compare the
final register state with what the chip tables say it must be (computed here independently of the generator)."""
import tempfile

import pytest

from puya_studio import chips, codegen, examples, timing, toolchain
from sim_harness import Sim
from stress_project import build_full

pytestmark = pytest.mark.needs_gcc
pytest.importorskip("unicorn")

SIM_EXAMPLES = ["blink", "button_irq", "uart_hello", "uart_echo", "pwm_fade", "pwm_two", "timer_irq", "adc_pot",
                "adc_temp", "i2c_scan", "spi_loopback", "stop_wake", "watchdog", "clock_mco"]


def make(project, sections=None, keep=()):
    """Generate + compile; `keep` = functions the linker must not drop (helpers the example does not call)."""
    folder = tempfile.mkdtemp()
    codegen.generate(project, folder, sections)
    r = toolchain.build(folder, "fw", extra_cflags=[f"-Wl,-u,{k}" for k in keep])
    assert r.ok, r.log
    return Sim(project.chip, r.elf, r.bin, project.flash_kb, project.ram_kb)


def expected_pin_state(p):
    """{(letter, reg): (mask, value)} computed from the chip tables."""
    exp = {}
    for port, d in p.pins.items():
        n = int(port[2:])
        letter = port[1]
        mode = {"gpio_in": 0, "exti": 0, "gpio_out": 1, "af": 2, "analog": 3}[d["func"]]
        exp.setdefault((letter, "MODER"), []).append((3 << (2 * n), mode << (2 * n)))
        if d["func"] == "af":
            af = [a for a, s in p.chip.af_of(port).items() if s == d["signal"]][0]
            reg = "AFRL" if n < 8 else "AFRH"
            exp.setdefault((letter, reg), []).append((0xF << (4 * (n % 8)), af << (4 * (n % 8))))
        if d["func"] != "analog":
            pull = {"none": 0, "up": 1, "down": 2}[d["pull"]]
            exp.setdefault((letter, "PUPDR"), []).append((3 << (2 * n), pull << (2 * n)))
        if d["func"] in ("gpio_out", "af"):
            exp.setdefault((letter, "OTYPER"), []).append((1 << n, (1 << n) if d["otype"] == "od" else 0))
    return exp


def check_pins(sim, p):
    for (letter, reg), items in expected_pin_state(p).items():
        v = sim.get(f"GPIO{letter}", reg)
        for m, e in items:
            assert v & m == e, f"GPIO{letter}->{reg}: 0x{v:08X} & 0x{m:X} != 0x{e:X}"
        assert sim.field("RCC", "IOPENR", f"GPIO{letter}EN") == 1
    for port, d in p.pins.items():
        if d["func"] == "gpio_out":
            odr = sim.get(f"GPIO{port[1]}", "ODR") >> int(port[2:]) & 1
            assert odr == (1 if d["init"] == "high" else 0)


def check_clock(sim, p):
    r = timing.clock_tree(p.chip, p.clock)
    assert r.ok, r.problems
    assert sim.field("RCC", "CFGR", "SW") == timing.SW_CODES[p.clock["source"]]
    assert sim.field("RCC", "CFGR", "HPRE") == timing.AHB_CODES[p.clock["ahb_div"]]
    assert sim.field("RCC", "CFGR", "PPRE") == timing.APB_CODES[p.clock["apb_div"]]
    assert sim.field("RCC", "CR", "HSIDIV") == timing.HSIDIV_CODES[p.clock["hsidiv"]]
    assert sim.field("RCC", "ICSCR", "HSI_FS") == r.hsi_fs                 # factory word has the index in bits 18:16
    assert sim.field("RCC", "ICSCR", "HSI_TRIM") == 0x1000 + r.hsi_fs       # trim comes from the factory word
    if len(p.chip.clock["flash_latency"]) > 1:
        assert sim.field("FLASH", "ACR", "LATENCY") == r.flash_latency
    assert sim.uc.mem_read(0xE000E014, 4) == (r.hclk // p.clock["systick_hz"] - 1).to_bytes(4, "little")
    assert sim.get("RCC", "CR") is not None


def check_irqs(sim, p):
    g = codegen.Gen(p)
    iser = 0xE000E100
    bits = 0
    for w, v, s in sim.writes:
        if w == iser:
            bits |= v
    for name in g.irq_list():
        n = [k for k, v in p.chip.interrupts.items() if v == name][0]
        assert bits >> n & 1, f"{name} not enabled in the NVIC"


@pytest.mark.parametrize("chip_id", chips.CHIP_NAMES)
@pytest.mark.parametrize("ex", SIM_EXAMPLES)
def test_example_init(chip_id, ex):
    try:
        p, sec, wiring = examples.build(ex, chip_id)
    except examples.Unsupported:
        pytest.skip("not supported on this chip")
    sim = make(p, sec)
    sim.call("Init_All")
    check_pins(sim, p)
    check_clock(sim, p)
    check_irqs(sim, p)
    if ex == "uart_hello":
        u = [x for x in p.chip.features["usart"] if x in p.periph][0]
        brr = sim.get(u, "BRR")
        assert brr == round(timing.clock_tree(p.chip, p.clock).pclk / 115200)
        assert sim.get(u, "CR1") & 0x200C == 0x2008          # UE | TE, no RE (the example only sends)
    if ex == "i2c_scan":
        assert sim.get("I2C", "CR2") == timing.clock_tree(p.chip, p.clock).pclk // 1_000_000
        assert sim.get("I2C", "CR1") & 1
    if ex == "clock_mco":
        assert sim.field("RCC", "CFGR", "MCOSEL") == 1 and sim.field("RCC", "CFGR", "MCOPRE") == 3
    if ex == "watchdog":
        assert [w for w in sim.writes if w[0] == sim.addr("IWDG", "KR")][0][1] == 0xCCCC
        assert sim.get("IWDG", "RLR") > 0


@pytest.mark.parametrize("chip_id", chips.CHIP_NAMES)
def test_stress_project(chip_id):
    p = build_full(chip_id)
    sim = make(p)
    sim.call("Init_All")
    check_pins(sim, p)
    check_clock(sim, p)
    check_irqs(sim, p)
    assert sim.field("ADC", "CFGR2", "CKMODE") == timing.adc_clock_div(timing.clock_tree(p.chip, p.clock).pclk)[0]
    assert sim.get("ADC", "CR") & 1          # ADEN
    for t in p.chip.features["timers"]:
        if t in p.periph and p.periph[t].get("enabled"):
            g = codegen.Gen(p)
            psc, arr, actual, err = g.tim_values(t)
            assert sim.get(t, "PSC") == psc and sim.get(t, "ARR") == arr
            assert err < 1.0


@pytest.mark.parametrize("chip_id", chips.CHIP_NAMES)
def test_helpers_run(chip_id):
    p, sec, _ = examples.build("uart_hello", chip_id)
    u = [x for x in p.chip.features["usart"] if x in p.periph][0].lower()
    sim = make(p, sec, keep=[f"{u}_print_hex", f"{u}_print_u32"])
    sim.call("Init_All")
    sim.tx.clear()
    sim.call(f"{u}_print_u32", 1234567)
    assert bytes(sim.tx) == b"1234567"
    sim.tx.clear()
    sim.call(f"{u}_print_hex", 0xBEEF, 4)
    assert bytes(sim.tx) == b"BEEF"
    sim.tx.clear()
    sim.call(f"{u}_print_u32", 0)
    assert bytes(sim.tx) == b"0"


def test_pwm_duty_helper():
    p, sec, _ = examples.build("pwm_fade", "py32f030")
    sim = make(p, sec)
    sim.call("Init_All")
    t = [x for x in p.chip.features["timers"] if x in p.periph][0]
    sig = [s for s in p.signals_in_use()][0]
    ch = int(sig.split("_CH")[1].rstrip("N"))
    sim.call(f"{t.lower()}_set_duty_permille", ch, 250)
    arr = sim.get(t, "ARR")
    assert sim.get(t, f"CCR{ch}") == (arr + 1) * 250 // 1000


def test_adc_read_helper():
    p, sec, _ = examples.build("adc_pot", "py32f030")
    sim = make(p, sec)
    sim.call("Init_All")
    sim.regs[sim.addr("ADC", "DR")] = 1234
    assert sim.call("adc_read", 3) == 1234
    assert sim.get("ADC", "CHSELR") == 1 << 3


@pytest.mark.parametrize("chip_id,src,kw", [
    ("py32f003", "HSE", {"hse_hz": 16_000_000}),
    ("py32f003", "HSE", {"hse_hz": 8_000_000, "hse_bypass": True}),
    ("py32f030", "HSE", {"hse_hz": 32_000_000}),
    ("py32f030", "PLL", {"pll_src": "HSE", "hse_hz": 24_000_000}),
    ("py32f030", "LSI", {}),
    ("py32f002b", "LSI", {}),
    ("py32f002b", "HSE", {"hse_hz": 24_000_000, "hse_bypass": True}),
])
def test_other_clock_sources(chip_id, src, kw):
    p = build_full(chip_id)
    p.clock.update({"source": src, "hsi_hz": 8_000_000 if chip_id != "py32f002b" else 24_000_000, "systick_hz": 1000})
    p.clock.update(kw)
    if src == "LSI":                          # a 32 kHz clock cannot run I2C or fast UART: take them out
        for port in [q for q, d in p.pins.items() if d["func"] == "af" and d["signal"].startswith("I2C")]:
            p.clear(port)
        p.periph.pop("I2C1", None)
        if p.periph.get("USART1"):
            p.periph["USART1"]["baud"] = 1200
    r = timing.clock_tree(p.chip, p.clock)
    assert r.ok, r.problems
    sim = make(p)
    sim.call("Init_All")
    assert sim.field("RCC", "CFGR", "SW") == timing.SW_CODES[src]
    if src == "HSE" or kw.get("pll_src") == "HSE":
        hz = kw["hse_hz"]
        want = 1 if hz <= 8_000_000 else 2 if hz <= 16_000_000 else 3
        if "HSE_FREQ" in p.chip.reg("RCC", "ECSCR")["fields"]:
            assert sim.field("RCC", "ECSCR", "HSE_FREQ") == want             # never 0 = HSE off
        assert sim.get("RCC", "CR") & sim.mask("RCC", "CR", "HSEON" if "HSEON" in p.chip.reg("RCC", "CR")["fields"] else "HSEEN")
        if kw.get("hse_bypass"):
            assert sim.get("RCC", "CR") & sim.mask("RCC", "CR", "HSEBYP") if "HSEBYP" in p.chip.reg("RCC", "CR")["fields"] else True
    if src == "LSI":
        assert sim.get("RCC", "CSR") & 1
