"""Clock tree, baud rate, SPI/I2C/timer/watchdog maths (no hardware, no compiler)."""
import pytest

from puya_studio import chips, timing


def cfg(chip, **kw):
    c = timing.default_clock(chip)
    c.update(kw)
    return c


def test_f030_pll_48mhz():
    c = chips.load("py32f030")
    r = timing.clock_tree(c, cfg(c, source="PLL", pll_src="HSI", hsi_hz=24_000_000))
    assert r.ok and (r.sysclk, r.hclk, r.pclk, r.tim_clk) == (48_000_000, 48_000_000, 48_000_000, 48_000_000)
    assert r.flash_latency == 1 and r.hsi_fs == 4


def test_timer_clock_doubles_when_apb_divided():
    c = chips.load("py32f030")
    r = timing.clock_tree(c, cfg(c, source="PLL", hsi_hz=24_000_000, apb_div=2))
    assert r.pclk == 24_000_000 and r.tim_clk == 48_000_000


def test_default_is_8mhz_hsi():
    for n in ("py32f030", "py32f003"):
        c = chips.load(n)
        r = timing.clock_tree(c, timing.default_clock(c))
        assert r.sysclk == 8_000_000 and r.flash_latency == 0 and r.ok
    b = chips.load("py32f002b")
    assert timing.clock_tree(b, timing.default_clock(b)).sysclk == 24_000_000


def test_limits_are_errors():
    c = chips.load("py32f003")
    r = timing.clock_tree(c, cfg(c, source="PLL", hsi_hz=24_000_000))
    assert not r.ok and any("no PLL" in t for _, t in r.problems)
    r = timing.clock_tree(c, cfg(c, source="HSE", hse_hz=33_000_000))
    assert not r.ok
    b = chips.load("py32f002b")
    r = timing.clock_tree(b, cfg(b, hsi_hz=16_000_000))
    assert not r.ok and any("does not exist" in t for _, t in r.problems)
    r = timing.clock_tree(b, cfg(b, source="HSE", hse_hz=8_000_000))
    assert not r.ok
    r = timing.clock_tree(b, cfg(b, source="HSE", hse_hz=24_000_000, hse_bypass=True))
    assert r.ok
    f = chips.load("py32f030")
    assert not timing.clock_tree(f, cfg(f, source="HSE", hse_hz=40_000_000)).ok


def test_hsi_divider_and_ahb():
    c = chips.load("py32f030")
    r = timing.clock_tree(c, cfg(c, hsi_hz=24_000_000, hsidiv=4, ahb_div=2, apb_div=4))
    assert (r.sysclk, r.hclk, r.pclk) == (6_000_000, 3_000_000, 750_000)


def test_baud():
    brr, actual, err = timing.usart_brr(48_000_000, 115200)
    assert brr == 417 and abs(actual - 115107.9) < 0.1 and err < 0.1
    brr, actual, err = timing.usart_brr(8_000_000, 9600)
    assert brr == 833 and err < 0.05
    assert timing.usart_brr(1_000_000, 1_000_000)[0] is None            # < 16 clocks per bit
    assert timing.usart_brr(24_000_000, 921600)[2] < 3.0


def test_spi():
    assert timing.spi_prescaler(48_000_000, 1_000_000) == (5, 750_000)
    assert timing.spi_prescaler(8_000_000, 4_000_000) == (0, 4_000_000)
    assert timing.spi_prescaler(8_000_000, 100) == (7, 8_000_000 / 256)


def test_i2c():
    t = timing.i2c_timing(48_000_000, 100_000)
    assert (t["FREQ"], t["CCR"], t["TRISE"], t["fast"]) == (48, 240, 49, False)
    t = timing.i2c_timing(8_000_000, 100_000)
    assert (t["CCR"], t["TRISE"]) == (40, 9)
    t = timing.i2c_timing(48_000_000, 400_000)
    assert (t["CCR"], t["TRISE"], t["fast"]) == (40, 15, True)
    assert timing.i2c_timing(1_000_000, 100_000) is None
    assert timing.i2c_timing(3_000_000, 400_000) is None


def test_timer():
    assert timing.timer_for_freq(48_000_000, 1000)[:2] == (0, 47999)
    psc, arr, actual, err = timing.timer_for_freq(48_000_000, 1)
    assert (psc + 1) * (arr + 1) == 48_000_000 and err == 0 and arr < 65536     # exact split found (e.g. 750 x 64000)
    psc, arr, actual, err = timing.timer_for_freq(8_000_000, 2)
    assert (psc + 1) * (arr + 1) == 4_000_000 and err == 0
    psc, arr, actual, err = timing.timer_for_freq(48_000_000, 0.7)
    assert err < 0.01 and arr < 65536
    assert timing.timer_for_freq(1000, 1_000_000) is None
    assert timing.pwm_ccr(999, 25) == 250


def test_iwdg():
    assert timing.iwdg_for_timeout(32768, 1000) == (1, 4095, 1000.0)
    pr, rlr, ms = timing.iwdg_for_timeout(32768, 10)
    assert pr == 0 and abs(ms - 10) < 0.5
    assert timing.iwdg_for_timeout(32768, 100000) is None


def test_adc_clock():
    assert timing.adc_clock_div(48_000_000) == (2, 12_000_000)
    assert timing.adc_clock_div(8_000_000) == (0, 8_000_000)
    assert timing.adc_clock_div(24_000_000)[1] <= 12_000_000
