"""Every function of every pin of every chip: the generator must produce code that compiles without warnings."""
import os
import tempfile

import pytest

from puya_studio import chips, codegen, toolchain
from puya_studio.project import Project

pytestmark = pytest.mark.needs_gcc


def functions(p, port):
    return [f["id"] for f in p.functions_for(port)]


@pytest.mark.parametrize("chip_id", chips.CHIP_NAMES)
def test_generator_handles_every_function_of_every_pin(chip_id):
    """All functions are generated (python only); every function number round r goes into one compiled project."""
    base = Project(chip_id)
    ports = sorted(base.chip.ports)
    longest = max(len(functions(base, port)) for port in ports)
    for r in range(longest):
        p = Project(chip_id)
        p.name = f"round{r}"
        for port in ports:
            fl = functions(p, port)
            f = fl[r % len(fl)]
            if f == "unused":
                continue
            p.assign(port, f, label=f"P{port[1:]}x")
        if p.clock:
            pass
        folder = tempfile.mkdtemp()
        try:
            codegen.generate(p, folder)
        except codegen.GenError as e:
            pytest.fail(f"round {r}: {e}")
        res = toolchain.build(folder, "fw")
        assert res.ok, (r, [d.message for d in res.errors][:3], res.log[:600])
        assert not res.warnings, (r, [d.message for d in res.warnings][:3])
