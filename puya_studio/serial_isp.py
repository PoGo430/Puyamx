"""Serial boot loader programmer (PY32F030 / PY32F003; NOT available on the PY32F002B).

Protocol (STM32-like frames, 8 data bits, EVEN parity, 1 stop bit, baud rate auto-detected from 0x7F):
    sync 0x7F -> ACK 0x79 (or NACK 0x1F if already synchronised)
    command byte + complement -> ACK;  Get 0x00, Version 0x01, ID 0x02, Read 0x11, Go 0x21, Write 0x31,
    Erase 0x44 (0xFFFF = whole chip), unlock-read-protection 0x92 (mass erase).
    address = 4 bytes big endian + xor byte;  blocks of up to 128 bytes.
Source of the protocol: the community tool puyaisp.py by Stefan Wagner (MIT licence), which the PY32F0xx
boot loader has been tested with - Puya publishes no protocol document.  This is an independent
implementation, tested here only against a simulated boot loader: see "Hardware checklist" in the README.
The class takes any pyserial-like port, so the tests can use a fake chip.
"""
import time

ACK, NACK, BUSY, SYNC = 0x79, 0x1F, 0xAA, 0x7F
CMD_GET, CMD_VER, CMD_ID, CMD_READ, CMD_GO, CMD_WRITE, CMD_ERASE, CMD_RUNLOCK = 0x00, 0x01, 0x02, 0x11, 0x21, 0x31, 0x44, 0x92
BLOCK = 128
FLASH_BASE = 0x08000000
ERASE_TIMEOUT = 10.0
KNOWN_IDS = {0x440: "PY32F002A / PY32F003 / PY32F030"}


class IspError(Exception):
    pass


class Isp:
    def __init__(self, port, log=lambda s: None):
        self.port = port
        self.log = log
        self.pid = None
        self.version = None

    # ------------------------------------------------------------------ low level
    def _read(self, n):
        return self.port.read(n)

    def _reply(self):
        b = self._read(1)
        return b[0] if len(b) == 1 else None

    def _ack(self, what):
        r = self._reply()
        if r != ACK:
            raise IspError(f"no ACK for {what} (got {'nothing' if r is None else hex(r)})")

    def command(self, cmd):
        self.port.write(bytes([cmd, cmd ^ 0xFF]))
        self._ack(f"command 0x{cmd:02X}")

    def address(self, addr):
        b = addr.to_bytes(4, "big")
        x = b[0] ^ b[1] ^ b[2] ^ b[3]
        self.port.write(b + bytes([x]))
        self._ack(f"address 0x{addr:08X}")

    def wait_ack(self, timeout):
        end = time.time() + timeout
        while time.time() < end:
            r = self._reply()
            if r is None or r == BUSY:
                continue
            return r == ACK
        return False

    # ------------------------------------------------------------------ session
    def sync(self):
        """Send 0x7F; the boot loader must answer ACK (or NACK when it is already synchronised)."""
        self.port.reset_input_buffer()
        self.port.write(bytes([SYNC]))
        r = self._reply()
        if r not in (ACK, NACK):
            raise IspError("the chip did not answer: BOOT0 high at reset? TX/RX crossed? (PY32F002B has no serial boot loader)")
        self.port.reset_input_buffer()

    def _info(self, cmd):
        self.command(cmd)
        n = self._read(1)
        if not n:
            raise IspError("no length byte in the answer")
        data = self._read(n[0] + 1)
        self._ack("end of answer")
        return data

    def identify(self):
        self.version = self._info(CMD_GET)[0]
        self.pid = int.from_bytes(self._info(CMD_ID), "big")
        return self.pid

    # ------------------------------------------------------------------ memory
    def read(self, addr, size, progress=None):
        out = bytearray()
        while size > 0:
            n = min(size, BLOCK)
            self.command(CMD_READ)
            self.address(addr)
            self.command(n - 1)
            blk = self._read(n)
            if len(blk) != n:
                raise IspError(f"short read at 0x{addr:08X}")
            out += blk
            addr += n
            size -= n
            if progress:
                progress(n)
        return bytes(out)

    def write(self, addr, data, progress=None):
        data = bytes(data)
        for off in range(0, len(data), BLOCK):
            blk = data[off:off + BLOCK]
            parity = len(blk) - 1
            for x in blk:
                parity ^= x
            self.command(CMD_WRITE)
            self.address(addr + off)
            self.port.write(bytes([len(blk) - 1]) + blk + bytes([parity]))
            if not self.wait_ack(5.0):
                raise IspError(f"write failed at 0x{addr + off:08X}")
            if progress:
                progress(len(blk))

    def erase_all(self):
        self.command(CMD_ERASE)
        self.port.write(b"\xff\xff\x00")
        if not self.wait_ack(ERASE_TIMEOUT):
            raise IspError("mass erase failed (write protection set?)")

    def unlock_read_protection(self):
        """Removes read protection; the chip erases all flash."""
        self.command(CMD_RUNLOCK)
        if not self.wait_ack(ERASE_TIMEOUT):
            raise IspError("unlock failed")

    def go(self, addr=FLASH_BASE):
        self.command(CMD_GO)
        self.address(addr)

    # ------------------------------------------------------------------ high level
    def program(self, data, erase=True, verify=True, progress=None, base=FLASH_BASE):
        data = bytes(data)
        if len(data) % 4:
            data += b"\xff" * (4 - len(data) % 4)
        if erase:
            self.log("erasing the whole flash")
            self.erase_all()
        self.log(f"writing {len(data)} bytes")
        self.write(base, data, progress)
        if verify:
            self.log("verifying")
            back = self.read(base, len(data))
            if back != data:
                bad = next(i for i in range(len(data)) if back[i] != data[i])
                raise IspError(f"verify failed at 0x{base + bad:08X}")
        return len(data)


def open_port(device, baud=115200, timeout=1.0):
    import serial
    return serial.Serial(device, baudrate=baud, parity=serial.PARITY_EVEN, timeout=timeout)


def enter_bootloader(port):
    """Adapters with control lines (e.g. CH340X): DTR low = BOOT0 high, RTS pulse = reset (the wiring PuyaISP expects;
    sequence as used by the community tool, not documented by Puya).  Without such wiring do it by hand: BOOT0 to VCC,
    then press reset."""
    try:
        port.rts = False
        port.dtr = False
        port.rts = True
        time.sleep(0.01)
        port.rts = False
        time.sleep(0.01)
    except Exception:
        pass


def leave_bootloader(port, reset=True):
    """BOOT0 back to low and (optionally) a reset pulse so that the new firmware starts."""
    try:
        port.dtr = True
        if reset:
            port.rts = True
            time.sleep(0.01)
            port.rts = False
    except Exception:
        pass
