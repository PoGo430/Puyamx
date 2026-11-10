"""A project that uses (nearly) everything the generator can do, for each chip."""
from puya_studio.project import Project
from puya_studio import codegen, toolchain, chips

def pick(chip, sig, used):
    for port, af in chip.port_for_signal(sig):
        if port not in used:
            return port
    return None

def build_full(chipname):
    p = Project(chipname); p.name = "stress"
    c = p.chip; used = set()
    def put(sig):
        port = pick(c, sig, used)
        if port:
            p.assign(port, "af:" + sig); used.add(port)
    for sig in ("USART1_TX","USART1_RX","SPI1_SCK","SPI1_MISO","SPI1_MOSI","I2C1_SCL","I2C1_SDA","TIM1_CH1","TIM1_CH2N","TIM14_CH1","TIM3_CH1","MCO"):
        if sig in {s for pp in c.ports for s in c.af_of(pp).values()}:
            put(sig)
    for x in sorted(c.ports):
        if any(a.startswith("ADC_IN") for a in c.analog_of(x)) and x not in used and len(p.adc_channels())<2:
            p.assign(x,"analog",label="POT"); used.add(x)
    free = [x for x in sorted(c.ports, key=lambda q:(q[1],int(q[2:]))) if x not in used and x not in ("PF4",)]
    p.assign(free[0], "gpio_out", label="LED"); used.add(free[0])
    p.assign(free[1], "gpio_in", label="BTN", pull="up"); used.add(free[1])
    ex=[x for x in free[2:] if int(x[2:])<=7 and x[1] in "AB"]
    p.assign(ex[0], "exti", label="WAKE", pull="up", edge="falling"); used.add(ex[0])
    p.periph["ADC"] = {"enabled": True, "resolution": 12, "sample": 7, "temp": True, "vref": True, "continuous": False}
    if "USART1" in p.periph: p.periph["USART1"]["irq_rx"] = True
    if "TIM14" in p.periph: p.periph["TIM14"]["irq"] = True
    p.periph["IWDG"] = {"enabled": True, "timeout_ms": 1000}
    p.clock.update({"source":"PLL","pll_src":"HSI","hsi_hz":24_000_000} if c.clock["pll"] else {"source":"HSE","hse_hz":16_000_000} if chipname=="py32f003" else {"source":"HSI"})
    p.irq["extra"] = {"ADC_COMP": 1}
    return p

