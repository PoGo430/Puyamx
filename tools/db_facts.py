"""Facts typed in from the Puya documents (datasheet DS, reference manual RM) for build_db.py.

Every table says where it comes from.  Anything NOT from a Puya document is marked
source="community" or "inferred" in the output, and the reason is listed in "notes".
"""
import re

HZ = 1_000_000

EXTRA_ALIAS = {
    "OSCIN": "OSC_IN", "OSC_IN": "OSC_IN", "OSCOUT": "OSC_OUT", "OSC_OUT": "OSC_OUT", "OSCOT": "OSC_OUT",
    "OSC32IN": "OSC32_IN", "OSC32OUT": "OSC32_OUT", "OS32IN": "OSC32_IN",
    "NRST": "NRST", "BOOT0": "BOOT0", "BOOT": "BOOT0", "SWD": "SWDIO", "SWC": "SWCLK", "SCK": "SPI1_SCK",
}

# which instances exist (DS "Features", RM memory map, official SVD) ------------------
FEATURES = {
    "py32f030": {
        "gpio_ports": ["A", "B", "F"], "usart": ["USART1", "USART2"], "spi": ["SPI1", "SPI2"], "i2c": ["I2C1"],
        "timers": {"TIM1": {"bits": 16, "kind": "advanced", "channels": 4, "complementary": 3, "bkin": True},
                   "TIM3": {"bits": 16, "kind": "general", "channels": 4},
                   "TIM14": {"bits": 16, "kind": "general", "channels": 1},
                   "TIM16": {"bits": 16, "kind": "general", "channels": 1, "complementary": 1, "bkin": True},
                   "TIM17": {"bits": 16, "kind": "general", "channels": 1, "complementary": 1, "bkin": True}},
        "lptim": ["LPTIM1"], "watchdogs": ["IWDG", "WWDG"], "rtc": True, "dma_channels": 3, "crc": True,
        "adc": {"bits": 12, "external_channels": 10}, "comp": ["COMP1", "COMP2"], "led_controller": True, "ir": True,
        "usart_lowpower": False,
    },
    "py32f003": {
        "gpio_ports": ["A", "B", "F"], "usart": ["USART1", "USART2"], "spi": ["SPI1"], "i2c": ["I2C1"],
        "timers": {"TIM1": {"bits": 16, "kind": "advanced", "channels": 4, "complementary": 3, "bkin": True},
                   "TIM3": {"bits": 16, "kind": "general", "channels": 4},
                   "TIM14": {"bits": 16, "kind": "general", "channels": 1},
                   "TIM16": {"bits": 16, "kind": "general", "channels": 1, "complementary": 1, "bkin": True},
                   "TIM17": {"bits": 16, "kind": "general", "channels": 1, "complementary": 1, "bkin": True}},
        "lptim": ["LPTIM1"], "watchdogs": ["IWDG", "WWDG"], "rtc": True, "dma_channels": 3, "crc": True,
        "adc": {"bits": 12, "external_channels": 10}, "comp": ["COMP1", "COMP2"], "led_controller": False, "ir": True,
    },
    "py32f002b": {
        "gpio_ports": ["A", "B", "C"], "usart": ["USART1"], "spi": ["SPI1"], "i2c": ["I2C1"],
        "timers": {"TIM1": {"bits": 16, "kind": "advanced", "channels": 4, "complementary": 3, "bkin": True},
                   "TIM14": {"bits": 16, "kind": "general", "channels": 1}},
        "lptim": ["LPTIM1"], "watchdogs": ["IWDG"], "rtc": False, "dma_channels": 0, "crc": True,
        "adc": {"bits": 12, "external_channels": 8}, "comp": ["COMP1", "COMP2"], "led_controller": False, "ir": False,
    },
}

# Signal prefixes that are really on a chip (used to drop copy-pasted rows in the datasheet tables)
def allowed_prefixes(chip):
    f = FEATURES[chip]
    ok = set(f["usart"]) | set(f["spi"]) | set(f["timers"]) | set(f["comp"]) | {"EVENTOUT", "MCO", "SWDIO", "SWCLK", "SWD", "SWC"}
    ok |= {"I2C", "I2C1", "LPTIM", "LPTIM1"}
    if f.get("rtc"):
        ok.add("RTC")
    if f.get("led_controller"):
        ok.add("LED")
    if f.get("ir"):
        ok.add("IR")
    return ok


