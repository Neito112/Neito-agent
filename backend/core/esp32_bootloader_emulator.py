"""
ESP32 ROM Bootloader & SLIP Protocol Emulator
=============================================
Enables any web firmware flasher (esptool-js, esp-web-tools, Adafruit WebSerial,
themochi.huykhong.com, etc.) and native esptool.py to connect, sync, detect chip
(ESP32-S3 / ESP32-C3), read MAC, write flash partitions, and run code.
"""

from __future__ import annotations

import hashlib
import io
import struct
from typing import Callable, Dict, List, Optional, Tuple

SLIP_END = 0xC0
SLIP_ESC = 0xDB
SLIP_ESC_END = 0xDC
SLIP_ESC_ESC = 0xDD

# ESP32 Bootloader Opcodes
ESP_FLASH_BEGIN = 0x02
ESP_FLASH_DATA = 0x03
ESP_FLASH_END = 0x04
ESP_MEM_BEGIN = 0x05
ESP_MEM_END = 0x06
ESP_MEM_DATA = 0x07
ESP_SYNC = 0x08
ESP_WRITE_REG = 0x09
ESP_READ_REG = 0x0A
ESP_SPI_ATTACH = 0x0D
ESP_CHANGE_BAUDRATE = 0x0F
ESP_SPI_FLASH_MD5 = 0x13

# Chip Magic Numbers (returned for register reads)
CHIP_DETECT_REG = 0x60000078
DATE_REG = 0x6001A000
MAC_REG_BASE = 0x6001A004

CHIP_MAGIC_ESP32_S3 = 0x00000009
CHIP_MAGIC_ESP32_C3 = 0x00000005


def slip_encode(data: bytes) -> bytes:
    """Encodes raw packet into SLIP frame (wrapped with 0xC0)."""
    out = bytearray([SLIP_END])
    for b in data:
        if b == SLIP_END:
            out.extend([SLIP_ESC, SLIP_ESC_END])
        elif b == SLIP_ESC:
            out.extend([SLIP_ESC, SLIP_ESC_ESC])
        else:
            out.append(b)
    out.append(SLIP_END)
    return bytes(out)


def slip_decode_frames(buffer: bytes) -> Tuple[List[bytes], bytes]:
    """Extracts complete SLIP frames from stream buffer, returns (frames, remaining)."""
    frames: List[bytes] = []
    i = 0
    n = len(buffer)
    while i < n:
        if buffer[i] != SLIP_END:
            i += 1
            continue
        # Found start delimiter
        start = i + 1
        end = -1
        for j in range(start, n):
            if buffer[j] == SLIP_END:
                end = j
                break
        if end == -1:
            # Incomplete frame
            return frames, buffer[i:]
        # Unescape frame body
        raw_body = buffer[start:end]
        unescaped = bytearray()
        k = 0
        m = len(raw_body)
        while k < m:
            b = raw_body[k]
            if b == SLIP_ESC and k + 1 < m:
                nb = raw_body[k + 1]
                if nb == SLIP_ESC_END:
                    unescaped.append(SLIP_END)
                    k += 2
                    continue
                elif nb == SLIP_ESC_ESC:
                    unescaped.append(SLIP_ESC)
                    k += 2
                    continue
            unescaped.append(b)
            k += 1
        if len(unescaped) >= 8:
            frames.append(bytes(unescaped))
        i = end + 1
    return frames, b""


