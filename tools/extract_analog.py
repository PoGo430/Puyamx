"""Dev tool: collect 'additional functions' (ADC_INx, COMPx_INP/INM, OSC pins, ...) per port
from the pin-definition tables of a datasheet, by pairing every such token with the
nearest port name on the same page (cells are vertically centred).
Usage: extract_analog.py file.pdf first_page last_page  -> JSON {port: [tokens]}"""
import json, re, subprocess, sys

TOK = re.compile(r"^(ADC_IN\d+|External_clock_in|OSCIN|OSCOUT|OSC32IN|OSC32OUT|OS32IN|COMP\d?_(INP|INM|INN|OUT)\d?|CMP\d?_(INP|INM|INN|OUT)\d?|OSC32?_(IN|OUT)|OSC_(IN|OUT)|RTC_TAMP\d*|RTC_REFIN|WKUP\d*|VREF\w*|NRST|BOOT0|ADC_IN\w+)$")
PORT = re.compile(r"^P[A-F]\d{1,2}")

def words(pdf, page):
    out = subprocess.run(["pdftotext", "-f", str(page), "-l", str(page), "-bbox", pdf, "-"],
                         capture_output=True, text=True, check=True).stdout
    for m in re.finditer(r'xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">(.*?)</word>', out):
        x0, y0, x1, y1 = map(float, m.groups()[:4])
        yield (x0 + x1) / 2, (y0 + y1) / 2, m.group(5)

def run(pdf, p0, p1):
    res = {}
    for p in range(p0, p1 + 1):
        ws = list(words(pdf, p))
        ports = [w for w in ws if PORT.match(w[2]) and re.fullmatch(r"P[A-F]\d{1,2}(\W.*)?|\(P[A-F]\d+\)", w[2])]
        # port label of the row: the cell with the pin name (x left of the tokens); keep plain names
        ports = [(x, y, re.match(r"P[A-F]\d{1,2}", n).group(0)) for x, y, n in ports]
        toks = [w for w in ws if TOK.match(w[2])]
        for x, y, t in toks:
            if t in ("NRST", "BOOT0") or t.endswith("_OUT") and not t.startswith("OSC"):
                continue
            cand = [pp for pp in ports if pp[0] < x]
            if not cand:
                continue
            best = min(cand, key=lambda pp: abs(pp[1] - y))
            if abs(best[1] - y) < 14:
                res.setdefault(best[2], set()).add(t)
    return {k: sorted(v) for k, v in sorted(res.items(), key=lambda kv: (kv[0][1], int(kv[0][2:])))}

if __name__ == "__main__":
    print(json.dumps(run(sys.argv[1], int(sys.argv[2]), int(sys.argv[3])), indent=0))