def canon(chip, sig):
    """Datasheet signal name -> canonical name (instance numbers added, CMP -> COMP)."""
    for a, b in SIGNAL_ALIAS[chip].items():
        if sig.startswith(a):
            return b + sig[len(a):]
    return sig


def prefix(sig):
    return sig.split("_")[0]


SIGNAL_ALIAS = {
    "py32f030": {"I2C_": "I2C1_", "LPTIM_": "LPTIM1_"},
    "py32f003": {"I2C_": "I2C1_", "LPTIM_": "LPTIM1_"},
    "py32f002b": {"SPI_": "SPI1_", "USART_": "USART1_", "I2C_": "I2C1_", "CMP": "COMP", "LPTIM_": "LPTIM1_"},
}

# Memory (RM "Memory map" + "Flash" chapters, DS ordering information) ---------------
MEM_DIGITS = {  # ordering code digit -> (flash KB, RAM KB); DS7 "User code memory size"; RAM from DS product tables
    "py32f030": {"3": (8, 1), "4": (16, 2), "6": (32, 4), "7": (48, 6), "8": (64, 8)},
    "py32f003": {"4": (16, 2), "6": (32, 4), "8": (64, 8)},
    "py32f002b": {"5": (24, 3)},
}

CLOCKS = {
    # RM RCC chapter (8.6), DS "Clock system"; flash latency RM FLASH_ACR
    "py32f030": {
        "sysclk_max_hz": 48 * HZ,
        "hsi": {"select_reg": "RCC_ICSCR.HSI_FS", "freqs_hz": {"0": 4 * HZ, "1": 8 * HZ, "2": 16 * HZ, "3": 22_120_000, "4": 24 * HZ},
                "default_after_reset_hz": 8 * HZ, "trim_addr": {"0": 0x1FFF0F00, "1": 0x1FFF0F04, "2": 0x1FFF0F08, "3": 0x1FFF0F0C, "4": 0x1FFF0F10},
                "div": [1, 2, 4, 8, 16, 32, 64, 128]},
        "hse": {"crystal_hz": [4 * HZ, 32 * HZ], "bypass": True, "freq_field": "RCC_ECSCR.HSE_FREQ"},
        "pll": {"multiplier": 2, "sources": ["HSI", "HSE"], "select_reg": "RCC_PLLCFGR.PLLSRC", "output_max_hz": 48 * HZ},
        "lsi_hz": 32768, "lse_hz": 32768, "ahb_div": [1, 2, 4, 8, 16, 64, 128, 256, 512], "apb_div": [1, 2, 4, 8, 16],
        "flash_latency": [{"max_hz": 24 * HZ, "latency": 0}, {"max_hz": 48 * HZ, "latency": 1}],
        "mco": {"sel": {"1": "SYSCLK", "3": "HSI", "4": "HSE", "5": "PLL", "6": "LSI", "7": "LSE"}, "div": [1, 2, 4, 8, 16, 32, 64, 128]},
        "source": "RM v1.2 8.6.1-8.6.4, FLASH_ACR 4.8.1; DS Rev2.2 'Clock system'",
    },
    "py32f003": {
        "sysclk_max_hz": 32 * HZ,
        "hsi": {"select_reg": "RCC_ICSCR.HSI_FS", "freqs_hz": {"0": 4 * HZ, "1": 8 * HZ, "2": 16 * HZ, "3": 22_120_000, "4": 24 * HZ},
                "default_after_reset_hz": 8 * HZ, "trim_addr": {"0": 0x1FFF0F00, "1": 0x1FFF0F04, "2": 0x1FFF0F08, "3": 0x1FFF0F0C, "4": 0x1FFF0F10},
                "div": [1, 2, 4, 8, 16, 32, 64, 128]},
        "hse": {"crystal_hz": [4 * HZ, 32 * HZ], "bypass": True, "freq_field": "RCC_ECSCR.HSE_FREQ"},
        "pll": None,     # RM v1.2 has no PLL (no PLLCFGR, no PLLON); the DS clock list has none either
        "lsi_hz": 32768, "lse_hz": 32768, "ahb_div": [1, 2, 4, 8, 16, 64, 128, 256, 512], "apb_div": [1, 2, 4, 8, 16],
        "flash_latency": [{"max_hz": 24 * HZ, "latency": 0}, {"max_hz": 32 * HZ, "latency": 1}],
        "mco": {"sel": {"1": "SYSCLK", "3": "HSI", "4": "HSE", "6": "LSI", "7": "LSE"}, "div": [1, 2, 4, 8, 16, 32, 64, 128]},
        "source": "DS Rev1.2 EN: 32 MHz max; RM v1.2 RCC/FLASH chapters (same layout as PY32F030)",
        "trim_addr_source": "inferred: same addresses as PY32F030 RM; verify on hardware",
    },
    "py32f002b": {
        "sysclk_max_hz": 24 * HZ,
        "hsi": {"select_reg": "RCC_ICSCR.HSI_FS", "freqs_hz": {"4": 24 * HZ}, "default_after_reset_hz": 24 * HZ,
                "trim_addr": {"4": 0x1FFF0100}, "div": [1, 2, 4, 8, 16, 32, 64, 128]},
        "hse": {"crystal_hz": None, "bypass": True, "enable_bit": "RCC_CR.HSEEN", "note": "external clock input only"},
        "pll": None,
        "lsi_hz": 32768, "lsi_alt_hz": 38400, "lsi_trim_addr": {"32768": 0x1FFF0144, "38400": 0x1FFF0148}, "lse_hz": 32768,
        "ahb_div": [1, 2, 4, 8, 16, 64, 128, 256, 512], "apb_div": [1, 2, 4, 8, 16],
        "flash_latency": [{"max_hz": 24 * HZ, "latency": 0}],
        "mco": {"sel": {"1": "SYSCLK", "3": "HSI", "4": "HSE", "6": "LSI", "7": "LSE"}, "div": [1, 2, 4, 8, 16, 32, 64, 128]},
        "source": "RM v0.4 8.6.1-8.6.3, FLASH_ACR 4.8.1; DS V0.8",
    },
}

