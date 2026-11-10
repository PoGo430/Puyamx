"""Cortex-M0 simulator harness (Unicorn) with a register stub built from the chip database.

Runs functions of a compiled firmware (Init_All, usart1_print_u32 ...) and records what they do to the
peripheral registers.  There is no real peripheral behaviour: the stub only makes polling loops finish
(ready flags, calibration done, TXE/RXNE set ...) and applies the write-1-to-set/clear semantics of BSRR.
"""
import subprocess

from unicorn import UC_ARCH_ARM, UC_MODE_MCLASS, UC_MODE_THUMB, Uc
from unicorn.arm_const import UC_ARM_REG_LR, UC_ARM_REG_R0, UC_ARM_REG_SP

from puya_studio import toolchain

MAGIC = 0x0F000000          # "return address": reaching it stops the run
CORE_BASE, CORE_SIZE = 0xE0000000, 0x100000
PERIPH_BASE, PERIPH_SIZE = 0x40000000, 0x20000000


class Sim:
    def __init__(self, chip, elf, bin_path, flash_kb, ram_kb):
        self.chip = chip
        self.writes = []                     # (addr, value, size) in order
        self.regs = {}                       # addr -> current 32-bit value
        self.tx = []                         # bytes written to a USART data register
        self.uc = Uc(UC_ARCH_ARM, UC_MODE_THUMB | UC_MODE_MCLASS)
        try:
            from unicorn.unicorn_const import UC_CPU_ARM_CORTEX_M0
            self.uc.ctl_set_cpu_model(UC_CPU_ARM_CORTEX_M0)
        except Exception:
            pass
        uc = self.uc
        uc.mem_map(0x08000000, (flash_kb * 1024 + 0xFFF) & ~0xFFF)
        uc.mem_write(0x08000000, open(bin_path, "rb").read())
        uc.mem_map(0x20000000, (ram_kb * 1024 + 0xFFF) & ~0xFFF)
        uc.mem_map(0x1FFF0000, 0x1000)
        uc.mem_map(MAGIC, 0x1000)
        uc.mem_write(MAGIC, b"\x70\x47" * 8)                       # bx lr
        # factory information area: HSI words = (frequency index << 16) | trim, flash timing words = recognisable values
        for off in range(0, 0x1000, 4):
            uc.mem_write(0x1FFF0000 + off, (0xA5A50000 | off).to_bytes(4, "little"))
        for fs, addr in chip.clock["hsi"]["trim_addr"].items():
            uc.mem_write(addr, ((int(fs) << 16) | (0x1000 + int(fs))).to_bytes(4, "little"))
        uc.mmio_map(PERIPH_BASE, PERIPH_SIZE, lambda u, o, s, d: self._read(PERIPH_BASE + o, s), None,
                    lambda u, o, s, v, d: self._write(PERIPH_BASE + o, s, v), None)
        uc.mmio_map(CORE_BASE, CORE_SIZE, lambda u, o, s, d: self._read(CORE_BASE + o, s), None,
                    lambda u, o, s, v, d: self._write(CORE_BASE + o, s, v), None)
        self.symbols = self._nm(elf)
        self.ram_top = 0x20000000 + ram_kb * 1024
        self.resets = {p["base"] + r["off"]: r["reset"] for p in chip.peripherals.values() for r in p["regs"].values()}
        self.usart_dr = {p["base"] + p["regs"]["DR"]["off"] for n, p in chip.peripherals.items() if n.startswith("USART")}
        self.usart_sr = {p["base"] + p["regs"]["SR"]["off"] for n, p in chip.peripherals.items() if n.startswith("USART")}
        self.spi_sr = {p["base"] + p["regs"]["SR"]["off"] for n, p in chip.peripherals.items() if n.startswith("SPI")}
        self.gpio_bsrr = {p["base"] + p["regs"]["BSRR"]["off"]: p["base"] + p["regs"]["ODR"]["off"]
                          for n, p in chip.peripherals.items() if n.startswith("GPIO")}

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _nm(elf):
        out = subprocess.run([toolchain.tool("nm"), elf], capture_output=True, text=True).stdout
        syms = {}
        for line in out.splitlines():
            parts = line.split()
            if len(parts) == 3:
                syms[parts[2]] = int(parts[0], 16)
        return syms

    def addr(self, periph, reg):
        return self.chip.reg_addr(periph, reg)

    def mask(self, periph, reg, field):
        lsb, w = self.chip.reg(periph, reg)["fields"][field]
        return ((1 << w) - 1) << lsb

    def get(self, periph, reg):
        return self.regs.get(self.addr(periph, reg), self.resets.get(self.addr(periph, reg), 0))

    def field(self, periph, reg, field):
        lsb, w = self.chip.reg(periph, reg)["fields"][field]
        return (self.get(periph, reg) >> lsb) & ((1 << w) - 1)

    # ------------------------------------------------------------------ the register stub
    def _stored(self, a):
        return self.regs.get(a, self.resets.get(a, 0))

    def _read(self, a, size):
        base = a & ~3
        v = self._stored(base)
        c = self.chip
        rcc = c.peripherals["RCC"]["base"]
        if base == rcc:                                           # RCC_CR: oscillators / PLL ready when switched on
            f = c.reg("RCC", "CR")["fields"]
            for on, rdy in (("HSION", "HSIRDY"), ("HSEON", "HSERDY"), ("HSEEN", "HSERDY"), ("PLLON", "PLLRDY")):
                if on in f and rdy in f:
                    onm, rm = self.mask("RCC", "CR", on), self.mask("RCC", "CR", rdy)
                    v = (v | rm) if v & onm else (v & ~rm)
        elif base == rcc + 0x08:                                  # RCC_CFGR: SWS follows SW
            v = (v & ~0x38) | ((v & 7) << 3)
        elif base == self.addr("ADC", "ISR"):
            v |= 0x0E                                             # EOSMP | EOC | EOSEQ
        elif base in self.usart_sr:
            v |= 0xC0                                             # TXE | TC
        elif base in self.spi_sr:
            v |= 0x3                                              # RXNE | TXE
        elif base == self.addr("IWDG", "SR"):
            v = 0
        return (v >> (8 * (a & 3))) & ((1 << (8 * size)) - 1)

    def _write(self, a, size, value):
        base = a & ~3
        self.writes.append((a, value, size))
        if size < 4:
            sh = 8 * (a & 3)
            m = ((1 << (8 * size)) - 1) << sh
            value = (self._stored(base) & ~m) | ((value << sh) & m)
        if base in self.usart_dr:
            self.tx.append(value & 0xFF)
        if base in self.gpio_bsrr:                                 # BSRR sets / resets ODR bits
            odr = self.gpio_bsrr[base]
            cur = self._stored(odr)
            cur = (cur | (value & 0xFFFF)) & ~((value >> 16) & 0xFFFF)
            self.regs[odr] = cur
            self.regs[base] = 0
            return
        adc_cr = self.addr("ADC", "CR") if "ADC" in self.chip.peripherals else None
        if base == adc_cr:
            value &= ~(1 << 31)                                    # calibration finishes at once
            value &= ~(1 << 2)                                     # ADSTART self clears
        self.regs[base] = value & 0xFFFFFFFF

    # ------------------------------------------------------------------ running code
    def call(self, name, *args, max_insns=2_000_000):
        uc = self.uc
        uc.reg_write(UC_ARM_REG_SP, self.ram_top)
        uc.reg_write(UC_ARM_REG_LR, MAGIC | 1)
        for i, a in enumerate(args):
            uc.reg_write(UC_ARM_REG_R0 + i, a)
        uc.emu_start(self.symbols[name] | 1, MAGIC, count=max_insns)
        return uc.reg_read(UC_ARM_REG_R0)

    def ram_u32(self, symbol):
        return int.from_bytes(self.uc.mem_read(self.symbols[symbol], 4), "little")
