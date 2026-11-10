import os
import shutil
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(__file__))

from puya_studio import toolchain  # noqa: E402


def pytest_collection_modifyitems(config, items):
    if toolchain.find_gcc_bin() is None:
        skip = pytest.mark.skip(reason="arm-none-eabi-gcc not found (set PUYA_GCC)")
        for it in items:
            if "needs_gcc" in it.keywords:
                it.add_marker(skip)


def pytest_configure(config):
    config.addinivalue_line("markers", "needs_gcc: test compiles C code with arm-none-eabi-gcc")
