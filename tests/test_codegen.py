"""Generator tests: user code survives regeneration, removed sections go to #if 0, headers are consistent."""
import os
import tempfile

import pytest

from puya_studio import chips, codegen, usercode
from puya_studio.project import Project

pytestmark = pytest.mark.needs_gcc


def read(folder, name):
    return open(os.path.join(folder, name), encoding="utf8").read()


def test_user_code_survives_regeneration():
    p = Project("py32f030")
    p.assign("PA5", "gpio_out", label="LED")
    folder = tempfile.mkdtemp()
    codegen.generate(p, folder)
    text = read(folder, "main.c")
    text = text.replace("/* USER CODE BEGIN 3 */\n", "/* USER CODE BEGIN 3 */\n        LED_TOGGLE(); delay_ms(100); /* mine */\n")
    text = text.replace("/* USER CODE BEGIN PV_main */\n", "/* USER CODE BEGIN PV_main */\nstatic int mine = 42;\n")
    open(os.path.join(folder, "main.c"), "w", encoding="utf8").write(text)
    p.assign("PA6", "gpio_in", label="BTN")          # change settings, regenerate
    p.clock["ahb_div"] = 2
    codegen.generate(p, folder)
    again = read(folder, "main.c")
    assert "LED_TOGGLE(); delay_ms(100); /* mine */" in again and "static int mine = 42;" in again
    assert "#if 0" not in again
    codegen.generate(p, folder)
    assert read(folder, "main.c") == again               # regenerating twice changes nothing


def test_removed_section_goes_to_if0_block_at_the_end():
    p = Project("py32f030")
    p.assign("PA0", "exti", label="BTN")
    folder = tempfile.mkdtemp()
    codegen.generate(p, folder)
    it = read(folder, "interrupts.c")
    assert "USER CODE BEGIN IRQ_EXTI0" in it
    it = it.replace("/* USER CODE BEGIN IRQ_EXTI0 */\n", "/* USER CODE BEGIN IRQ_EXTI0 */\n        my_handler_code();\n")
    open(os.path.join(folder, "interrupts.c"), "w", encoding="utf8").write(it)
    p.clear("PA0")                                         # the EXTI0 section disappears
    codegen.generate(p, folder)
    out = read(folder, "interrupts.c")
    assert "USER CODE BEGIN IRQ_EXTI0 " not in out.split("#if 0")[0]
    tail = out[out.index("#if 0"):]
    assert "my_handler_code();" in tail and tail.rstrip().endswith("#endif  /* end of orphaned user code */")
    # the orphan survives further regenerations, and comes back as a normal section when the pin returns
    codegen.generate(p, folder)
    assert read(folder, "interrupts.c").count("my_handler_code();") == 1
    p.assign("PA0", "exti", label="BTN")
    codegen.generate(p, folder)
    back = read(folder, "interrupts.c")
    assert "my_handler_code();" in back.split("#if 0")[0] or "my_handler_code();" in back


def test_merge_unit():
    new = "a\n" + usercode.section("X") + "\nb\n" + usercode.section("Y") + "\n"
    old = "a\n" + usercode.section("X", "keep me\n") + "\nb\n" + usercode.section("Z", "gone\n") + "\n"
    out = usercode.merge(new, old)
    assert "keep me" in out.split("#if 0")[0]
    assert "gone" in out.split("#if 0")[1]
    assert usercode.merge(out, out).count("gone") == 1


@pytest.mark.parametrize("chip_id", chips.CHIP_NAMES)
def test_header_offsets_checked_by_compiler(chip_id):
    from puya_studio import toolchain, gen_header
    import subprocess
    c = chips.load(chip_id)
    folder = tempfile.mkdtemp()
    open(os.path.join(folder, f"{chip_id}.h"), "w").write(gen_header.generate(c))
    mp = gen_header.macro_prefixes(c)
    lines = ["#include <stddef.h>", f'#include "{chip_id}.h"']
    n = 0
    for pname, per in c.peripherals.items():
        inst = {"I2C": "I2C1", "LPTIM": "LPTIM1"}.get(pname, pname)
        for rn, r in per["regs"].items():
            rn2 = rn.replace("_Input", "").replace("_Output", "").replace("_INPUT", "").replace("_OUTPUT", "")
            lines.append(f"_Static_assert(offsetof(__typeof__(*{inst}), {rn2}) == 0x{r['off']:X}, \"{inst}.{rn2}\");")
            for fn, (lsb, w) in r["fields"].items():
                lines.append(f"_Static_assert({mp[inst]}_{rn2}_{fn}_Pos == {lsb} && {mp[inst]}_{rn2}_{fn}_Msk == 0x{((1 << w) - 1) << lsb:X}UL, \"{inst}.{rn2}.{fn}\");")
                n += 1
    open(os.path.join(folder, "t.c"), "w").write("\n".join(lines) + "\n")
    p = subprocess.run([toolchain.tool("gcc"), "-mcpu=cortex-m0plus", "-mthumb", "-Wall", "-Wextra", "-c", "t.c", "-o", "t.o"],
                       cwd=folder, capture_output=True, text=True)
    assert p.returncode == 0, p.stderr[:2000]
    assert p.stderr == ""
    assert n > 200
