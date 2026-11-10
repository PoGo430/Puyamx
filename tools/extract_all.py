"""Dev tool: run all PDF extractions and write tools/data/raw_*.json.
Usage: extract_all.py DOCDIR   (DOCDIR holds f030_cn22.pdf f003_cn19.pdf f002b_cn08.pdf)
Needs poppler's pdftotext. The JSON files are committed so the build does not need the PDFs."""
import json, os, re, subprocess, sys
sys.path.insert(0, os.path.dirname(__file__))
import extract_pinouts, extract_af, extract_analog

doc = sys.argv[1]
out = os.path.join(os.path.dirname(__file__), "data")

def save(name, obj):
    with open(os.path.join(out, name), "w") as f:
        json.dump(obj, f, indent=1, sort_keys=True, ensure_ascii=False)
        f.write("\n")

jobs = {
    "f030": ("f030_cn22.pdf", (21, 25), (40, 42), (26, 40)),
    "f003": ("f003_cn19.pdf", (18, 20), (25, 28), (20, 25)),
    "f002b": ("f002b_cn08.pdf", (17, 18), None, (14, 22)),
}
for chip, (pdf, pp, ap, an) in jobs.items():
    p = os.path.join(doc, pdf)
    pins = [{"page": pg, "caption": cap, "pins": {str(k): v for k, v in d.items()}}
            for pg, cap, d in extract_pinouts.extract(p, *pp)]
    save(f"raw_{chip}_pinouts.json", pins)
    if ap:
        allp = {}
        for pg in range(ap[0], ap[1] + 1):
            for k, v in extract_af.parse_page(p, pg).items():
                allp.setdefault(k, v)
        save(f"raw_{chip}_af.json", allp)
    save(f"raw_{chip}_analog.json", extract_analog.run(p, *an))
    print(chip, len(pins), "pinouts")

# PY32F002B: the AF table is plain text (one row per port)
txt = subprocess.run(["pdftotext", "-layout", "-f", "22", "-l", "23", os.path.join(doc, "f002b_cn08.pdf"), "-"],
                     capture_output=True, text=True).stdout
af = {}
for line in txt.splitlines():
    line = re.sub(r"\bI\s+C_", "I2C_", line)
    m = re.match(r"\s*(P[ABC]\d)(?:-\w+)?\s+(.*)$", line)
    if not m:
        continue
    toks = m.group(2).split()
    if len(toks) == 7 and m.group(1) == "PA7":
        toks.append("-")          # last cell is empty in the table (checked on the page image)
    if len(toks) != 8:
        print("F002B AF row skipped:", line.strip())
        continue
    af[m.group(1)] = {str(i): (None if t == "-" else t) for i, t in enumerate(toks)}
save("raw_f002b_af.json", af)
print("f002b af ports:", sorted(af))
