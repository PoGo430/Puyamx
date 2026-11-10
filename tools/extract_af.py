"""Dev tool: read the alternate-function tables (Port A/B/F, AF0..AF15) of
PY32F030 / PY32F003 datasheets (two header rows per port) from a PDF.

Usage: extract_af.py file.pdf first_page last_page   -> JSON {port: {af: name}}
Uses word coordinates from pdftotext -bbox.  Output is checked against the
rendered pages (see tests/test_chips.py for the values typed again by hand).
"""
import json, re, subprocess, sys

def words(pdf, page):
    out = subprocess.run(["pdftotext", "-f", str(page), "-l", str(page), "-bbox", pdf, "-"],
                         capture_output=True, text=True, check=True).stdout
    for m in re.finditer(r'xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">(.*?)</word>', out):
        x0, y0, x1, y1 = map(float, m.groups()[:4])
        yield (x0 + x1) / 2, (y0 + y1) / 2, x0, x1, y0, y1, m.group(5)

def parse_page(pdf, page):
    ws = list(words(pdf, page))
    hdrs = sorted([w for w in ws if re.fullmatch(r"AF\d{1,2}", w[6])], key=lambda w: (round(w[1]), w[0]))
    # group header words into rows by y
    rows = []
    for w in hdrs:
        if rows and abs(rows[-1][0][1] - w[1]) < 2.5:
            rows[-1].append(w)
        else:
            rows.append([w])
    rows = [sorted(r, key=lambda w: w[0]) for r in rows if len(r) == 8]
    ports = [w for w in ws if re.fullmatch(r"P[A-F]\d{1,2}", w[6]) and w[2] < min(r[0][2] for r in rows) - 1] if rows else []
    ports.sort(key=lambda w: w[1])
    res = {}
    # rows come in pairs (AF0-7, AF8-15) for the 16-AF tables
    for k in range(0, len(rows) - 1, 2):
        r0, r8 = rows[k], rows[k + 1]
        y_top, y_mid = r0[0][1], r8[0][1]
        y_end = rows[k + 2][0][1] - 3 if k + 2 < len(rows) else y_mid + 40
        # port label: nearest label to the pair's centre, not yet used
        cands = [p for p in ports if y_top - 8 <= p[1] <= y_end + 4]
        centre = (y_top + y_mid) / 2 + 4
        cands.sort(key=lambda p: abs(p[1] - centre))
        if not cands:
            continue
        name = cands[0][6]
        ports = [p for p in ports if p is not cands[0]]
        afs = {}
        for hdr, ya, yb in ((r0, y_top + 2, y_mid - 2), (r8, y_mid + 2, y_end)):
            cols = {}
            for w in ws:
                if not (ya < w[1] < yb) or re.fullmatch(r"AF\d+|P[A-F]\d+", w[6]):
                    continue
                if w[0] < hdr[0][0] - 25 or w[0] > hdr[-1][0] + 40:
                    continue
                c = min(hdr, key=lambda h: abs(h[0] - w[0]))
                cols.setdefault(c[6], []).append(w)
            for h in hdr:
                parts = sorted(cols.get(h[6], []), key=lambda w: (round(w[1] / 4), w[0]))
                txt = "".join(p[6] for p in parts).replace(" ", "")
                txt = re.sub(r"_+$", "", txt)
                afs[int(h[6][2:])] = txt if txt not in ("", "-") else None
        res[name] = afs
    return res

if __name__ == "__main__":
    pdf, p0, p1 = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
    allp = {}
    for p in range(p0, p1 + 1):
        for k, v in parse_page(pdf, p).items():
            allp.setdefault(k, v)
    print(json.dumps(allp, indent=0, sort_keys=True))
