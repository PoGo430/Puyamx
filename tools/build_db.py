"""Dev tool: build puya_studio/chips/py32*.json from
  tools/data/raw_*.json   (extracted from the datasheet PDFs by extract_all.py)
  the official Puya DFP 1.2.0 SVD files (registers)   -> pass the unpacked DFP directory
  the reference manuals' interrupt tables              -> pass the RM text files directory
  tools/db_facts.py       (facts typed from the documents: clocks, options, features ...)

Usage: build_db.py DFP_DIR RMTXT_DIR
"""
import json, os, re, sys
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import db_facts as F

OUT = os.path.join(HERE, "..", "puya_studio", "chips")


def raw(name):
    with open(os.path.join(HERE, "data", name)) as f:
        return json.load(f)


# ---------------------------------------------------------------- pins / packages
PKG_LETTER = {"LQFP": "T", "QFN": "U", "TSSOP": "P", "SSOP": "M", "SOP": "S", "MSOP": "N", "DFN": "D"}


def norm_label(lbl):
    parts = [p for p in lbl.split("+") if not re.search(r"QFN|Exposed|EP$", p)]
    lbl = "+".join(parts)
    ports = re.findall(r"P[A-F]\d{1,2}", lbl)
    extras = []
    for tok in re.split(r"[-/()]", lbl):
        tok = tok.strip()
        if not tok or re.fullmatch(r"P[A-F]\d{1,2}", tok):
            continue
        extras.append(F.EXTRA_ALIAS.get(tok, tok))
    if ports:
        return {"kind": "io", "ports": ports, "notes": extras}
    if re.fullmatch(r"V(CC|DD)", lbl):
        return {"kind": "power", "name": "VCC"}
    if lbl == "VSS":
        return {"kind": "power", "name": "VSS"}
    if lbl == "NC":
        return {"kind": "nc"}
    raise ValueError("unknown pin label " + lbl)


def build_packages(chip):
    pkgs = {}
    for fig in raw(f"raw_{chip[4:]}_pinouts.json"):
        m = re.match(r"\S+\s+\d+-\d+\s+(\w+?)\s+Pinout(\d+)\s+(PY32F(?:002B|030|003))([A-Z]\d)(x|\d)([A-Z])$", fig["caption"])
        if not m:
            raise ValueError("caption " + fig["caption"])
        ptype, idx, base, code, memc, letter = m.groups()
        pins = []
        for n in sorted(fig["pins"], key=int):
            labels = fig["pins"][n]
            d = {"n": int(n)}
            lbl = "+".join(labels)
            d.update(norm_label(lbl))
            pins.append(d)
        total = len(pins)
        fam = re.match(r"[A-Z]+", ptype).group(0)
        if fam in ("QFN", "DFN"):
            pins.append({"n": total + 1, "kind": "power", "name": "VSS", "exposed_pad": True})
        pid = f"{ptype}-{code}"
        pkgs[pid] = {
            "type": ptype, "pinout": int(idx), "code": code, "pin_count": total,
            "exposed_pad": fam in ("QFN", "DFN"), "letter": letter, "pins": pins,
            "source": f"{fig['caption']} (page {fig['page']})",
        }
    return pkgs


# ---------------------------------------------------------------- alternate functions
def build_ports(chip):
    afraw = raw(f"raw_{chip[4:]}_af.json")
    ports = {}
    notes = []
    for port, afs in afraw.items():
        ports[port] = {"af": {k: v for k, v in sorted(afs.items(), key=lambda kv: int(kv[0])) if v}}
    return ports


# ---------------------------------------------------------------- registers (SVD)
def svd_peripherals(path):
    root = ET.parse(path).getroot()
    pers = {}
    by_name = {}
    for p in root.find("peripherals"):
        by_name[p.findtext("name")] = p

    def regs_of(p):
        d = p.get("derivedFrom")
        src = by_name[d] if d else p
        out = {}
        for r in src.iter("register"):
            nm = r.findtext("name")
            fields = {}
            for f in r.iter("field"):
                lsb = f.findtext("bitOffset")
                w = f.findtext("bitWidth")
                if lsb is None and f.findtext("lsb") is not None:      # <msb>/<lsb> form (PY32F002B SVD)
                    lo, hi = int(f.findtext("lsb")), int(f.findtext("msb"))
                    lsb, w = lo, hi - lo + 1
                elif lsb is None:
                    rng = f.findtext("bitRange")
                    hi, lo = [int(x) for x in rng.strip("[]").split(":")]
                    lsb, w = lo, hi - lo + 1
                fields[f.findtext("name")] = [int(lsb), int(w)]
            rs = r.findtext("resetValue")
            out[nm] = {"off": int(r.findtext("addressOffset"), 0), "reset": int(rs, 0) if rs else 0,
                       "fields": fields}
        return out

    for name, p in by_name.items():
        pers[name] = {"base": int(p.findtext("baseAddress"), 0), "regs": regs_of(p)}
        if p.get("derivedFrom"):
            pers[name]["same_as"] = p.get("derivedFrom")
    return pers


