"""Chip database checks.

The expected values below were typed again by hand from the datasheet drawings / tables and
the reference-manual memory maps (not generated from the database), so a wrong extraction,
a changed builder or a hand edit of the JSON is caught.

Documents: PY32F030 DS Rev2.2 (and Rev1.4 EN), PY32F003 DS Rev1.9 (and Rev1.2 EN),
PY32F002B DS V0.8, RM v1.2 / v1.2 / v0.4.
"""
import pytest

from puya_studio import chips


def pins_of(chip, pkg):
    return {p.n: p.label for p in chip.pins(pkg)}


def expect(chip, pkg, mapping):
    got = pins_of(chip, pkg)
    for n, label in mapping.items():
        assert got[n] == label, f"{chip.name} {pkg} pin {n}: {got[n]} != {label}"


# ------------------------------------------------------------------ pinouts (drawings)
def test_f030_lqfp32_k1():
    c = chips.load("py32f030")
    expect(c, "LQFP32-K1", {1: "VCC", 2: "PF0", 3: "PF1", 4: "PF2", 5: "PF3", 6: "PA0", 7: "PA1", 8: "PA2", 9: "PA3",
                            10: "PA4", 11: "PA5", 12: "PA6", 13: "PA7", 14: "PB0", 15: "PB1", 16: "VSS", 17: "VCC",
                            18: "PA8", 19: "PA9", 20: "PA10", 21: "PA11", 22: "PA12", 23: "PA13", 24: "PA14",
                            25: "PA15", 26: "PB3", 27: "PB4", 28: "PB5", 29: "PB6", 30: "PB7", 31: "PF4", 32: "VSS"})


def test_f030_lqfp32_k2_differs_from_k1():
    c = chips.load("py32f030")
    expect(c, "LQFP32-K2", {1: "VCC", 17: "PB2", 32: "PB8", 18: "PA8", 16: "VSS"})


def test_f030_tssop20_variants():
    c = chips.load("py32f030")
    expect(c, "TSSOP20-F1", {1: "PF0", 2: "PF1", 3: "PF2", 4: "PF3", 5: "PA2", 6: "PA3", 7: "VSS", 8: "PB2", 9: "VCC",
                             10: "PA8", 11: "PA9", 12: "PA10", 13: "PA11", 14: "PA13", 15: "PA14", 16: "PB4",
                             17: "PB5", 18: "PB6", 19: "PB7", 20: "PF4"})
    expect(c, "TSSOP20-F2", {1: "PA2", 2: "PA3", 3: "PA4", 4: "PA5", 5: "PA6", 6: "PA7", 7: "VSS", 8: "PA12", 9: "VCC",
                             10: "PA13", 11: "PA14", 12: "PB5", 13: "PB6", 14: "PB7", 15: "PF4", 16: "PF0", 17: "PF1",
                             18: "PF2", 19: "PA0", 20: "PA1"})
    expect(c, "TSSOP20-F4", {1: "PA4", 2: "PA6", 3: "PA7", 4: "PB0", 5: "PB1", 6: "VSS", 7: "VCC", 8: "PA8", 9: "PA9",
                             10: "PA10", 11: "PA13", 12: "PA14", 13: "PA5/PB4", 14: "PF0", 15: "PF1", 16: "PF2",
                             17: "PA0", 18: "PA1", 19: "PA2", 20: "PA3"})


def test_f030_dual_bonded_pad():
    c = chips.load("py32f030")
    pin = [p for p in c.pins("TSSOP20-F4") if p.n == 13][0]
    assert pin.shared and pin.ports == ["PA5", "PB4"]


