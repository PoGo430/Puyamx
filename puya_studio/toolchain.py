"""Finds and runs the ARM compiler: build a project folder, parse errors, report ROM/RAM use."""
import glob
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field

IS_WIN = sys.platform.startswith("win")
EXE = ".exe" if IS_WIN else ""
PREFIX = "arm-none-eabi-"
CFLAGS = ["-mcpu=cortex-m0plus", "-mthumb", "-Os", "-g", "-Wall", "-Wextra", "-ffunction-sections", "-fdata-sections",
          "-ffreestanding", "-std=gnu11"]
LDFLAGS = ["-mcpu=cortex-m0plus", "-mthumb", "-nostartfiles", "-Wl,--gc-sections", "-T", "link.ld",
           "--specs=nano.specs", "--specs=nosys.specs"]


def app_dir():
    """Folder of the program (PyInstaller unpack folder, or the repository root when run from source)."""
    if getattr(sys, "_MEIPASS", None):
        return sys._MEIPASS
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def find_gcc_bin():
    """Directory containing arm-none-eabi-gcc, or None.  Order: PUYA_GCC env var, bundled copy, PATH."""
    cands = []
    if os.environ.get("PUYA_GCC"):
        cands.append(os.environ["PUYA_GCC"])
    base = app_dir()
    cands += [os.path.join(base, "tools", "arm-none-eabi", "bin"), os.path.join(base, "packaging", "tools", "arm-none-eabi", "bin")]
    cands += glob.glob(os.path.join(base, "packaging", "tools-*", "arm-none-eabi", "bin"))
    for d in cands:
        if os.path.exists(os.path.join(d, PREFIX + "gcc" + EXE)):
            return d
    which = shutil.which(PREFIX + "gcc")
    return os.path.dirname(which) if which else None


def tool(name):
    d = find_gcc_bin()
    if d is None:
        return None
    return os.path.join(d, PREFIX + name + EXE)


def gcc_version():
    gcc = tool("gcc")
    if not gcc:
        return None
    try:
        out = subprocess.run([gcc, "--version"], capture_output=True, text=True, timeout=30).stdout
        return out.splitlines()[0]
    except Exception:
        return None


DIAG = re.compile(r"^(?P<file>(?:[A-Za-z]:)?[^:\n]+?):(?P<line>\d+):(?:(?P<col>\d+):)?\s*(?P<sev>fatal error|error|warning|note):\s*(?P<msg>.*)$")


@dataclass
class Diagnostic:
    file: str
    line: int
    col: int
    severity: str
    message: str


@dataclass
class BuildResult:
    ok: bool = False
    diagnostics: list = field(default_factory=list)
    log: str = ""
    rom: int = 0           # bytes of flash used (text + data)
    ram: int = 0           # bytes of RAM used (data + bss)
    flash_size: int = 0
    ram_size: int = 0
    elf: str = ""
    bin: str = ""
    hex: str = ""

    @property
    def warnings(self):
        return [d for d in self.diagnostics if d.severity == "warning"]

    @property
    def errors(self):
        return [d for d in self.diagnostics if d.severity in ("error", "fatal error")]


def parse_diagnostics(text, folder=""):
    out = []
    for line in text.splitlines():
        m = DIAG.match(line.strip())
        if m:
            f = m.group("file")
            out.append(Diagnostic(os.path.basename(f) if folder and os.path.dirname(f) in ("", ".") else f,
                                  int(m.group("line")), int(m.group("col") or 1), m.group("sev").replace("fatal ", ""), m.group("msg")))
    return out


def parse_size(text):
    """`size` Berkeley format -> (text, data, bss)."""
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[0].isdigit() and parts[1].isdigit() and parts[2].isdigit():
            return int(parts[0]), int(parts[1]), int(parts[2])
    return 0, 0, 0


def read_limits(folder):
    """Flash / RAM size from the generated link.ld."""
    try:
        t = open(os.path.join(folder, "link.ld"), encoding="utf8").read()
        f = int(re.search(r"FLASH.*LENGTH = (\d+)K", t).group(1)) * 1024
        r = int(re.search(r"RAM .*LENGTH = (\d+)K", t).group(1)) * 1024
        return f, r
    except Exception:
        return 0, 0


def sources(folder):
    return sorted(os.path.basename(p) for p in glob.glob(os.path.join(folder, "*.c")))


def build(folder, name=None, extra_cflags=(), werror=False):
    """Compile every .c file in `folder` into build/<name>.elf/.bin/.hex."""
    res = BuildResult()
    gcc = tool("gcc")
    if not gcc:
        res.log = "arm-none-eabi-gcc not found (set PUYA_GCC or install the compiler)."
        res.diagnostics.append(Diagnostic("", 0, 0, "error", res.log))
        return res
    name = name or "firmware"
    bdir = os.path.join(folder, "build")
    os.makedirs(bdir, exist_ok=True)
    elf = os.path.join(bdir, name + ".elf")
    cmd = [gcc] + CFLAGS + list(extra_cflags) + (["-Werror"] if werror else []) + sources(folder) + LDFLAGS + \
        [f"-Wl,-Map={os.path.join('build', name + '.map')}", "-o", os.path.join("build", name + ".elf")]
    p = subprocess.run(cmd, cwd=folder, capture_output=True, text=True)
    res.log = (p.stdout or "") + (p.stderr or "")
    res.diagnostics = parse_diagnostics(res.log, folder)
    res.flash_size, res.ram_size = read_limits(folder)
    if p.returncode != 0:
        if not res.errors:
            res.diagnostics.append(Diagnostic("", 0, 0, "error", res.log.strip().splitlines()[-1] if res.log.strip() else "build failed"))
        return res
    res.elf = elf
    binf, hexf = os.path.join(bdir, name + ".bin"), os.path.join(bdir, name + ".hex")
    subprocess.run([tool("objcopy"), "-O", "binary", elf, binf], check=True, capture_output=True)
    subprocess.run([tool("objcopy"), "-O", "ihex", elf, hexf], check=True, capture_output=True)
    sz = subprocess.run([tool("size"), elf], capture_output=True, text=True).stdout
    t, d, b = parse_size(sz)
    res.rom, res.ram = t + d, d + b
    res.bin, res.hex = binf, hexf
    res.ok = True
    return res
