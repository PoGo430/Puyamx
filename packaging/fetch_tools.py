"""Download and trim the bundled tools.   python packaging/fetch_tools.py [--out DIR]

Result: DIR/arm-none-eabi/{bin,libexec,lib,arm-none-eabi}  (xPack GNU Arm Embedded GCC, cut down to what a
Cortex-M0+ build with newlib-nano needs) - about 60 MB instead of 880 MB.

No installer is involved: Linux gets a .tar.gz, Windows a .zip, both unpacked with Python's own modules
(so there is no "installer ignores its target folder / keeps running" problem).
"""
import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import tarfile
import urllib.request
import zipfile

VERSION = "13.3.1-1.1"
BASE = f"https://github.com/xpack-dev-tools/arm-none-eabi-gcc-xpack/releases/download/v{VERSION}/"
ARCHIVES = {
    "linux": (f"xpack-arm-none-eabi-gcc-{VERSION}-linux-x64.tar.gz", "006c89337eced277fdf4c1c3bf3aebe55c85e8d52cba8d412009717fb781b959"),
    "win32": (f"xpack-arm-none-eabi-gcc-{VERSION}-win32-x64.zip", "49cda1bf01215f3df0613972d21f9fec3eb79dca82506365e7da2ff74b921733"),
}
GCC_VER = "13.3.1"
MULTILIB = os.path.join("thumb", "v6-m", "nofp")
KEEP_BIN = ["gcc", "gcc-" + GCC_VER, "as", "ld", "ld.bfd", "objcopy", "size", "nm", "objdump", "ar", "strip", "readelf"]


def platform_key():
    return "win32" if sys.platform.startswith("win") else "linux"


def download(url, dest, sha256):
    if os.path.exists(dest) and sha256_of(dest) == sha256:
        return
    print("downloading", url)
    last = None
    for attempt in range(4):
        try:
            with urllib.request.urlopen(url, timeout=120) as r, open(dest, "wb") as f:
                shutil.copyfileobj(r, f)
            break
        except Exception as e:                      # network hiccup: retry
            last = e
            print("  retry after:", e)
    else:
        raise SystemExit(f"download failed: {last}")
    got = sha256_of(dest)
    if got != sha256:
        os.remove(dest)
        raise SystemExit(f"checksum mismatch for {os.path.basename(dest)}: {got}")


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def extract(archive, dest):
    if archive.endswith(".zip"):
        with zipfile.ZipFile(archive) as z:
            z.extractall(dest)
    else:
        with tarfile.open(archive) as t:
            t.extractall(dest)


def copy(src, dst, win):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy2(src, dst)


def trim(root, out, win):
    exe = ".exe" if win else ""
    arm = os.path.join(out, "arm-none-eabi")
    if os.path.exists(arm):
        shutil.rmtree(arm)
    os.makedirs(os.path.join(arm, "bin"))
    # bin: the compiler driver, assembler, linker, binutils we call + every DLL next to them (Windows)
    for name in KEEP_BIN:
        for cand in (f"arm-none-eabi-{name}{exe}", f"arm-none-eabi-{name}"):
            p = os.path.join(root, "bin", cand)
            if os.path.exists(p):
                copy(p, os.path.join(arm, "bin", cand), win)
                break
    for f in os.listdir(os.path.join(root, "bin")):
        if f.lower().endswith((".dll", ".so", ".so.0")) or ".so." in f:
            copy(os.path.join(root, "bin", f), os.path.join(arm, "bin", f), win)
    # libexec: cc1, collect2, lto plugin/wrapper
    src = os.path.join(root, "libexec", "gcc", "arm-none-eabi", GCC_VER)
    dst = os.path.join(arm, "libexec", "gcc", "arm-none-eabi", GCC_VER)
    for f in os.listdir(src):
        if f.split(".")[0] in ("cc1", "collect2", "liblto_plugin", "lto-wrapper"):
            copy(os.path.join(src, f), os.path.join(dst, f), win)
    # runtime libraries next to them (found through RPATH $ORIGIN/../libexec; DLLs on Windows)
    lx = os.path.join(root, "libexec")
    for f in os.listdir(lx):
        p = os.path.join(lx, f)
        if os.path.isfile(p) and (".so" in f or f.lower().endswith(".dll")):
            copy(p, os.path.join(arm, "libexec", f), win)
    # gcc support library for v6-m, headers
    libgcc = os.path.join(root, "lib", "gcc", "arm-none-eabi", GCC_VER)
    for sub in ("include", "include-fixed"):
        if os.path.isdir(os.path.join(libgcc, sub)):
            shutil.copytree(os.path.join(libgcc, sub), os.path.join(arm, "lib", "gcc", "arm-none-eabi", GCC_VER, sub))
    ml = os.path.join(libgcc, MULTILIB)
    shutil.copytree(ml, os.path.join(arm, "lib", "gcc", "arm-none-eabi", GCC_VER, MULTILIB))
    # newlib: nano libraries for v6-m, headers, specs
    nl = os.path.join(root, "arm-none-eabi")
    shutil.copytree(os.path.join(nl, "include"), os.path.join(arm, "arm-none-eabi", "include"),
                    ignore=shutil.ignore_patterns("c++"))
    os.makedirs(os.path.join(arm, "arm-none-eabi", "lib", MULTILIB), exist_ok=True)
    for f in os.listdir(os.path.join(nl, "lib")):
        p = os.path.join(nl, "lib", f)
        if os.path.isfile(p) and f.endswith((".specs", ".ld")) and f in ("nano.specs", "nosys.specs", "rdimon.specs", "nano.specs"):
            copy(p, os.path.join(arm, "arm-none-eabi", "lib", f), win)
    for f in ("libc_nano.a", "libg_nano.a", "libm_nano.a", "libnosys.a", "crt0.o", "libc.a", "libg.a", "libm.a"):
        p = os.path.join(nl, "lib", MULTILIB, f)
        if os.path.exists(p):
            copy(p, os.path.join(arm, "arm-none-eabi", "lib", MULTILIB, f), win)
    for f in os.listdir(os.path.join(nl, "bin")) if os.path.isdir(os.path.join(nl, "bin")) else []:
        p = os.path.join(nl, "bin", f)
        if f in ("as" + exe, "ld" + exe, "ld.bfd" + exe, "ar" + exe, "objcopy" + exe, "nm" + exe, "strip" + exe, "ranlib" + exe, "objdump" + exe):
            copy(p, os.path.join(arm, "arm-none-eabi", "bin", f), win)
    for f in ("LICENSE", "README.md"):
        pass
    for lic in ("distro-info",):
        p = os.path.join(root, lic)
    open(os.path.join(arm, "SOURCE.txt"), "w").write(
        f"xPack GNU Arm Embedded GCC {VERSION} (GCC {GCC_VER}, newlib), https://github.com/xpack-dev-tools/arm-none-eabi-gcc-xpack\n"
        "Trimmed to the Cortex-M0+ (thumb/v6-m/nofp) parts. GPL-3.0 with the GCC Runtime Library Exception; source is available from the project above.\n")
    return arm