def test_f030_package_list():
    c = chips.load("py32f030")
    assert set(c.packages) >= {"LQFP32-K1", "LQFP32-K2", "SSOP24-E1", "SSOP24-E2", "QFN20-F1", "QFN20-F2",
                               "QFN32-K2", "TSSOP20-F1", "TSSOP20-F2", "TSSOP20-F3", "TSSOP20-F4"}
    assert c.packages["LQFP32-K1"]["pin_count"] == 32
    assert c.packages["SSOP24-E1"]["pin_count"] == 24
    assert c.packages["QFN20-F1"]["exposed_pad"] is True


def test_f003_tssop20_variants():
    c = chips.load("py32f003")
    expect(c, "TSSOP20-F3", {1: "PA1", 2: "PA2", 3: "PA3", 4: "PA4", 5: "PF0", 6: "PA7", 7: "VSS", 8: "PB2", 9: "VCC",
                             10: "PA12", 11: "PA13", 12: "PA14", 13: "PB3", 14: "PB4", 15: "PB5", 16: "PB6",
                             17: "PB7", 18: "PF4", 19: "PF2", 20: "PA0"})
    expect(c, "TSSOP20-F4", {1: "PF1", 2: "PA2/PF2", 3: "PA3", 4: "PA4", 5: "PA5", 6: "PA6", 7: "VSS", 8: "PB2",
                             9: "VCC", 10: "PA9", 11: "PA10", 12: "PA11", 13: "PA12", 14: "PA15", 15: "PB3",
                             16: "PB4", 17: "PA13", 18: "PA14", 19: "PA7", 20: "PF0"})
    expect(c, "TSSOP20-F5", {1: "PA2", 6: "PA7", 7: "VSS", 8: "PB2", 9: "VCC", 10: "PA13", 11: "PA14", 12: "PB5",
                             13: "PB6", 14: "PB8", 15: "PF4", 16: "PF0", 17: "PF1", 18: "PF2", 19: "PF3", 20: "PA1"})
    expect(c, "TSSOP20-F6", {1: "VCC", 2: "VSS", 3: "PB1", 4: "PA10", 5: "PA11", 6: "PA12", 7: "PA14", 8: "PA13",
                             9: "PB0", 10: "PA5", 11: "PF0", 12: "PF1", 13: "PF2", 14: "PA0", 15: "PA1", 16: "PA2",
                             17: "PA3", 18: "PA4", 19: "PA6", 20: "PA7"})
    expect(c, "SOP20-F1", {1: "PA4", 2: "PA5", 3: "PA6", 4: "PA7", 5: "PB0", 6: "PB1", 7: "VSS", 8: "PB2", 9: "VCC",
                            10: "PA12", 11: "PA13", 12: "PA14", 13: "PF4", 14: "PA3", 15: "PA2", 16: "PF0", 17: "PF1",
                            18: "PF2", 19: "PA0", 20: "PA1"})


def test_f002b_packages():
    c = chips.load("py32f002b")
    expect(c, "TSSOP20-F1", {1: "PA5", 2: "PA6", 3: "PA7", 4: "PC0", 5: "PC1", 6: "PB7", 7: "VSS", 8: "PB6", 9: "VCC",
                             10: "PB5", 11: "PB4", 12: "PB3", 13: "PB2", 14: "PB1", 15: "PB0", 16: "PA0", 17: "PA1",
                             18: "PA2", 19: "PA3", 20: "PA4"})
    expect(c, "SOP16-W1", {1: "VCC", 2: "PB4", 3: "PB3", 4: "PB2", 5: "PB1", 6: "PB0", 7: "PA0", 8: "PA1", 9: "PA4",
                            10: "PB6", 11: "PA2", 12: "PA6", 13: "PA7/PC0", 14: "PC1", 15: "PB7", 16: "VSS"})
    expect(c, "SOP14-D1", {1: "VCC", 2: "PB2", 3: "PB1", 4: "PB0", 5: "PA0", 6: "PA1", 7: "PA2", 8: "PB6", 9: "PA4",
                            10: "PA6", 11: "PA7", 12: "PC1", 13: "PB7/PC0", 14: "VSS"})


