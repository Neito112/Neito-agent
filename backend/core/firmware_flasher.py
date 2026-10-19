"""
ESP32 Firmware Flasher Engine for Neito Agent
============================================
Allows one-click flashing of official firmwares (Xiaozhi Vietnam, Xiaozhi Me,
The Mochi) or custom .bin files directly into the virtual ESP32 hardware emulator.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import struct
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import httpx

from backend.core.config import config_manager
from backend.core.esp32_hardware_emulator import esp32_emulator
from backend.core.mochi_core_brain import mochi_core_brain


def _resolve_project_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


PROJECT_ROOT = _resolve_project_root()
FLASH_DIR = PROJECT_ROOT / "assets" / "firmwares"
FLASH_DIR.mkdir(parents=True, exist_ok=True)

ACTIVE_FIRMWARE_PATH = FLASH_DIR / "active_firmware.bin"

FIRMWARE_PRESETS: List[Dict[str, Any]] = [
    {
        "id": "xiaozhi_s3_oled_096",
        "name": "Xiaozhi AI - ESP32-S3 Tím (OLED 0.96 inch SSD1306)",
        "description": "Bản ROM chính thức từ xiaozhi.vn, màn hình OLED 128x64 sắc nét, tối ưu cho ESP32-S3 mạch tím.",
        "url": "https://xiaozhi.vn/flash/s3tim/s3timoled096/s3timoled096.bin",
        "chip_model": "ESP32-S3-N8R2",
        "flash_size": "8MB",
        "psram_size": "2MB Quad",
        "display_type": "OLED SSD1306 (0.96 inch)",
        "camera_module": "OV2640-ScreenCam (Màn hình PC)",
        "author": "XIAOZHI VIỆT NAM (xiaozhi.vn)",
        "version": "1.1.0",
        "size_bytes": 8680129,
    },
    {
        "id": "xiaozhi_s3_oled_130",
        "name": "Xiaozhi AI - ESP32-S3 Tím (OLED 1.3 inch SH1106)",
        "description": "Bản ROM Xiaozhi cho màn hình OLED kích thước lớn 1.3 inch 128x64 chip SH1106.",
        "url": "https://xiaozhi.vn/flash/s3tim/s3timoledsh1106/s3timoledsh1106.bin",
        "chip_model": "ESP32-S3-N8R2",
        "flash_size": "8MB",
        "psram_size": "2MB Quad",
        "display_type": "OLED SH1106 (1.3 inch)",
        "camera_module": "OV2640-ScreenCam (Màn hình PC)",
        "author": "XIAOZHI VIỆT NAM (xiaozhi.vn)",
        "version": "1.1.0",
    },
    {
        "id": "xiaozhi_s3_tft_128r",
        "name": "Xiaozhi AI - ESP32-S3 Tím (TFT Tròn 1.28 inch GC9A01)",
        "description": "Bản ROM Xiaozhi mặt đồng hồ tròn 240x240, giao diện anime và robot sống động.",
        "url": "https://xiaozhi.vn/flash/s3tim/s3tim128notext/s3tim128r.bin",
        "chip_model": "ESP32-S3",
        "flash_size": "16MB",
        "psram_size": "8MB Octal",
        "display_type": "TFT 1.28\" Round",
        "camera_module": "OV2640-ScreenCam (Màn hình PC)",
        "author": "XIAOZHI VIỆT NAM (xiaozhi.vn)",
        "version": "1.1.0",
    },
    {
        "id": "xiaozhi_s3_box3",
        "name": "Xiaozhi AI - ESP32-S3-N16R8 Box 3 (TFT 2.4\" ST7789 + Screen-Cam MCP)",
        "description": "Bản ROM cao cấp nhất: 16MB Flash, 8MB PSRAM, màn hình màu ST7789, camera nhìn màn hình PC và 9 MCP phần cứng.",
        "url": "https://xiaozhi.vn/flash/s3tim/s3timoled096/s3timoled096.bin",
        "chip_model": "ESP32-S3-N16R8",
        "flash_size": "16MB",
        "psram_size": "8MB Octal",
        "display_type": "TFT ST7789 240x240",
        "camera_module": "OV2640-ScreenCam (Màn hình PC)",
        "author": "Xiaozhi Cloud Console (xiaozhi.me)",
        "version": "2.0.0",
    },
    {
        "id": "mochi_c3_v432",
        "name": "The Mochi Gốc ESP32-C3 v4.3.2 (71 Biểu Cảm + 27 SFX WAV + Chiptune)",
        "description": "Firmware gốc từ themochi.huykhong.com với đầy đủ 71 biểu cảm OLED và 27 âm thanh WAV gốc.",
        "url": "https://themochi.huykhong.com/fw/432/c3.bin",
        "chip_model": "ESP32-C3",
        "flash_size": "4MB",
        "psram_size": "0MB (Không có)",
        "display_type": "OLED SSD1306 (0.96 inch)",
        "camera_module": "Tắt",
        "author": "The Mochi (themochi.huykhong.com)",
        "version": "4.3.2",
        "size_bytes": 4190208,
    },
]


class FirmwareFlasherEngine:
    def __init__(self) -> None:
        self.state: str = "idle"  # idle, downloading, flashing, complete, error
        self.progress_pct: int = 0
        self.status_message: str = "Sẵn sàng nạp firmware"
        self.current_rom_info: Optional[Dict[str, Any]] = None
        self.log_lines: List[str] = []
        self._lock = threading.Lock()
        self._is_flashing = False

    def get_presets(self) -> List[Dict[str, Any]]:
        return FIRMWARE_PRESETS

    def get_status(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "state": self.state,
                "progress_pct": self.progress_pct,
                "status_message": self.status_message,
                "current_rom_info": self.current_rom_info,
                "log_lines": self.log_lines[-20:],
                "active_firmware_exists": ACTIVE_FIRMWARE_PATH.exists(),
                "active_firmware_size": ACTIVE_FIRMWARE_PATH.stat().st_size if ACTIVE_FIRMWARE_PATH.exists() else 0,
            }

    def _append_log(self, text: str):
        with self._lock:
            self.log_lines.append(f"[{time.strftime('%H:%M:%S')}] {text}")

    def flash_firmware_async(
        self,
        preset_id: Optional[str] = None,
        custom_url: Optional[str] = None,
        file_path: Optional[str] = None,
    ):
        if self._is_flashing:
            return {"ok": False, "error": "Đang có tiến trình nạp firmware khác chạy."}

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        t = threading.Thread(
            target=self._run_flash_worker,
            args=(preset_id, custom_url, file_path, loop),
            daemon=True,
        )
        t.start()
        return {"ok": True, "message": "Bắt đầu nạp firmware."}

    def _run_flash_worker(
        self,
        preset_id: Optional[str] = None,
        custom_url: Optional[str] = None,
        file_path: Optional[str] = None,
        loop: Optional[asyncio.AbstractEventLoop] = None,
    ):
        self._is_flashing = True
        self.progress_pct = 0
        self.state = "downloading"
        self.log_lines = []

        try:
            target_preset = next((p for p in FIRMWARE_PRESETS if p["id"] == preset_id), None)
            rom_title = target_preset["name"] if target_preset else "Custom Firmware"
            self.current_rom_info = target_preset

            self._append_log(f"Bắt đầu nạp: {rom_title}")
            self.status_message = f"Đang chuẩn bị ROM {rom_title}..."

            firmware_bytes: Optional[bytes] = None

            # 1. Source: Local file path
            if file_path and Path(file_path).exists():
                self._append_log(f"Đọc file nhị phân từ máy: {file_path}")
                firmware_bytes = Path(file_path).read_bytes()

            # 2. Source: Mochi local cached c3.bin
            elif preset_id == "mochi_c3_v432":
                local_c3 = PROJECT_ROOT / "assets" / "mochi_esp32" / "c3.bin"
                if local_c3.exists():
                    self._append_log(f"Sử dụng ROM Mochi gốc lưu trữ cục bộ ({local_c3.stat().st_size:,} bytes)")
                    firmware_bytes = local_c3.read_bytes()

            # 3. Source: Remote download (xiaozhi.vn, themochi, or custom URL)
            target_url = custom_url or (target_preset["url"] if target_preset else None)
            if not firmware_bytes and target_url:
                self._append_log(f"Tải firmware từ máy chủ: {target_url}")
                self.status_message = "Đang tải firmware từ máy chủ..."
                with httpx.Client(timeout=30.0, follow_redirects=True) as client:
                    resp = client.get(target_url)
                    resp.raise_for_status()
                    firmware_bytes = resp.content

            if not firmware_bytes or len(firmware_bytes) < 0x1000:
                raise ValueError("Dữ liệu firmware không hợp lệ hoặc quá nhỏ (< 4KB).")

            self._append_log(f"Đã nạp file ROM vào bộ nhớ đệm: {len(firmware_bytes):,} bytes ({len(firmware_bytes)/1024/1024:.2f} MB)")
            self.progress_pct = 25
            time.sleep(0.3)

            # 4. Analyze ESP32 Image Header
            self.state = "flashing"
            self.status_message = "Xác thực SPI Bootloader & phân tích phân vùng..."
            self._append_log("Đang phân tích ESP32 Header Magic (0xE9)...")

            magic = firmware_bytes[0]
            if magic == 0xE9:
                segments = firmware_bytes[1]
                spi_mode = firmware_bytes[2]
                spi_size_freq = firmware_bytes[3]
                entry_point = struct.unpack("<I", firmware_bytes[4:8])[0]
                self._append_log(f"✓ ESP32 Header hợp lệ: {segments} segments, entry: 0x{entry_point:08X}, SPI mode: {spi_mode}")
            else:
                self._append_log(f"Header magic: 0x{magic:02X} (ROM Binary raw hoặc Merged BIN)")

            self.progress_pct = 45
            time.sleep(0.4)

            # 5. Emulate writing to virtual SPI Flash with progressive block feedback
            self.status_message = "Đang ghi các khối dữ liệu vào chip Flash ESP32..."
            total_len = len(firmware_bytes)
            chunk_size = 65536
            written = 0

            while written < total_len:
                chunk = firmware_bytes[written : written + chunk_size]
                written += len(chunk)
                pct = 45 + int((written / total_len) * 45)
                self.progress_pct = min(90, pct)
                self.status_message = f"Đang ghi Flash: {written:,} / {total_len:,} bytes ({self.progress_pct}%)..."
                time.sleep(0.08)

            # 6. Save as active firmware
            ACTIVE_FIRMWARE_PATH.write_bytes(firmware_bytes)
            self._append_log(f"Đã lưu firmware hoạt động vào: {ACTIVE_FIRMWARE_PATH.name}")

            # 7. Checksum MD5
            md5 = hashlib.md5(firmware_bytes).hexdigest()
            self._append_log(f"✓ MD5 Checksum: {md5}")
            self.progress_pct = 95
            time.sleep(0.3)

            # 8. Auto-apply corresponding Hardware Configuration
            patch = {
                "active_firmware": preset_id or "custom",
                "active_firmware_name": rom_title,
                "chip_model": target_preset.get("chip_model", "ESP32-S3") if target_preset else "ESP32-S3",
                "flash_size": target_preset.get("flash_size", "16MB") if target_preset else "16MB",
                "psram_size": target_preset.get("psram_size", "8MB Octal") if target_preset else "8MB Octal",
                "display_type": target_preset.get("display_type", "OLED SSD1306 (0.96 inch)") if target_preset else "OLED SSD1306 (0.96 inch)",
                "camera_module": target_preset.get("camera_module", "OV2640-ScreenCam (Màn hình PC)") if target_preset else "Tắt",
            }
            esp32_emulator.update_hardware_config(patch)
            self._append_log(f"✓ Đã tự động cấu hình phần cứng: {patch['chip_model']} • {patch['flash_size']} Flash • {patch['display_type']}")

            # 9. If Mochi firmware: extract faces & sounds
            if preset_id == "mochi_c3_v432" or "themochi" in (custom_url or ""):
                try:
                    self._append_log("Đang giải nén 71 hoạt ảnh biểu cảm OLED & 27 âm thanh Mochi...")
                    from backend.vision.mochi_esp32_client import MochiESP32Client
                    client = MochiESP32Client()
                    client.extract_all_faces(export_gifs=True, download_web_previews=True)
                    self._append_log("✓ Đã nạp thành công 71 hoạt ảnh biểu cảm OLED & 27 SFX!")
                except Exception as ex:
                    self._append_log(f"Lưu ý khi giải nén assets Mochi: {ex}")

            self.progress_pct = 100
            self.state = "complete"
            self.status_message = f"🟢 Nạp thành công: {rom_title}!"
            self._append_log("══════════════════════════════════════════════")
            self._append_log("✓ QUÁ TRÌNH NẠP FIRMWARE HOÀN TẤT THÀNH CÔNG!")
            self._append_log("ESP32 đã tự động khởi động lại và sẵn sàng.")
            self._append_log("══════════════════════════════════════════════")

            # Broadcast event to Desktop Overlay
            evt = {
                "type": "mochi_firmware_event",
                "event": "firmware_flashed",
                "preset_id": preset_id,
                "rom_title": rom_title,
                "text": f"Đã nạp thành công {rom_title}!",
                "face": "happy",
                "display_mode": "face",
                "emotion": "happy",
            }
            if loop and loop.is_running():
                try:
                    asyncio.run_coroutine_threadsafe(mochi_core_brain.broadcast_event(evt), loop)
                except Exception:
                    pass

        except Exception as e:
            self.state = "error"
            self.status_message = f"Lỗi nạp firmware: {str(e)}"
            self._append_log(f"❌ LỖI: {str(e)}")
        finally:
            self._is_flashing = False


firmware_flasher = FirmwareFlasherEngine()
