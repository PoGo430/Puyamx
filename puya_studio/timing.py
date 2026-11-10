"""Clock tree and peripheral timing maths (no GUI, no I/O): used by the code generator,
the Problems list and the tests.

All formulas follow the reference manuals (RCC chapter 8, USART/SPI/I2C/TIM/ADC chapters);
where a formula is the usual STM32-style one and could not be confirmed against a chip
it is marked "verify on hardware" in the hardware checklist (README).
"""
from dataclasses import dataclass, field

AHB_CODES = {1: 0b0000, 2: 0b1000, 4: 0b1001, 8: 0b1010, 16: 0b1011, 64: 0b1100, 128: 0b1101, 256: 0b1110, 512: 0b1111}
APB_CODES = {1: 0b000, 2: 0b100, 4: 0b101, 8: 0b110, 16: 0b111}
HSIDIV_CODES = {1: 0, 2: 1, 4: 2, 8: 3, 16: 4, 32: 5, 64: 6, 128: 7}
SW_CODES = {"HSI": 0, "HSE": 1, "PLL": 2, "LSI": 3, "LSE": 4}


def default_clock(chip):
    """Reset-like default: HSI at the chip's default frequency, no dividers."""
    hsi = chip.clock["hsi"]
    return {"source": "HSI", "hsi_hz": hsi["default_after_reset_hz"], "hsidiv": 1, "hse_hz": 8_000_000,
            "hse_bypass": False, "pll_src": "HSI", "ahb_div": 1, "apb_div": 1, "mco": None, "systick_hz": 1000}


@dataclass
class ClockResult:
    sysclk: int = 0
    hclk: int = 0
    pclk: int = 0
    tim_clk: int = 0
    hsi_fs: int = 0
    flash_latency: int = 0
    problems: list = field(default_factory=list)      # (severity, text)  severity: "error" | "warning"
    ok: bool = True


def clock_tree(chip, cfg):
    r = ClockResult()
    hsi = chip.clock["hsi"]
    src = cfg["source"]
    freqs = {int(k): v for k, v in hsi["freqs_hz"].items()}
    hz_to_fs = {v: k for k, v in freqs.items()}
    r.hsi_fs = hz_to_fs.get(cfg["hsi_hz"], 0)
    if cfg["hsi_hz"] not in hz_to_fs:
        r.problems.append(("error", f"HSI of {cfg['hsi_hz'] / 1e6:g} MHz does not exist on {chip.name}; choose "
                           + ", ".join(f"{v / 1e6:g}" for v in sorted(freqs.values())) + " MHz"))
    if cfg["hsidiv"] not in HSIDIV_CODES:
        r.problems.append(("error", "HSI divider must be 1, 2, 4 ... 128"))
    hsisys = cfg["hsi_hz"] // max(1, cfg["hsidiv"])
    if src == "HSI":
        r.sysclk = hsisys
    elif src == "HSE":
        if chip.clock["hse"].get("crystal_hz") is None and not cfg.get("hse_bypass"):
            r.problems.append(("error", f"{chip.name} has no crystal oscillator: HSE can only be an external clock input"))
        lo_hi = chip.clock["hse"].get("crystal_hz")
        if lo_hi and not cfg.get("hse_bypass") and not (lo_hi[0] <= cfg["hse_hz"] <= lo_hi[1]):
            r.problems.append(("error", f"HSE crystal {cfg['hse_hz'] / 1e6:g} MHz outside {lo_hi[0] / 1e6:g}..{lo_hi[1] / 1e6:g} MHz"))
        r.sysclk = cfg["hse_hz"]
    elif src == "PLL":
        pll = chip.clock["pll"]
        if not pll:
            r.problems.append(("error", f"{chip.name} has no PLL"))
            r.sysclk = hsisys
        else:
            base = cfg["hsi_hz"] if cfg.get("pll_src", "HSI") == "HSI" else cfg["hse_hz"]
            r.sysclk = base * pll["multiplier"]
            if cfg.get("pll_src") == "HSE":
                lo_hi = chip.clock["hse"].get("crystal_hz")
                if lo_hi and not cfg.get("hse_bypass") and not (lo_hi[0] <= cfg["hse_hz"] <= lo_hi[1]):
                    r.problems.append(("error", f"HSE crystal {cfg['hse_hz'] / 1e6:g} MHz outside {lo_hi[0] / 1e6:g}..{lo_hi[1] / 1e6:g} MHz"))
    elif src == "LSI":
        r.sysclk = chip.clock["lsi_hz"]
    elif src == "LSE":
        r.sysclk = chip.clock["lse_hz"]
    else:
        r.problems.append(("error", f"unknown clock source {src}"))
    if cfg["ahb_div"] not in AHB_CODES:
        r.problems.append(("error", "AHB divider must be 1, 2, 4, 8, 16, 64, 128, 256 or 512"))
    if cfg["apb_div"] not in APB_CODES:
        r.problems.append(("error", "APB divider must be 1, 2, 4, 8 or 16"))
    r.hclk = r.sysclk // max(1, cfg["ahb_div"])
    r.pclk = r.hclk // max(1, cfg["apb_div"])
    r.tim_clk = r.pclk if cfg["apb_div"] == 1 else r.pclk * 2        # RM figure 8-1: "if APB prescaler = 1 x1 else x2"
    limit = chip.max_hz
    if r.sysclk > limit:
        r.problems.append(("error", f"SYSCLK {r.sysclk / 1e6:g} MHz is above the {chip.name} maximum of {limit / 1e6:g} MHz"))
    if r.hclk > limit:
        r.problems.append(("error", f"HCLK {r.hclk / 1e6:g} MHz is above the maximum of {limit / 1e6:g} MHz"))
    r.flash_latency = 0
    for step in chip.clock["flash_latency"]:
        r.flash_latency = step["latency"]
        if r.sysclk <= step["max_hz"]:
            break
    if cfg.get("systick_hz") and r.hclk and r.hclk // cfg["systick_hz"] > 0xFFFFFF:
        r.problems.append(("error", "SysTick tick too slow for this HCLK (24-bit reload)"))
    r.ok = not any(s == "error" for s, _ in r.problems)
    return r


