"""Dev tool: cut the official Puya DFP down to the devices of the three chips (pdsc + flash algorithms).
Usage: make_trimmed_pack.py Puya.PY32F0xx_DFP.1.2.0.pack out.pack   (the original comes from Puya / the Keil pack server)."""
import re
import sys
import zipfile

src, dst = sys.argv[1], sys.argv[2]
z = zipfile.ZipFile(src)
pdsc = z.read("Puya.PY32F0xx_DFP.pdsc").decode("utf8")
need = set()
for m in re.finditer(r'<device Dname="(PY32F0(?:30|03|02B)x\d)"(.*?)</device>', pdsc, re.S):
    need.update(re.findall(r'<algorithm name="([^"]+)"', m.group(2)))
with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as out:
    out.writestr("Puya.PY32F0xx_DFP.pdsc", pdsc)
    for n in sorted(need):
        out.writestr(n, z.read(n))
print("kept", sorted(need))