# Option bytes (RM FLASH chapter 4.4) -------------------------------------------
OPTION_BYTES = {
    "py32f030": {
        "address": 0x1FFF0E80, "size": 128, "stored_with_complement": True,
        "words": {
            "user": {"addr": 0x1FFF0E80, "production": 0x4155BEAA, "fields": {
                "RDP": [0, 8], "BOR_EN": [8, 1], "BOR_LEV": [9, 3], "IWDG_SW": [12, 1], "WWDG_SW": [13, 1],
                "NRST_MODE": [14, 1], "nBOOT1": [15, 1]}},
            "sdk": {"addr": 0x1FFF0E84, "production": 0xFF0000FF, "fields": {"SDK_STRT": [0, 5], "SDK_END": [8, 5]}},
            "wrp": {"addr": 0x1FFF0E8C, "production": 0x0000FFFF, "fields": {"WRP": [0, 16]}},
        },
        "rdp": {"unprotected": 0xAA, "note": "0xAA = level 0 (open); any other value = level 1 (read-out protected)"},
        "unlock": {"optkey1": 0x08192A3B, "optkey2": 0x4C5D6E7F},
        "danger": {"NRST_MODE": "1 makes PF2 a GPIO: no hardware reset pin",
                   "RDP": "any value except 0xAA turns on read-out protection; going back to 0xAA mass-erases the chip",
                   "WRP": "write-protects flash sectors", "SDK": "SDK area is not readable by the debugger",
                   "nBOOT1": "changes the boot source selection"},
        "source": "RM v1.2 4.4",
    },
    "py32f003": {
        "address": 0x1FFF0E80, "size": 128, "stored_with_complement": True,
        "words": {
            "user": {"addr": 0x1FFF0E80, "production": 0x0155BEAA, "fields": {
                "RDP": [0, 8], "BOR_EN": [8, 1], "BOR_LEV": [9, 3], "IWDG_SW": [12, 1], "WWDG_SW": [13, 1],
                "NRST_MODE": [14, 1], "nBOOT1": [15, 1]}},
            "sdk": {"addr": 0x1FFF0E84, "production": 0xFF0000FF, "fields": {"SDK_STRT": [0, 5], "SDK_END": [8, 5]}},
            "wrp": {"addr": 0x1FFF0E8C, "production": 0x0000FFFF, "fields": {"WRP": [0, 16]}},
        },
        "rdp": {"unprotected": 0xAA, "note": "0xAA = level 0 (open); any other value = level 1 (read-out protected)"},
        "unlock": {"optkey1": 0x08192A3B, "optkey2": 0x4C5D6E7F},
        "danger": {"NRST_MODE": "1 makes PF2 a GPIO: no hardware reset pin",
                   "RDP": "any value except 0xAA turns on read-out protection; going back to 0xAA mass-erases the chip",
                   "WRP": "write-protects flash sectors", "SDK": "SDK area is not readable by the debugger",
                   "nBOOT1": "changes the boot source selection"},
        "source": "RM v1.2 4.4 (production values from the RM; field layout verified against the PY32F030 RM, same text)",
        "layout_source": "inferred-from-PY32F030",
    },
    "py32f002b": {
        "address": 0x1FFF0080, "size": 128, "stored_with_complement": True,
        "words": {
            "user": {"addr": 0x1FFF0080, "production": 0x0155BEAA, "fields": {
                "BOR_EN": [8, 1], "BOR_LEV": [9, 3], "IWDG_SW": [12, 1], "SWD_MODE": [13, 1], "NRST_MODE": [14, 1],
                "IWDG_STOP": [15, 1]}},
            "sdk": {"addr": 0x1FFF0084, "production": 0xF4FF0B00, "fields": {"SDK_STRT": [0, 4], "SDK_END": [8, 4]}},
            "boot": {"addr": 0x1FFF0088, "production": 0xFFFF0000, "fields": {"BOOT_SIZE": [0, 3], "BOOT0": [14, 1], "nBOOT1": [15, 1]}},
            "wrp": {"addr": 0x1FFF008C, "production": 0xFFC0003F, "fields": {"WRP": [0, 6]}},
        },
        "rdp": None,
        "unlock": {"optkey1": 0x08192A3B, "optkey2": 0x4C5D6E7F, "source": "inferred: same keys as PY32F030 RM; check RM 4.4.2"},
        "danger": {"NRST_MODE/SWD_MODE": "00/01: PC0=NRST, PB6=SWD; 10: PC0=GPIO, PB6=SWD; 11: PC0=SWD, PB6=GPIO. A wrong choice can make the chip unreachable by the probe",
                   "WRP": "write-protects flash sectors", "SDK": "SDK area is not readable by the debugger",
                   "BOOT0/nBOOT1": "changes the boot source selection"},
        "source": "RM v0.4 4.4",
    },
}