# --------------------------------------------------------------------------- UART
def usart_brr(pclk, baud):
    """16x oversampling: USARTDIV = pclk / (16 * baud); BRR = mantissa<<4 | fraction (= round(pclk / baud))."""
    brr = int(round(pclk / baud))
    if brr < 16 or brr > 0xFFFF:
        return None, 0.0, 100.0
    actual = pclk / brr
    return brr, actual, abs(actual - baud) / baud * 100.0


# --------------------------------------------------------------------------- SPI
def spi_prescaler(pclk, target_hz):
    """BR field: fPCLK / 2^(BR+1).  Returns (BR, actual_hz) with the highest speed not above target."""
    for br in range(8):
        hz = pclk / (2 ** (br + 1))
        if hz <= target_hz:
            return br, hz
    return 7, pclk / 256


# --------------------------------------------------------------------------- I2C
def i2c_timing(pclk, scl_hz):
    """STM32-style I2C master timing (standard mode <= 100 kHz, fast mode <= 400 kHz, DUTY=0).
    Returns dict(FREQ, CCR, TRISE, fast, actual_hz) or None if PCLK is too low."""
    mhz = pclk // 1_000_000
    if scl_hz <= 100_000:
        if mhz < 2:
            return None
        ccr = max(4, int(round(pclk / (2 * scl_hz))))
        return {"FREQ": mhz, "CCR": ccr, "TRISE": mhz + 1, "fast": False, "actual_hz": pclk / (2 * ccr)}
    if mhz < 4:
        return None
    ccr = max(1, int(round(pclk / (3 * scl_hz))))
    return {"FREQ": mhz, "CCR": ccr, "TRISE": (mhz * 300) // 1000 + 1, "fast": True, "actual_hz": pclk / (3 * ccr)}


# --------------------------------------------------------------------------- timers
def timer_for_freq(tim_clk, freq_hz, bits=16):
    """Prescaler and auto-reload for an update frequency: returns (PSC, ARR, actual_hz, err_percent)."""
    maxv = (1 << bits)
    if freq_hz <= 0 or tim_clk <= 0:
        return None
    n = tim_clk / freq_hz
    if abs(n - round(n)) < 1e-9 and round(n) >= 2:       # look for an exact split first (prescaler * reload = n)
        total = int(round(n))
        lo = max(1, -(-total // maxv))
        for d in range(lo, min(lo + 256, total + 1)):
            if total % d == 0 and total // d <= maxv and d <= 0x10000:
                return d - 1, total // d - 1, tim_clk / total, 0.0
    psc = 0
    ticks = tim_clk / freq_hz
    if ticks > maxv:
        psc = int(-(-ticks // maxv)) - 1
    arr = int(round(tim_clk / ((psc + 1) * freq_hz))) - 1
    if arr < 1:
        return None
    if arr > maxv - 1:
        psc += 1
        arr = int(round(tim_clk / ((psc + 1) * freq_hz))) - 1
    if psc > 0xFFFF or arr > maxv - 1:
        return None
    actual = tim_clk / ((psc + 1) * (arr + 1))
    return psc, arr, actual, abs(actual - freq_hz) / freq_hz * 100.0


def pwm_ccr(arr, duty_percent):
    return int(round((arr + 1) * duty_percent / 100.0))


# --------------------------------------------------------------------------- IWDG
IWDG_DIVIDERS = {0: 4, 1: 8, 2: 16, 3: 32, 4: 64, 5: 128, 6: 256}


def iwdg_for_timeout(lsi_hz, timeout_ms):
    """-> (PR, RLR, actual_ms).  The 12-bit down-counter runs (RLR + 1) ticks of lsi/divider."""
    for pr, div in IWDG_DIVIDERS.items():
        ticks = timeout_ms / 1000.0 * lsi_hz / div
        if round(ticks) <= 4096:
            rlr = min(max(int(round(ticks)) - 1, 0), 4095)
            return pr, rlr, (rlr + 1) * div / lsi_hz * 1000.0
    return None


# --------------------------------------------------------------------------- ADC
def adc_clock_div(pclk, max_hz=12_000_000):
    """CKMODE[3:0] for PCLK/n with the ADC clock not above max_hz -> (code, adc_hz)."""
    for code, n in enumerate((1, 2, 4, 8, 16, 32, 64)):
        if pclk // n <= max_hz:
            return code, pclk // n
    return 6, pclk // 64
