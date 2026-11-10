"""The Problems list finds what it should find, and stays quiet on correct projects."""
import pytest

from puya_studio import chips, checks, examples
from puya_studio.project import Project


def codes(p, sev=None):
    return {x.code for x in checks.check(p) if sev is None or x.severity == sev}


def test_examples_have_no_errors():
    for chip in chips.CHIP_NAMES:
        for e in examples.EXAMPLES:
            try:
                p, sec, w = examples.build(e.id, chip)
            except examples.Unsupported:
                continue
            errs = [x for x in checks.check(p) if x.severity == "error"]
            assert not errs, (chip, e.id, errs)


def test_signal_on_two_pins():
    p = Project("py32f030")
    p.assign("PA2", "af:USART1_TX")
    p.assign("PA7", "af:USART1_TX")      # USART1_TX is also on PA7 (AF8)
    probs = [x for x in checks.check(p) if x.code == "dup-signal"]
    assert {x.target for x in probs} == {("pin", "PA2"), ("pin", "PA7")}


def test_dual_bonded_pad_used_twice():
    p = Project("py32f030", package="TSSOP20-F4")
    p.assign("PA5", "gpio_out")
    p.assign("PB4", "gpio_in")
    assert "shared-pad" in codes(p, "error")
    p.clear("PB4")
    assert "shared-pad" not in codes(p)


def test_clock_errors_jump_to_clock_page():
    p = Project("py32f003")
    p.clock.update(source="PLL", hsi_hz=24_000_000)
    probs = [x for x in checks.check(p) if x.code == "clock"]
    assert probs and all(x.target == ("clock", None) for x in probs)
    b = Project("py32f002b")
    b.clock["hsi_hz"] = 8_000_000
    assert "clock" in codes(b, "error")


def test_baud_error_and_impossible_baud():
    p = Project("py32f030")
    p.assign("PA2", "af:USART1_TX")
    p.clock.update(hsi_hz=8_000_000)
    p.periph["USART1"]["baud"] = 115200      # 8 MHz / 115200 = 69.4 -> 69: error 0.6 %
    assert "baud" not in codes(p)
    p.periph["USART1"]["baud"] = 1_000_000   # < 16 clocks per bit
    assert "baud" in codes(p, "error")
    p.periph["USART1"]["baud"] = 9600
    p.clock.update(hsidiv=128)               # PCLK 62.5 kHz
    assert "baud" in codes(p, "error")


def test_peripheral_needs_its_pins_and_enabled_state():
    p = Project("py32f030")
    p.assign("PA10", "af:USART1_TX")
    p.periph["USART1"]["enabled"] = False
    assert "periph-off" in codes(p, "error")
    p.periph["USART1"]["enabled"] = True
    p.clear("PA10")
    p.periph["USART1"] = {**p.periph.get("USART1", {"baud": 9600, "bits": 8, "parity": "none", "stop": 1}), "enabled": True}
    assert "usart-pins" in codes(p, "error")
    q = Project("py32f030")
    q.assign("PA2", "af:I2C1_SDA")                    # PA2 AF12 = I2C_SDA, PA3 AF12 = I2C_SCL
    assert "i2c-pins" in codes(q, "error")
    q.assign("PA3", "af:I2C1_SCL")
    assert "i2c-pins" not in codes(q)


def test_i2c_pins_are_open_drain_by_default():
    p = Project("py32f030")
    p.assign("PA3", "af:I2C1_SCL")
    assert p.pins["PA3"]["otype"] == "od"
    p.pins["PA3"]["otype"] = "pp"
    assert "i2c-od" in codes(p, "warning")


def test_exti_rules():
    p = Project("py32f030")
    p.assign("PA5", "exti")
    p.assign("PB5", "exti")
    assert "exti-conflict" in codes(p, "error")
    q = Project("py32f030")
    q.assign("PA12", "exti")                         # line 12, port A only: fine
    assert "exti-port" not in codes(q)
    r = Project("py32f002b")
    r.assign("PB7", "exti")
    assert "exti-port" not in codes(r)


def test_debug_and_reset_pin_warnings():
    p = Project("py32f030")
    p.assign("PA13", "gpio_out")
    p.assign("PF2", "gpio_in")
    c = codes(p, "warning")
    assert "swd-pin" in c and "nrst-pin" in c
    q = Project("py32f002b")
    q.assign("PB6", "gpio_out")
    assert "swd-pin" in codes(q, "warning")


def test_stop_needs_a_wake_source():
    p = Project("py32f030")
    p.power["idle"] = "stop"
    assert "stop-wake" in codes(p, "warning")
    p.assign("PA0", "exti")
    assert "stop-wake" not in codes(p)


def test_hse_pins_conflict():
    p = Project("py32f030")
    p.clock.update(source="HSE", hse_hz=8_000_000)
    p.assign("PF0", "gpio_out")
    assert "hse-pin" in codes(p, "error")


def test_timer_frequency_warning_and_error():
    p = Project("py32f030")
    p.assign("PA3", "af:TIM1_CH1")
    p.periph["TIM1"]["freq_hz"] = 1000.0
    assert "tim-freq" not in codes(p)
    p.periph["TIM1"]["freq_hz"] = 40_000_000.0       # 8 MHz clock cannot do 40 MHz
    assert "tim-freq" in codes(p, "error")


def test_problem_has_a_target_for_every_code():
    p = Project("py32f030")
    p.assign("PA13", "gpio_out")
    p.assign("PA2", "af:USART1_TX"); p.assign("PA7", "af:USART1_TX")
    for x in checks.check(p):
        assert x.target[0] in ("pin", "clock", "periph", "power", "part"), x