BOOTLOADER = {  # RM "Boot mode" (system memory 0x1FFF0000, 3.5 KB on F030/F003); protocol still to verify on hardware
    "py32f030": {"system_memory": 0x1FFF0000, "size": 0xE00, "interface": "USART (see RM, boot loader app note)"},
    "py32f003": {"system_memory": 0x1FFF0000, "size": 0xE00, "interface": "USART"},
    "py32f002b": {"system_memory": 0x1FFF0000, "size": 0x80, "interface": "see RM; the 128-byte area at 0x1FFF0000 is the UID on this part",
                  "note": "RM memory map shows UID at 0x1FFF0000; boot via Load Flash area (BOOT_SIZE)"},
}

ADC_EXTRA = {  # RM ADC chapter
    "py32f030": {"internal": {"TS_VIN": 10, "VREFINT": 11}, "resolution_bits": 12},
    "py32f003": {"internal": {"TS_VIN": 10, "VREFINT": 11}, "resolution_bits": 12, "source": "RM v1.2 (same as F030)"},
    "py32f002b": {"internal": {"TS_VIN": 8, "VREFINT": 9}, "resolution_bits": 12},
}

# PA3=IN1 for PY32F002B from RM v0.4 ADC channel table (the DS pin table layout is ambiguous there)
ADC_PIN_OVERRIDE = {"py32f002b": {"PA3": "ADC_IN1"}}