class ESP32BootloaderEmulator:
    """
    Virtual ESP32 ROM Bootloader responding to esptool SLIP protocol.
    Emulates an ESP32-S3 (or ESP32-C3) with full flash write and verify.
    """

    def __init__(
        self,
        mac_address: str = "EC:DA:3B:A1:7E:52",
        chip_type: str = "ESP32-S3",
        flash_size_mb: int = 16,
        psram_size_mb: int = 8,
    ):
        self.mac_bytes = bytes.fromhex(mac_address.replace(":", "").replace("-", ""))
        self.chip_type = chip_type.upper()
        self.flash_size_mb = flash_size_mb
        self.psram_size_mb = psram_size_mb
        self.is_flashing = False
        self.flash_buffer = bytearray()
        self.flash_write_offset = 0
        self.flash_total_size = 0
        self.flash_block_size = 1024
        self.flash_num_blocks = 0
        self.current_seq = 0
        self.on_flash_completed_callback: Optional[Callable[[bytes], None]] = None

    def build_response(self, opcode: int, value: int = 0, data: bytes = b"", status: int = 0, error: int = 0) -> bytes:
        """
        Builds esptool response header (8 bytes):
        [direction: 0x01, opcode: 1B, size: 2B (little endian), value: 4B (little endian)] + data + [status: 1B, error: 1B]
        """
        payload = data + bytes([status, error])
        hdr = struct.pack("<BBHI", 0x01, opcode, len(payload), value)
        return slip_encode(hdr + payload)

    def handle_slip_frame(self, frame: bytes) -> List[bytes]:
        """Parses a single unescaped SLIP request frame and returns encoded SLIP response frames."""
        if len(frame) < 8:
            return []
        direction, opcode, size, value = struct.unpack("<BBHI", frame[:8])
        data = frame[8 : 8 + size]

        responses: List[bytes] = []

        if opcode == ESP_SYNC:
            # esptool sends 36 bytes (0x07 0x07 0x12 0x20 + 32 times 0x55)
            # ESP32 replies with status 0, and then 7 frames of greeting
            responses.append(self.build_response(ESP_SYNC, value=0, status=0, error=0))
            for _ in range(7):
                greeting = bytes([0x07, 0x07, 0x12, 0x20])
                responses.append(self.build_response(ESP_SYNC, value=0, data=greeting, status=0, error=0))

        elif opcode == ESP_READ_REG:
            reg_addr = value
            reg_val = 0
            if reg_addr in (0x40001000, 0x60000078):
                if "C3" in self.chip_type:
                    reg_val = 1763790959  # ESP32-C3
                elif "C2" in self.chip_type:
                    reg_val = 1867591791  # ESP32-C2
                elif "C6" in self.chip_type:
                    reg_val = 752910447   # ESP32-C6
                else:
                    reg_val = 9           # ESP32-S3 (matches "case 9: ESP32S3ROM" in xiaozhi.vn)
            elif reg_addr in (0x6001A000, 1610612864, 0x60000080):
                reg_val = 0x20200700
            elif reg_addr in (0x60007044, 0x6001A004, 0x60008844):
                # MAC low 4 bytes (e.g. for EC:DA:3B:A1:7E:52 -> 0x3BA17E52)
                if len(self.mac_bytes) >= 6:
                    reg_val = (self.mac_bytes[2] << 24) | (self.mac_bytes[3] << 16) | (self.mac_bytes[4] << 8) | self.mac_bytes[5]
                elif len(self.mac_bytes) >= 4:
                    reg_val = struct.unpack("<I", self.mac_bytes[:4])[0]
            elif reg_addr in (0x60007048, 0x6001A008, 0x60008848):
                # MAC high 2 bytes (e.g. for EC:DA:3B:A1:7E:52 -> 0xECDA)
                if len(self.mac_bytes) >= 2:
                    reg_val = (self.mac_bytes[0] << 8) | self.mac_bytes[1]
            elif reg_addr == 0x60007050:
                reg_val = (1 << 24) | (2 << 18)  # blk_major: 1, minor: 2
            elif reg_addr == 0x60007054:
                psram_code = 1 if self.psram_size_mb >= 8 else (2 if self.psram_size_mb >= 2 else 0)
                reg_val = (1 << 7) | (psram_code << 3) | 1  # AP_3v3 vendor + PSRAM cap + XMC flash
            elif reg_addr == 0x60007058:
                reg_val = 0  # major version 0
            elif reg_addr == 0x60007068:
                reg_val = 1  # blk version major 1
            elif reg_addr in (0x60002000, 0x60003000):
                reg_val = 0  # SPI_CMD_REG operation done
            elif reg_addr in (0x60002058, 0x60002080, 0x60002010, 0x60003058):
                cap = 0x18 if self.flash_size_mb >= 16 else (0x17 if self.flash_size_mb >= 8 else (0x19 if self.flash_size_mb >= 32 else 0x16))
                reg_val = (cap << 16) | (0x40 << 8) | 0x20  # 0x00184020 for 16MB XMC
            elif reg_addr == 1070526796:
                reg_val = 3  # USB CDC block
            responses.append(self.build_response(ESP_READ_REG, value=reg_val, status=0, error=0))

        elif opcode == ESP_WRITE_REG:
            responses.append(self.build_response(ESP_WRITE_REG, value=0, status=0, error=0))

        elif opcode == ESP_SPI_ATTACH:
            # esptool connects SPI flash pins
            responses.append(self.build_response(ESP_SPI_ATTACH, value=0, status=0, error=0))

        elif opcode == ESP_CHANGE_BAUDRATE:
            # esptool requests higher speed (e.g. 460800 or 921600)
            responses.append(self.build_response(ESP_CHANGE_BAUDRATE, value=0, status=0, error=0))

        elif opcode in (ESP_FLASH_BEGIN, 0x0A):
            if len(data) >= 16:
                erase_size, num_blocks, block_size, offset = struct.unpack("<IIII", data[:16])
                self.flash_total_size = erase_size
                self.flash_num_blocks = num_blocks
                self.flash_block_size = block_size
                self.flash_write_offset = offset
                self.is_flashing = True
                self.current_seq = 0
                self.flash_buffer = bytearray()
            responses.append(self.build_response(opcode, value=0, status=0, error=0))

        elif opcode in (ESP_FLASH_DATA, 0x0B):
            if len(data) >= 16:
                data_size, seq, _, _ = struct.unpack("<IIII", data[:16])
                chunk = data[16 : 16 + data_size]
                self.flash_buffer.extend(chunk)
                self.current_seq = seq
            responses.append(self.build_response(opcode, value=0, status=0, error=0))

        elif opcode in (ESP_FLASH_END, 0x0C):
            self.is_flashing = False
            reboot_flag = value
            # Completed flashing! If firmware image was uploaded, trigger callback
            if self.on_flash_completed_callback and len(self.flash_buffer) > 0:
                try:
                    self.on_flash_completed_callback(bytes(self.flash_buffer))
                except Exception:
                    pass
            responses.append(self.build_response(opcode, value=0, status=0, error=0))

        elif opcode == ESP_SPI_FLASH_MD5:
            if len(data) >= 16:
                offset, size, _, _ = struct.unpack("<IIII", data[:16])
                sub = bytes(self.flash_buffer[:size]) if self.flash_buffer else b"\xff" * size
                md5_hex = hashlib.md5(sub).hexdigest()
                md5_bytes = bytes.fromhex(md5_hex)
                responses.append(self.build_response(ESP_SPI_FLASH_MD5, value=0, data=md5_bytes, status=0, error=0))
            else:
                responses.append(self.build_response(ESP_SPI_FLASH_MD5, value=0, status=0, error=0))

        else:
            # Generic success for unknown opcodes
            responses.append(self.build_response(opcode, value=0, status=0, error=0))

        return responses