# ------------------------------------------------------------------ alternate functions (tables)
F030_AF = {  # DS Rev2.2 tables 3-5 .. 3-7 (retyped)
    "PA0": {0: "SPI2_SCK", 1: "USART1_CTS", 3: "LED_DATA_B", 4: "USART2_CTS", 7: "COMP1_OUT", 9: "USART2_TX",
            10: "SPI1_MISO", 13: "TIM1_CH3", 14: "TIM1_CH1N", 15: "IR_OUT"},
    "PA4": {0: "SPI1_NSS", 1: "USART1_CK", 2: "SPI2_MOSI", 3: "LED_DATA_F", 4: "TIM14_CH1", 5: "USART2_CK",
            7: "EVENTOUT", 9: "USART2_TX", 13: "TIM3_CH3", 15: "RTC_OUT"},
    "PA13": {0: "SWDIO", 1: "IR_OUT", 7: "EVENTOUT", 8: "USART1_RX", 10: "SPI1_MISO", 13: "TIM1_CH2", 15: "MCO"},
    "PA14": {0: "SWCLK", 1: "USART1_TX", 4: "USART2_TX", 7: "EVENTOUT", 15: "MCO"},
    "PA15": {0: "SPI1_NSS", 1: "USART1_RX", 4: "USART2_RX", 6: "LED_COM0", 7: "EVENTOUT"},
    "PB1": {0: "TIM14_CH1", 1: "TIM3_CH4", 2: "TIM1_CH3N", 7: "EVENTOUT"},
    "PB3": {0: "SPI1_SCK", 1: "TIM1_CH2", 3: "USART1_RTS", 4: "USART2_RTS", 6: "LED_COM1", 7: "EVENTOUT"},
    "PB8": {1: "SPI2_SCK", 2: "TIM16_CH1", 3: "LED_DATA_A", 4: "USART2_TX", 6: "I2C1_SCL", 7: "EVENTOUT",
            8: "USART1_TX", 11: "SPI2_NSS", 12: "I2C1_SDA", 13: "TIM17_CH1", 15: "IR_OUT"},
    "PF0": {2: "TIM14_CH1", 3: "SPI2_SCK", 4: "USART2_RX", 8: "USART1_RX", 9: "USART2_TX", 12: "I2C1_SDA"},
    "PF3": {0: "USART1_TX", 3: "SPI2_MISO", 4: "USART2_TX", 10: "SPI1_NSS", 13: "TIM3_CH3", 15: "RTC_OUT"},
}


@pytest.mark.parametrize("port", sorted(F030_AF))
def test_f030_af(port):
    assert chips.load("py32f030").af_of(port) == F030_AF[port]


def test_f003_af_follows_f030_but_without_spi2_and_led():
    c = chips.load("py32f003")
    # PB5-PB7 typed from DS Rev1.2 EN table 4-4
    assert c.af_of("PB6") == {0: "USART1_TX", 1: "TIM1_CH3", 2: "TIM16_CH1N", 4: "USART2_TX", 5: "LPTIM1_ETR",
                              6: "I2C1_SCL", 7: "EVENTOUT"}
    assert c.af_of("PB7") == {0: "USART1_RX", 2: "TIM17_CH1N", 4: "USART2_RX", 6: "I2C1_SDA", 7: "EVENTOUT"}
    assert c.af_of("PA6")[0] == "SPI1_MISO" and 3 not in c.af_of("PA6")      # LED_DATA_DP dropped
    assert c.af_of("PA0") == {1: "USART1_CTS", 4: "USART2_CTS", 7: "COMP1_OUT", 9: "USART2_TX", 10: "SPI1_MISO",
                              13: "TIM1_CH3", 14: "TIM1_CH1N", 15: "IR_OUT"}
    allsig = {s for p in c.ports for s in c.af_of(p).values()}
    assert not [s for s in allsig if s.startswith(("SPI2", "LED"))]