NOTES = {
    "py32f030": [
        "LQFP32 K1 pin 1: DS Rev1.4 EN says NC, DS Rev2.2 says VCC; Rev2.2 is used.",
        "TSSOP20 F4 (Pinout4) has the dual-bonded pad PA5/PB4 on pin 13; the pad is one clickable pin with a port choice.",
        "Datasheet pin table shows LPUART_TX on PA2 (Rev1.4 EN only); the chip has no LPUART in the RM/SVD, ignored.",
    ],
    "py32f003": [
        "DS Rev1.9 has no real Port B alternate-function table (the section repeats Port A). PB5-PB7 follow DS Rev1.2 EN; "
        "PB0-PB4 and PB8 use the numbering of the PY32F030 DS Rev2.2 table (marked source=inferred); their function set matches the F003 pin table.",
        "DS Rev1.9 alternate-function table lists SPI2_* and LED_* (copied from PY32F030); the chip has only SPI1 and no LED controller (DS Rev1.2 EN, RM, SVD), those entries are dropped.",
        "TSSOP20 F4 (Pinout4) has the dual-bonded pad PA2/PF2-NRST on pin 2.",
        "PY32F003 has no PLL (the RM has no PLL register and the DS clock list has none): 32 MHz needs an external clock/crystal on HSE.",
    ],
    "py32f002b": [
        "DS V0.8 is an early revision. MSOP10 (PY32F010MA15N) appears only in the EN V0.3 datasheet and is not included.",
        "ADC_IN1 is on PA3 per RM v0.4 (DS pin table layout is ambiguous).",
        "Table 3-6: PC0 lists SWD on AF0 (as printed).",
        "SWD pins are PB6 (SWDIO) and PA2 (SWCLK); option bytes can move SWD (see option_bytes).",
    ],
}

def _exti(ports3, five_eight, hi, last):
    """EXTI line -> ports that can be selected (code = index in the list), RM EXTI_EXTICR1..3."""
    t = {}
    for n in range(0, 5):
        t[str(n)] = list(ports3)
    for n in range(5, 9):
        t[str(n)] = list(five_eight)
    for n in range(9, 16):
        t[str(n)] = list(hi)
    return {k: v for k, v in t.items() if int(k) <= last}


EXTI = {
    "py32f030": {"lines": _exti("ABF", "AB", "A", 15), "source": "RM v1.2 EXTI_EXTICR1-3 (12.3.5-12.3.7); lines 9-15 have no selector (port A)"},
    "py32f003": {"lines": _exti("ABF", "AB", "A", 15), "source": "RM v1.2 EXTI_EXTICR1-3"},
    "py32f002b": {"lines": _exti("ABC", "AB", "", 7), "source": "RM v0.4 EXTI_EXTICR1-2; the code for port C (2) is not printed in the RM, inferred (verify on hardware)"},
}

# Factory flash timing words copied into FLASH_TS0.. after changing the HSI frequency (RM table 4-6, PY32F030/F003).
# Per HSI_FS index: address of EPPARA0; the five words follow (TS0/TS3/TS1, TS2P/TPS3, PERTPE, SMERTPE, PRGTPE/PRETPE)
FLASH_TIMING = {
    "py32f030": {"epara_base": {"0": 0x1FFF0F1C, "1": 0x1FFF0F30, "2": 0x1FFF0F44, "3": 0x1FFF0F58, "4": 0x1FFF0F6C},
                 "layout": {"TS0": [0, 8, 0, 0], "TS3": [0, 8, 8, 0], "TS1": [0, 9, 16, 0], "TS2P": [1, 8, 0, 0], "TPS3": [1, 11, 16, 0],
                            "PERTPE": [2, 17, 0, 0], "SMERTPE": [3, 17, 0, 0], "PRGTPE": [4, 16, 0, 0], "PRETPE": [4, 13, 16, 0]},
                 "source": "RM v1.2 4.5.3-4.5.8"},
    "py32f003": {"epara_base": {"0": 0x1FFF0F1C, "1": 0x1FFF0F30, "2": 0x1FFF0F44, "3": 0x1FFF0F58, "4": 0x1FFF0F6C},
                 "layout": {"TS0": [0, 8, 0, 0], "TS3": [0, 8, 8, 0], "TS1": [0, 9, 16, 0], "TS2P": [1, 8, 0, 0], "TPS3": [1, 11, 16, 0],
                            "PERTPE": [2, 17, 0, 0], "SMERTPE": [3, 17, 0, 0], "PRGTPE": [4, 16, 0, 0], "PRETPE": [4, 13, 16, 0]},
                 "source": "RM v1.2 4.5.3-4.5.8 (table 4-6)"},
    "py32f002b": None,
}
HSI_WORD = {"fs_shift_in_word": 16, "fs_bits": 3, "trim_bits": 13, "note": "factory word: HSI_FS[2:0] at bit 16, HSI_TRIM[12:0] at bit 0 (RM 4.5.1)"}

