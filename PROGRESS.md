# Progress

Source documents (not committed, from the community mirror github.com/decaday/PY32_Docs):
F030 DS Rev2.2 (CN) / Rev1.4 EN, RM v1.2 · F003 DS Rev1.9 (CN) / Rev1.2 EN, RM v1.2 / v1.0 EN ·
F002B DS V0.8 (CN) / V0.3 EN, RM v0.4 / v0.2 EN.

- [x] M1 chip databases + data tests: pins (all leaded + QFN packages of the three main datasheets, every pinout variant),
      AF tables, analog functions, registers (Puya SVD, offsets/reset checked against the RM), IRQs (RM), clocks, option bytes.
      `python tools/build_db.py DFP_DIR RMTXT_DIR` rebuilds `puya_studio/chips/*.json`; `tools/verify_regs.py` re-checks the RM.
      **Phase 2 (not done yet):** the separate single-package datasheets (F003 SOP8/SOP8L2/SOP16/MSOP10/DFN8, F030 DFN8/QFN20F3)
      describe sub-families with their own function sets; the DB can hold them but they are not added.
- [x] M2 codegen / examples / simulator
- [x] M3 GUI
- [x] M4 programming (untested on real chips: see README checklist)
- [~] M5 packaging / CI / README: README, one-file build, CI written; verify CI runs green, then run the release workflow with a version

Notes for a resumed session: reference clones live in the session scratchpad and may be gone;
re-clone `decaday/PY32_Docs`, `IOsetting/py32f0-template`, `OpenPuya/PY32F0xx_Firmware` (git clone works
through the proxy, official Puya sites are blocked).
