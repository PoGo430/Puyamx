"""Dev tool: compare register offsets / reset values in the chip database (from the Puya SVD)
with the headings of the reference manual text ("Address offset" / "Reset value").
Usage: verify_regs.py RMTXT_DIR   Prints mismatches and a summary per chip."""
import json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
from puya_studio import chips

RM = {"py32f030": "f030_rm_cn12.txt", "py32f003": "f003_rm_cn12.txt", "py32f002b": "f002b_rm_cn04.txt"}
# RM register prefix -> database peripherals
PREFIX = {"RCC": ["RCC"], "FLASH": ["FLASH"], "GPIOx": ["GPIOA", "GPIOB"], "GPIO": ["GPIOA", "GPIOB"], "PWR": ["PWR"],
          "EXTI": ["EXTI"], "SYSCFG": ["SYSCFG"], "DMA": ["DMA"], "CRC": ["CRC"], "ADC": ["ADC"], "IWDG": ["IWDG"],
          "WWDG": ["WWDG"], "RTC": ["RTC"], "LPTIM": ["LPTIM", "LPTIM1"], "I2C": ["I2C"], "SPI": ["SPI1"],
          "USART": ["USART1"], "TIM1": ["TIM1"], "TIM3": ["TIM3"], "TIM14": ["TIM14"], "TIM16": ["TIM16"],
          "TIM17": ["TIM17"], "LED": ["LED"], "COMP": ["COMP1"], "DBGMCU": ["DBGMCU"], "DBG": ["DBGMCU"]}


def hexv(s):
    return int(re.sub(r"[\s_]", "", s), 16)


def main():
    rmdir = sys.argv[1]
    for name, fn in RM.items():
        c = chips.load(name)
        txt = open(os.path.join(rmdir, fn), encoding="utf8").read().splitlines()
        checked = bad = missing = 0
        seen = set()
        for i, line in enumerate(txt):
            m = re.search(r"[（(]([A-Za-z0-9]+)_([A-Za-z0-9_]+)[）)]\s*$", line)
            if not m or i + 3 >= len(txt):
                continue
            pre, reg = m.groups()
            nxt = txt[i + 1:i + 4]
            ao = next((re.search(r"Address offset:\s*0x([0-9A-Fa-f]{1,4}(?:[ _][0-9A-Fa-f]{4})?)", l) for l in nxt
                       if "Address offset" in l), None)
            rv = next((re.search(r"Reset value:\s*0x([0-9A-Fa-f]{4}[ _][0-9A-Fa-f]{4}|[0-9A-Fa-f]{1,8})", l) for l in nxt
                       if "Reset value" in l), None)
            if not ao or pre not in PREFIX:
                continue
            for per in PREFIX[pre]:
                if per not in c.peripherals:
                    continue
                key = (per, reg)
                if key in seen:
                    continue
                r = c.peripherals[per]["regs"].get(reg) or c.peripherals[per]["regs"].get(reg.replace("_", ""))
                if r is None:
                    missing += 1
                    print(f"{name}: {per}_{reg} in RM (offset 0x{hexv(ao.group(1)):X}) but not in the database")
                    continue
                seen.add(key)
                checked += 1
                off = hexv(ao.group(1))
                bits = []
                if r["off"] != off:
                    bits.append(f"offset db 0x{r['off']:X} rm 0x{off:X}")
                if rv:
                    try:
                        rvv = hexv(rv.group(1).split(",")[0])
                        if r["reset"] != rvv:
                            bits.append(f"reset db 0x{r['reset']:X} rm 0x{rvv:X}")
                    except ValueError:
                        pass
                if bits:
                    bad += 1
                    print(f"{name}: {per}_{reg}: " + "; ".join(bits))
        print(f"== {name}: {checked} registers compared, {bad} differ, {missing} only in RM")


main()