# ---------------------------------------------------------------- interrupts (reference manual)
def rm_interrupts(path):
    txt = open(path, encoding="utf8").read()
    ints = {}
    for m in re.finditer(r"^\s*(\d{1,2})\s+(\d{1,2})\s+可设置\s+([A-Za-z][A-Za-z0-9_]*)", txt, re.M):
        pos, prio, name = int(m.group(1)), int(m.group(2)), m.group(3)
        if pos == 13 and name == "TIM1":          # name wraps over two lines in the RM table
            name = "TIM1_BRK_UP_TRG_COM"
        if name.lower() == "flash":
            name = "FLASH"
        ints.setdefault(pos, name)
    return {str(k): v for k, v in sorted(ints.items())}


PREFIX = {"RCC": ["RCC"], "FLASH": ["FLASH"], "GPIOx": ["GPIOA", "GPIOB", "GPIOC", "GPIOF"], "PWR": ["PWR"],
          "EXTI": ["EXTI"], "SYSCFG": ["SYSCFG"], "DMA": ["DMA"], "CRC": ["CRC"], "ADC": ["ADC"], "IWDG": ["IWDG"],
          "WWDG": ["WWDG"], "RTC": ["RTC"], "LPTIM": ["LPTIM", "LPTIM1"], "I2C": ["I2C"], "SPI": ["SPI1", "SPI2"],
          "USART": ["USART1", "USART2"], "TIM1": ["TIM1"], "TIM3": ["TIM3"], "TIM14": ["TIM14"], "TIM16": ["TIM16", "TIM17"],
          "LED": ["LED"], "COMP": ["COMP1", "COMP2"], "DBGMCU": ["DBGMCU"]}


def hexv(s):
    return int(re.sub(r"[\s_]", "", s), 16)


def rm_reset_overrides(path, pers):
    """The SVD has some wrong reset values; the RM headings win ("Reset value: 0x...")."""
    txt = open(path, encoding="utf8").read().splitlines()
    n = 0
    for i, line in enumerate(txt):
        m = re.search(r"[（(]([A-Za-z0-9]+)_([A-Za-z0-9_]+)[）)]\s*$", line)
        if not m or m.group(1) not in PREFIX:
            continue
        nxt = txt[i + 1:i + 4]
        rv = next((re.search(r"Reset value:\s*0x([0-9A-Fa-f]{4}[ _][0-9A-Fa-f]{4}|[0-9A-Fa-f]{1,8})", l) for l in nxt
                   if "Reset value" in l), None)
        if not rv:
            continue
        for per in PREFIX[m.group(1)]:
            r = pers.get(per, {}).get("regs", {}).get(m.group(2))
            if r is not None and r["reset"] != hexv(rv.group(1)):
                r["svd_reset"] = r["reset"]
                r["reset"] = hexv(rv.group(1))
                n += 1
    return n


def main():
    dfp, rmtxt = sys.argv[1], sys.argv[2]
    os.makedirs(OUT, exist_ok=True)
    for chip, info in F.CHIPS.items():
        db = {"schema": 1}
        db.update(info["meta"])
        db["sources"] = info["sources"]
        db["packages"] = build_packages(chip)
        db["ports"] = F.finish_ports(chip, build_ports(chip), raw)
        db["peripherals"] = svd_peripherals(os.path.join(dfp, "CMSIS", "SVD", info["svd"]))
        db["reset_values_from_rm"] = rm_reset_overrides(os.path.join(rmtxt, info["rmtxt"]), db["peripherals"])
        db["interrupts"] = rm_interrupts(os.path.join(rmtxt, info["rmtxt"]))
        for key in ("memory", "features", "clock", "option_bytes", "parts", "signal_alias", "notes", "adc",
                    "bootloader", "flash_timing", "gpio_regs"):
            if key in info:
                db[key] = info[key]
        F.apply_package_parts(chip, db)
        path = os.path.join(OUT, f"{chip}.json")
        with open(path, "w", encoding="utf8") as f:
            json.dump(db, f, indent=1, sort_keys=True, ensure_ascii=False)
            f.write("\n")
        print(path, len(db["packages"]), "packages", len(db["ports"]), "ports", len(db["interrupts"]), "irqs",
              len(db["peripherals"]), "peripherals")


if __name__ == "__main__":
    main()