CHIPS = {
    "py32f030": {
        "svd": "py32f030xx.svd", "rmtxt": "f030_rm_cn12.txt",
        "meta": {"name": "PY32F030", "core": "Cortex-M0+", "max_hz": 48 * HZ, "vdd_min": 1.7, "vdd_max": 5.5,
                 "temp_min": -40, "temp_max": 85, "pack_device_prefix": "PY32F030", "ordering_base": "PY32F030",
                 "swd": {"SWDIO": "PA13", "SWCLK": "PA14"}, "nrst": "PF2", "boot0": "PF4", "pin_default_boot0_as_gpio": True},
        "sources": [{"id": "DS", "doc": "PY32F030 Datasheet Rev2.2 (Chinese)", "also": "Rev1.4_EN"},
                    {"id": "RM", "doc": "PY32F030 Reference Manual v1.2 (Chinese)"},
                    {"id": "SVD", "doc": "Puya.PY32F0xx_DFP 1.2.0 py32f030xx.svd (Puya)"}],
        "memory": {"flash_base": 0x08000000, "ram_base": 0x20000000, "page_bytes": 128, "sector_bytes": 4096,
                   "system_base": 0x1FFF0000, "uid_base": 0x1FFF0E00, "option_base": 0x1FFF0E80, "factory_base": 0x1FFF0F00,
                   "source": "RM v1.2 table 4-1"},
    },
    "py32f003": {
        "svd": "py32f003xx.svd", "rmtxt": "f003_rm_cn12.txt",
        "meta": {"name": "PY32F003", "core": "Cortex-M0+", "max_hz": 32 * HZ, "vdd_min": 1.7, "vdd_max": 5.5,
                 "temp_min": -40, "temp_max": 85, "pack_device_prefix": "PY32F003", "ordering_base": "PY32F003",
                 "swd": {"SWDIO": "PA13", "SWCLK": "PA14"}, "nrst": "PF2", "boot0": "PF4", "pin_default_boot0_as_gpio": True},
        "sources": [{"id": "DS", "doc": "PY32F003 Datasheet Rev1.9 (Chinese)", "also": "Rev1.2_EN"},
                    {"id": "RM", "doc": "PY32F003 Reference Manual v1.2 (Chinese)"},
                    {"id": "SVD", "doc": "Puya.PY32F0xx_DFP 1.2.0 py32f003xx.svd (Puya)"}],
        "memory": {"flash_base": 0x08000000, "ram_base": 0x20000000, "page_bytes": 128, "sector_bytes": 4096,
                   "system_base": 0x1FFF0000, "uid_base": 0x1FFF0E00, "option_base": 0x1FFF0E80, "factory_base": 0x1FFF0F00,
                   "source": "RM v1.2 memory map"},
    },
    "py32f002b": {
        "svd": "py32f002bxx.svd", "rmtxt": "f002b_rm_cn04.txt",
        "meta": {"name": "PY32F002B", "core": "Cortex-M0+", "max_hz": 24 * HZ, "vdd_min": 1.7, "vdd_max": 5.5,
                 "temp_min": -40, "temp_max": 85, "pack_device_prefix": "PY32F002B", "ordering_base": "PY32F002B",
                 "swd": {"SWDIO": "PB6", "SWCLK": "PA2"}, "nrst": "PC0", "boot0": None, "pin_default_boot0_as_gpio": False},
        "sources": [{"id": "DS", "doc": "PY32F002B Datasheet V0.8 (Chinese)", "also": "V0.3_EN"},
                    {"id": "RM", "doc": "PY32F002B Reference Manual v0.4 (Chinese)", "also": "v0.2_EN"},
                    {"id": "SVD", "doc": "Puya.PY32F0xx_DFP 1.2.0 py32f002bxx.svd (Puya)"}],
        "memory": {"flash_base": 0x08000000, "ram_base": 0x20000000, "page_bytes": 128, "sector_bytes": 4096,
                   "system_base": 0x1FFF0000, "uid_base": 0x1FFF0000, "option_base": 0x1FFF0080, "factory_base": 0x1FFF0100,
                   "user_otp_base": 0x1FFF0280, "source": "RM v0.4 memory map; page/sector size inferred from PY32F030 (verify)"},
    },
}
for _c, _i in CHIPS.items():
    _i["features"] = FEATURES[_c]
    _i["clock"] = CLOCKS[_c]
    _i["option_bytes"] = OPTION_BYTES[_c]
    _i["bootloader"] = BOOTLOADER[_c]
    _i["adc"] = ADC_EXTRA[_c]
    _i["signal_alias"] = SIGNAL_ALIAS[_c]
    _i["notes"] = NOTES[_c]
    _i["exti"] = EXTI[_c]
    _i["flash_timing"] = FLASH_TIMING[_c]
    _i["clock"] = dict(_i["clock"], hsi_word=HSI_WORD)