F002B_AF = {  # DS V0.8 tables 3-4 .. 3-6 (retyped, instance numbers added by the loader)
    "PA0": {0: "SPI1_MOSI", 2: "TIM1_CH1"},
    "PA2": {0: "SWC", 1: "USART1_RX", 2: "TIM1_CH4", 4: "COMP2_OUT", 6: "I2C1_SCL"},
    "PA6": {0: "SPI1_NSS", 1: "USART1_TX", 7: "EVENTOUT"},
    "PA7": {0: "SPI1_MOSI", 1: "USART1_TX", 2: "TIM1_CH4", 3: "USART1_RX", 4: "MCO"},
    "PB6": {0: "SWD", 1: "USART1_TX", 2: "SPI1_MISO", 6: "I2C1_SDA"},
    "PC0": {0: "SWD", 2: "TIM1_CH1N", 7: "EVENTOUT"},
    "PC1": {0: "SPI1_MISO"},
}


@pytest.mark.parametrize("port", sorted(F002B_AF))
def test_f002b_af(port):
    assert chips.load("py32f002b").af_of(port) == F002B_AF[port]


# ------------------------------------------------------------------ analog functions
def test_adc_channels_each_once():
    for name, n in (("py32f030", 10), ("py32f003", 10), ("py32f002b", 8)):
        c = chips.load(name)
        ch = sorted(int(a[6:]) for p in c.ports for a in c.analog_of(p) if a.startswith("ADC_IN"))
        assert ch == list(range(n)), (name, ch)


def test_adc_pins():
    c = chips.load("py32f030")
    assert [c.analog_of(p)[0] for p in ("PA0", "PA7", "PB0", "PB1")] == ["ADC_IN0", "ADC_IN7", "ADC_IN8", "ADC_IN9"]
    b = chips.load("py32f002b")      # RM v0.4 ADC channel table
    got = {int(a[6:]): p for p in b.ports for a in b.analog_of(p) if a.startswith("ADC_IN")}
    assert got == {0: "PB1", 1: "PA3", 2: "PA4", 3: "PA6", 4: "PA7", 5: "PC0", 6: "PB6", 7: "PB0"}


# ------------------------------------------------------------------ memory map / registers (RM)
BASES_F030 = {"TIM3": 0x40000400, "TIM14": 0x40002000, "LED": 0x40002400, "RTC": 0x40002800, "WWDG": 0x40002C00,
              "IWDG": 0x40003000, "SPI2": 0x40003800, "USART2": 0x40004400, "I2C": 0x40005400, "PWR": 0x40007000,
              "LPTIM": 0x40007C00, "SYSCFG": 0x40010000, "COMP1": 0x40010200, "ADC": 0x40012400, "TIM1": 0x40012C00,
              "SPI1": 0x40013000, "USART1": 0x40013800, "TIM16": 0x40014400, "TIM17": 0x40014800,
              "DBGMCU": 0x40015800, "DMA": 0x40020000, "RCC": 0x40021000, "EXTI": 0x40021800, "FLASH": 0x40022000,
              "CRC": 0x40023000, "GPIOA": 0x50000000, "GPIOB": 0x50000400, "GPIOF": 0x50001400}


@pytest.mark.parametrize("periph,base", sorted(BASES_F030.items()))
def test_f030_bases(periph, base):
    assert chips.load("py32f030").peripherals[periph]["base"] == base


def test_f003_has_no_spi2_or_led():
    c = chips.load("py32f003")
    assert "SPI2" not in c.peripherals and "LED" not in c.peripherals
    assert c.peripherals["USART2"]["base"] == 0x40004400


def test_f002b_peripherals():
    c = chips.load("py32f002b")
    assert c.peripherals["GPIOC"]["base"] == 0x50000800
    assert not [p for p in ("USART2", "SPI2", "TIM3", "TIM16", "TIM17", "DMA", "RTC", "WWDG") if p in c.peripherals]
    assert c.peripherals["USART1"]["base"] == 0x40013800 and c.peripherals["SPI1"]["base"] == 0x40013000


