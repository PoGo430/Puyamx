# Dev tools (only needed to change the chip databases)

The program itself only reads `puya_studio/chips/*.json`. These scripts rebuild them from the documents:

| script | what it does |
|---|---|
| `extract_pinouts.py` | reads the package drawings of a datasheet PDF (vector text) -> pin number to label |
| `extract_af.py` | reads the Port A/B/F alternate-function tables (AF0-AF15) |
| `extract_analog.py` | reads ADC / comparator / oscillator functions from the pin tables |
| `extract_all.py DOCDIR` | runs the three above on the newest datasheets (`f030_cn22.pdf`, `f003_cn19.pdf`, `f002b_cn08.pdf`) -> `data/raw_*.json` |
| `db_facts.py` | facts typed from the documents (clocks, option bytes, features ...) with their source |
| `build_db.py DFP_DIR RMTXT_DIR` | merges everything with the Puya SVD files and the RM interrupt tables -> `puya_studio/chips/*.json` |
| `verify_regs.py RMTXT_DIR` | compares every register offset / reset value in the database with the reference manual text |
| `make_trimmed_pack.py` | cuts the Puya DFP down to the three chips (flash algorithms for pyOCD) |
| `make_screenshot.py` | renders the README screenshot |

All of them need poppler's `pdftotext`. The PDFs come from the Puya web site (blocked on some networks) or the mirror
<https://github.com/decaday/PY32_Docs>. `RMTXT_DIR` holds `pdftotext -layout` output of the three reference manuals
(`f030_rm_cn12.txt`, `f003_rm_cn12.txt`, `f002b_rm_cn04.txt`).

After a change run `python -m pytest tests/test_chips.py`: the expected values there were typed again by hand from the documents.
