# Puya Studio – final plan

A CubeMX-style tool for **PY32F030**, **PY32F003** and **PY32F002B**.
Python 3 + PySide6, one-file PyInstaller build for Linux and Windows.

## Decisions (agreed with the user)
- Language/GUI: Python + PySide6; one downloadable file per OS, nothing to install.
- Chip picker: exact orderable part number (package variant, flash, RAM follow from the
  datasheet ordering table) **and** a manual override (chip -> package variant -> memory size).
- Packages: **all** footprints in the datasheets (LQFP, TSSOP, SOP, SSOP, MSOP, QFN, DFN),
  every pinout variant (K1/K2, F1..F6 ...) is its own package entry, read from the drawings.
  Dual-bonded pads (two ports on one pin): one clickable pad, the side panel picks the port.
  Exposed pads are drawn and marked as VSS.
- SWD/NRST pins may be reassigned, with a red Problem and a confirmation on Generate.
- Probes: user owns DAPLink (primary) and ST-Link V2 clones (both supported through pyOCD),
  serial bootloader as the probe-less fallback. Option bytes / read protection: always confirm.
- Toolchain: bundled xPack arm-none-eabi-gcc (trimmed to Cortex-M0+), real compile tested in CI.
- Newest document revision wins; conflicts between revisions are recorded in the chip DB
  (`notes`/`source`), anything not from Puya documents is marked `source="community"`.

## Architecture (`puya_studio/`)
chips/ (one DB file per chip, plus `common.py` model) · gen_header.py · codegen.py ·
checks.py · timing.py · project.py · toolchain.py · flasher.py · examples.py · ui/ · firmware-side
templates (startup, linker) in `templates/`. `tests/`, `packaging/`, `.github/workflows/`, `tools/`
(dev tools that extract data from the PDFs).

## Milestones (commit + push after each)
1. M1 chip DBs (pins from drawings, AF tables, registers, clocks, option bytes) + data tests
2. M2 header generator, codegen, examples, Unicorn simulator tests
3. M3 GUI (offscreen test drives every page and every pin function)
4. M4 flasher (pyOCD + Puya DFP, ST-Link/DAPLink, serial bootloader, option-byte safety)
5. M5 packaging, CI on Linux + Windows (Windows early), release workflow, README + screenshot

Progress is tracked in `PROGRESS.md`.