def test_common_register_offsets():       # RM register tables
    for name in chips.CHIP_NAMES:
        c = chips.load(name)
        assert c.reg("GPIOA", "MODER")["off"] == 0x00
        assert c.reg("GPIOA", "IDR")["off"] == 0x10 and c.reg("GPIOA", "ODR")["off"] == 0x14
        assert c.reg("GPIOA", "BSRR")["off"] == 0x18
        assert c.reg("RCC", "CR")["off"] == 0x00 and c.reg("RCC", "ICSCR")["off"] == 0x04
        assert c.reg("RCC", "CFGR")["off"] == 0x08
        assert c.reg("FLASH", "ACR")["off"] == 0x00 and c.reg("FLASH", "KEYR")["off"] == 0x08
        assert c.reg("RCC", "ICSCR")["reset"] == 0x00FF10FF


def test_rcc_bits():
    c = chips.load("py32f030")
    assert c.reg("RCC", "CR")["fields"]["HSION"] == [8, 1]
    assert c.reg("RCC", "CR")["fields"]["HSIRDY"] == [10, 1]
    assert c.reg("RCC", "CR")["fields"]["HSEON"] == [16, 1]
    assert c.reg("RCC", "CFGR")["fields"]["HPRE"] == [8, 4]
    assert c.reg("RCC", "CFGR")["fields"]["PPRE"] == [12, 3]
    assert c.reg("RCC", "CFGR")["fields"]["SW"] == [0, 3]
    assert c.reg("RCC", "ICSCR")["fields"]["HSI_FS"] == [13, 3]
    assert c.reg("RCC", "ICSCR")["fields"]["HSI_TRIM"] == [0, 13]
    assert c.reg("RCC", "PLLCFGR")["fields"]["PLLSRC"] == [0, 1]
    assert c.reg("FLASH", "ACR")["fields"]["LATENCY"] == [0, 1]


# ------------------------------------------------------------------ interrupts (RM vector tables)
IRQ_F030 = {0: "WWDG", 1: "PVD", 2: "RTC", 3: "FLASH", 4: "RCC", 5: "EXTI0_1", 6: "EXTI2_3", 7: "EXTI4_15",
            9: "DMA_Channel1", 10: "DMA_Channel2_3", 12: "ADC_COMP", 13: "TIM1_BRK_UP_TRG_COM", 14: "TIM1_CC",
            16: "TIM3", 17: "LPTIM1", 19: "TIM14", 21: "TIM16", 22: "TIM17", 23: "I2C1", 25: "SPI1", 26: "SPI2",
            27: "USART1", 28: "USART2", 30: "LED"}


def test_f030_irqs():
    assert chips.load("py32f030").interrupts == IRQ_F030


def test_f003_irqs():
    exp = {k: v for k, v in IRQ_F030.items() if v not in ("SPI2", "LED")}
    assert chips.load("py32f003").interrupts == exp


def test_f002b_irqs():
    exp = {3: "FLASH", 4: "RCC", 5: "EXTI0_1", 6: "EXTI2_3", 7: "EXTI4_15", 12: "ADC_COMP",
           13: "TIM1_BRK_UP_TRG_COM", 14: "TIM1_CC", 17: "LPTIM1", 19: "TIM14", 23: "I2C1", 25: "SPI1", 27: "USART1"}
    assert chips.load("py32f002b").interrupts == exp


# ------------------------------------------------------------------ device facts
def test_limits():
    assert chips.load("py32f030").max_hz == 48_000_000
    assert chips.load("py32f003").max_hz == 32_000_000
    assert chips.load("py32f002b").max_hz == 24_000_000
    assert chips.load("py32f002b").clock["pll"] is None and chips.load("py32f003").clock["pll"] is None
    assert chips.load("py32f030").clock["pll"]["multiplier"] == 2
    assert chips.load("py32f030").clock["flash_latency"] == [{"max_hz": 24_000_000, "latency": 0},
                                                              {"max_hz": 48_000_000, "latency": 1}]