def finish_ports(chip, ports, raw):
    """Merge analog functions, fix the F003 Port B table, drop signals of absent peripherals."""
    feats = allowed_prefixes(chip)
    if chip == "py32f003":
        f030 = raw("raw_f030_af.json")
        en_pb = {}  # PB5-PB7 as printed in DS Rev1.2 EN (retyped in tests); here fill from F030 and mark
        for p in ("PB0", "PB1", "PB2", "PB3", "PB4", "PB5", "PB6", "PB7", "PB8"):
            ports[p] = {"af": {k: v for k, v in f030[p].items() if v}, "af_source": "inferred-from-PY32F030-DS"}
            if p in ("PB5", "PB6", "PB7"):
                ports[p]["af_source"] = "DS Rev1.2 EN table 4-4 (matches PY32F030 numbering)"
    if chip == "py32f003" and not ports.get("PA1", {}).get("af"):
        # PA1's header row is on the previous page in DS Rev1.9; the row text (read on the page) equals the PY32F030 row
        ports["PA1"] = {"af": {k: v for k, v in raw("raw_f030_af.json")["PA1"].items() if v},
                        "af_source": "DS Rev1.9 p25-26 (row split by a page break; identical to the PY32F030 row)"}
    REPAIR = {"COMP1_OU": "COMP1_OUT"}      # word wrapped in the PDF cell ("COMP1_OU" / "T")
    for d in ports.values():
        d["af"] = {k: REPAIR.get(v, v) for k, v in d["af"].items()}
    for p, d in ports.items():
        d["af"] = {k: v for k, v in d["af"].items()
                   if prefix(canon(chip, v)) in feats or v in ("EVENTOUT", "MCO", "IR_OUT")}
        if chip in ("py32f030", "py32f003") and p in raw("raw_f030_af.json") and "af_source" not in d:
            d["af_source"] = "DS table"
    analog = raw(f"raw_{chip[4:]}_analog.json")
    for p, toks in analog.items():
        if p not in ports:
            ports[p] = {"af": {}}
        fixed = []
        for t in toks:
            t = {"OS32IN": "OSC32_IN", "OSC32OUT": "OSC32_OUT", "OSCIN": "OSC_IN", "OSCOUT": "OSC_OUT",
                 "External_clock_in": "EXT_CLK_IN"}.get(t, t)
            t = t.replace("CMP", "COMP")
            fixed.append(t)
        ports[p]["analog"] = sorted(set(fixed))
    for p, t in ADC_PIN_OVERRIDE.get(chip, {}).items():
        a = [x for x in ports[p].get("analog", []) if not x.startswith("ADC_IN")]
        ports[p]["analog"] = sorted(a + [t])
    return dict(sorted(ports.items(), key=lambda kv: (kv[0][1], int(kv[0][2:]))))


def apply_package_parts(chip, db):
    parts = []
    base = CHIPS[chip]["meta"]["ordering_base"]
    for pid, pk in db["packages"].items():
        for digit, (fk, rk) in MEM_DIGITS[chip].items():
            memc = digit
            parts.append({"part": f"{base}{pk['code']}{memc}{pk['letter']}6", "package": pid, "flash_kb": fk, "ram_kb": rk,
                          "source": "DS ordering information (7)"})
    db["parts"] = parts
    db["memory"]["flash_ram_by_digit"] = {d: list(v) for d, v in MEM_DIGITS[chip].items()}
