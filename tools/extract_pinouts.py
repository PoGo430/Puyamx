"""Dev tool: read package pinout drawings (vector text) from a datasheet PDF.

Usage: extract_pinouts.py file.pdf first_page last_page
Prints, per page, each 'Figure x-y <title>' and the pin number -> label map
found by pairing every label with the pin number in the same row/column.
Needs poppler's pdftotext.  Results are checked by eye against the drawing.
"""
import re, subprocess, sys

def words(pdf, page):
    out = subprocess.run(["pdftotext", "-f", str(page), "-l", str(page), "-bbox", pdf, "-"],
                         capture_output=True, text=True, check=True).stdout
    for m in re.finditer(r'xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">(.*?)</word>', out):
        x0, y0, x1, y1 = map(float, m.groups()[:4])
        yield x0, y0, x1, y1, m.group(5)

def figures(pdf, page):
    ws = list(words(pdf, page))
    caps = [w for w in ws if w[4].startswith(("Figure", "图"))]
    # a caption line: words with same yMin as the 'Figure' word
    caps_full = []
    for c in caps:
        line = [w for w in ws if abs(w[1] - c[1]) < 2.5 and w[0] >= c[0] - 1]
        line.sort()
        caps_full.append((c, " ".join(w[4] for w in line)))
    nums = [w for w in ws if re.fullmatch(r"\d{1,2}", w[4]) and w[1] < (max(c[1] for c in caps) + 1 if caps else 1e9)]
    labs = [w for w in ws if not re.fullmatch(r"[\d]+", w[4]) and not w[4].startswith(("Figure", "图"))]
    return ws, caps_full, nums, labs

def pair(nums, labs, ytop, ybot):
    pins = {}
    for (x0, y0, x1, y1, t) in labs:
        if not (ytop <= y0 and y1 <= ybot):
            continue
        if not re.fullmatch(r"[A-Z][A-Za-z0-9_\-/()]*", t):
            continue
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        vertical = (y1 - y0) > (x1 - x0) * 1.2 and len(t) > 1
        best = None
        for (a0, b0, a1, b1, n) in nums:
            if not (ytop <= b0 and b1 <= ybot):
                continue
            ncx, ncy = (a0 + a1) / 2, (b0 + b1) / 2
            if vertical:
                if abs(ncx - cx) > 3.5: continue
                d = abs(ncy - cy)
            else:
                if abs(ncy - cy) > 3.5: continue
                d = abs(ncx - cx)
            if best is None or d < best[0]:
                best = (d, int(n))
        if best:
            pins.setdefault(best[1], []).append(t)
    return pins

if __name__ == "__main__":
    pdf, p0, p1 = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
    for page in range(p0, p1 + 1):
        ws, caps, nums, labs = figures(pdf, page)
        caps = sorted(caps, key=lambda c: c[0][1])
        top = 0
        for c, title in caps:
            if not re.match(r"(Figure|图)\s*\d+-\d+", title):
                continue
            pins = pair(nums, labs, top, c[1])
            print(f"--- page {page}: {title}")
            print("   ", {k: "+".join(v) for k, v in sorted(pins.items())})
            top = c[3]