def selftest(arm, win):
    """Compile and link a tiny program with the trimmed compiler."""
    exe = ".exe" if win else ""
    gcc = os.path.join(arm, "bin", "arm-none-eabi-gcc" + exe)
    work = os.path.join(arm, "..", "selftest")
    os.makedirs(work, exist_ok=True)
    with open(os.path.join(work, "t.c"), "w") as f:
        f.write('#include <stdint.h>\n#include <string.h>\nvolatile uint32_t x;\nint main(void){ char b[8]; memset(b,1,8); x = 100u / (x + 3u) + b[2]; return (int) x; }\n'
                'void Reset_Handler(void){ main(); }\n')
    with open(os.path.join(work, "l.ld"), "w") as f:
        f.write("ENTRY(Reset_Handler) MEMORY { F (rx): ORIGIN = 0x08000000, LENGTH = 16K R (rwx): ORIGIN = 0x20000000, LENGTH = 2K }\n"
                "SECTIONS { .text : { *(.text*) *(.rodata*) } > F  .data : { *(.data*) } > R  .bss : { *(.bss*) } > R }\n")
    cmd = [gcc, "-mcpu=cortex-m0plus", "-mthumb", "-Os", "-Wall", "-Wextra", "-ffreestanding", "t.c", "-nostartfiles",
           "-T", "l.ld", "--specs=nano.specs", "--specs=nosys.specs", "-o", "t.elf"]
    r = subprocess.run(cmd, cwd=work, capture_output=True, text=True)
    if r.returncode != 0 or r.stderr.strip():
        info = [f"self test failed, exit code {r.returncode} (0x{r.returncode & 0xFFFFFFFF:08X})", "stdout:", r.stdout, "stderr:", r.stderr]
        v = subprocess.run([gcc, "-v", "-mcpu=cortex-m0plus", "-mthumb", "-c", "t.c", "-o", "t.o"], cwd=work, capture_output=True, text=True)
        info += ["---- gcc -v (exit %s):" % v.returncode, v.stdout[-3000:], v.stderr[-3000:]]
        for sub in ("bin", os.path.join("libexec", "gcc", "arm-none-eabi", GCC_VER), "libexec"):
            d = os.path.join(arm, sub)
            info.append(f"---- {sub}: " + ", ".join(sorted(os.listdir(d))) if os.path.isdir(d) else f"---- {sub}: missing")
        raise SystemExit("\n".join(info))
    size = subprocess.run([os.path.join(arm, "bin", "arm-none-eabi-size" + exe), "t.elf"], cwd=work, capture_output=True, text=True)
    print("self test ok:", size.stdout.strip().splitlines()[-1])
    shutil.rmtree(work)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None, help="output folder (default packaging/tools-<os>)")
    ap.add_argument("--cache", default=None, help="download/unpack cache folder")
    a = ap.parse_args()
    key = platform_key()
    win = key == "win32"
    here = os.path.dirname(os.path.abspath(__file__))
    out = a.out or os.path.join(here, f"tools-{key}")
    cache = a.cache or os.path.join(here, "work")
    os.makedirs(cache, exist_ok=True)
    name, sha = ARCHIVES[key]
    arch = os.path.join(cache, name)
    download(BASE + name, arch, sha)
    root = os.path.join(cache, f"xpack-arm-none-eabi-gcc-{VERSION}")
    if not os.path.isdir(root):
        extract(arch, cache)
    arm = trim(root, out, win)
    selftest(arm, win)
    total = sum(os.path.getsize(os.path.join(d, f)) for d, _, fs in os.walk(arm) for f in fs)
    print(f"trimmed compiler: {arm} ({total / 1e6:.0f} MB)")


if __name__ == "__main__":
    main()