def test_memory_sizes():
    f030 = {p["part"]: (p["flash_kb"], p["ram_kb"]) for p in chips.load("py32f030").parts}
    assert f030["PY32F030K18T6"] == (64, 8) and f030["PY32F030K26T6"] == (32, 4)
    assert f030["PY32F030F27P6"] == (48, 6) and f030["PY32F030E14M6"] == (16, 2)
    f003 = {p["part"]: (p["flash_kb"], p["ram_kb"]) for p in chips.load("py32f003").parts}
    assert f003["PY32F003F18P6"] == (64, 8) and f003["PY32F003F16S6"] == (32, 4)
    assert "PY32F003F17P6" not in f003            # no 48 KB part in the ordering table
    f002 = {p["part"]: (p["flash_kb"], p["ram_kb"]) for p in chips.load("py32f002b").parts}
    assert f002["PY32F002BF15P6"] == (24, 3) and f002["PY32F002BW15S6"] == (24, 3)


def test_option_bytes():
    c030 = chips.load("py32f030").option_bytes
    assert c030["words"]["user"]["addr"] == 0x1FFF0E80 and c030["words"]["user"]["production"] == 0x4155BEAA
    assert c030["rdp"]["unprotected"] == 0xAA
    b = chips.load("py32f002b").option_bytes
    assert b["words"]["user"]["addr"] == 0x1FFF0080 and b["words"]["wrp"]["production"] == 0xFFC0003F
    assert b["rdp"] is None


def test_sources_and_notes_present():
    for c in chips.all_chips():
        assert c.d["sources"] and c.notes
        assert all(w in c.d["sources"][0]["doc"] for w in ("Datasheet",))


# ------------------------------------------------------------------ structural consistency
@pytest.mark.parametrize("name", chips.CHIP_NAMES)
def test_packages_are_consistent(name):
    c = chips.load(name)
    used = set()
    for pid, pk in c.packages.items():
        pins = c.pins(pid)
        nums = [p.n for p in pins]
        assert nums == sorted(set(nums)), pid
        assert nums[:pk["pin_count"]] == list(range(1, pk["pin_count"] + 1)), pid
        assert sum(1 for p in pins if p.kind == "power" and p.name == "VSS") >= 1, pid
        assert sum(1 for p in pins if p.kind == "power" and p.name == "VCC") >= 1, pid
        for p in pins:
            for port in p.ports:
                assert port in c.ports, (pid, port)
                used.add(port)
    unused = set(c.ports) - used           # in the AF table but not bonded out in any listed package
    assert unused == ({"PA8"} if name == "py32f003" else set()), unused


@pytest.mark.parametrize("name", chips.CHIP_NAMES)
def test_every_signal_has_a_peripheral(name):
    c = chips.load(name)
    periph = set(c.peripherals) | {"I2C1", "LPTIM1", "COMP1", "COMP2"}
    for p in c.ports:
        for af, sig in c.af_of(p).items():
            head = sig.split("_")[0]
            if head in ("EVENTOUT", "MCO", "SWDIO", "SWCLK", "SWD", "SWC", "IR", "RTC", "LED"):
                continue
            assert head in periph, (name, p, sig)
            assert 0 <= af <= 15


@pytest.mark.parametrize("name", chips.CHIP_NAMES)
def test_interrupts_exist_for_peripherals(name):
    c = chips.load(name)
    irq = set(c.interrupts.values())
    for t in c.features["timers"]:
        if t == "TIM1":
            assert "TIM1_CC" in irq
        else:
            assert t in irq, t
    for u in c.features["usart"] + c.features["spi"]:
        assert u in irq, u