class ESP32UnifiedSerialRouter:
    """
    Handles both binary esptool SLIP bootloader packets (firmware flashing)
    and ASCII Mochi serial commands (set:get, gif_speed, set:save, etc.)
    on the same serial stream.
    """

    def __init__(self, bootloader: Optional[ESP32BootloaderEmulator] = None):
        self.bootloader = bootloader or ESP32BootloaderEmulator()
        self.slip_buffer = bytearray()
        self.text_buffer = ""

    def process_incoming_chunk(self, chunk: bytes) -> Tuple[List[bytes], List[str]]:
        """
        Processes an incoming raw byte chunk.
        Returns:
            binary_replies: List[bytes] (to send back as raw bytes/SLIP)
            text_lines: List[str] (ASCII commands to pass to mochi_core_brain)
        """
        if not chunk:
            return [], []

        # Check if stream is SLIP-framed (0xC0) or currently flashing
        if SLIP_END in chunk or self.bootloader.is_flashing or len(self.slip_buffer) > 0:
            self.slip_buffer.extend(chunk)
            frames, rem = slip_decode_frames(bytes(self.slip_buffer))
            self.slip_buffer = bytearray(rem)
            binary_replies: List[bytes] = []
            for frame in frames:
                replies = self.bootloader.handle_slip_frame(frame)
                binary_replies.extend(replies)
            return binary_replies, []

        # Otherwise treat as newline-terminated ASCII text commands
        text = chunk.decode("utf-8", errors="ignore")
        self.text_buffer += text
        lines = self.text_buffer.split("\n")
        self.text_buffer = lines.pop() or ""
        valid_lines = [l.strip() for l in lines if l.strip()]
        return [], valid_lines


esp32_bootloader = ESP32BootloaderEmulator()
esp32_serial_router = ESP32UnifiedSerialRouter(esp32_bootloader)

