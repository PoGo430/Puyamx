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
    rows = []
    for w in hdrs:
        if rows and abs(rows[-1][0][1] - w[1]) < 2.5:
            rows[-1].append(w)
        else:
            rows.append([w])
    rows = [sorted(r, key=lambda w: w[0]) for r in rows if len(r) == 8]
    if not rows:
        return {}
    col0 = min(r[0][0] for r in rows)
    ports = [w for w in ws if re.match(r"P[A-F]\d{1,2}(?![0-9])", w[6]) and w[0] < col0 - 12]
    ports.sort(key=lambda w: w[1])
    # blocks: each AF0-7 row starts a block, an AF8-15 row directly after belongs to it
    blocks = []
    for r in rows:
        if r[0][6] == "AF0":
            blocks.append([r])
        elif blocks:
            blocks[-1].append(r)
    res = {}
    for i, blk in enumerate(blocks):
        y0 = blk[0][0][1] - 3
        y1 = blocks[i + 1][0][0][1] - 3 if i + 1 < len(blocks) else blk[-1][0][1] + 24
        labs = [p for p in ports if y0 <= p[1] < y1]
        if not labs:
            continue
        name = re.match(r"P[A-F]\d{1,2}", labs[0][6]).group(0)
        afs = {}
        for j, hdr in enumerate(blk):
            ya = hdr[0][1] + 2
            yb = blk[j + 1][0][1] - 2 if j + 1 < len(blk) else y1
            cols = {}
            for w in ws:
                if not (ya < w[1] < yb) or re.fullmatch(r"AF\d+|P[A-F]\d+.*", w[6]):
                    continue
                if not w[6].isascii() or re.fullmatch(r"[A-Z]", w[6]) or re.fullmatch(r"\d+/\d+|\d+-\d+", w[6]):
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
