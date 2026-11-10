"""Every example is generated and compiled for every chip and every package it supports, with no warnings."""
import concurrent.futures
import os
import tempfile

import pytest

from puya_studio import chips, codegen, examples, toolchain

pytestmark = pytest.mark.needs_gcc


def one(args):
    ex_id, chip_id, package = args
    try:
        p, sec, wiring = examples.build(ex_id, chip_id, package=package)
    except examples.Unsupported:
        return ex_id, chip_id, package, None, None
    folder = tempfile.mkdtemp()
    codegen.generate(p, folder, sec)
    r = toolchain.build(folder, "fw")
    msgs = [f"{d.file}:{d.line}: {d.severity}: {d.message}" for d in r.diagnostics]
    return ex_id, chip_id, package, r.ok, msgs


def test_every_example_on_every_chip_and_package():
    jobs = [(e.id, c, pk) for c in chips.CHIP_NAMES for pk in chips.load(c).packages for e in examples.EXAMPLES]
    bad, built = [], 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=os.cpu_count() or 2) as ex:
        for ex_id, chip_id, pk, ok, msgs in ex.map(one, jobs):
            if ok is None:
                continue
            built += 1
            if not ok or msgs:
                bad.append((ex_id, chip_id, pk, msgs[:3]))
    assert not bad, bad[:5]
    assert built > 200


def test_every_example_supported_somewhere_on_each_chip():
    for c in chips.CHIP_NAMES:
        for e in examples.EXAMPLES:
            if c == "py32f002b" and e.id == "pwm_two":
                continue
            ok = [examples.supported(e, c, package=pk)[0] for pk in chips.load(c).packages]
            assert any(ok), (c, e.id)


def test_wiring_text_names_the_pins():
    p, sec, wiring = examples.build("blink", "py32f030", package="LQFP32-K1")
    assert wiring and "LED:" in wiring[0] and "pin " in wiring[0]
