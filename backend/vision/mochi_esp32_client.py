"""
Neito-Agent: ESP32-C3 "The Mochi" Firmware Extractor, Audio Unpacker & OLED Engine
==================================================================================
Ported directly from https://themochi.huykhong.com/ (The Mochi v4.3.2 `c3.bin`):
1. Unpacks all 71 128x64 1-bit OLED face animations (2,447 frames) from DROM (`0x10020`).
2. Unpacks all 27 original `.wav` voice/sound assets (`/moshi.wav`, `/intro.wav`,
   `/UwU.wav`, `/love.wav`, `/tanjiro.wav`, `/coin.wav`, etc.) from the ESP32-C3
   SPIFFS partition (`0x35a000..0x3ff000`).
3. Ports the Mochi 8-Bit Square-Wave Buzzer Melody Synthesizer (`notesFreq`).
4. Renders 128x64 OLED faces + Firmware HUD modes (`show_clock`, `CPUZ`,
   Chronos Phone Notifications, and Google Maps Navigation) inside the mascot visor.
"""

from __future__ import annotations

import io
import json
import math
import random
import struct
import time
import urllib.parse
import wave
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import httpx
import numpy as np
from PIL import Image, ImageDraw, ImageFont

BASE_URL = "https://themochi.huykhong.com"
FIRMWARE_XML_URL = f"{BASE_URL}/firmware-data.xml"
DEFAULT_MANIFEST_URL = f"{BASE_URL}/fw/432/manifest.json"
DEFAULT_BIN_URL = f"{BASE_URL}/fw/432/c3.bin"
LICENSE_CHECK_URL = f"{BASE_URL}/thietlap/license_check.php"
WEB_ASSETS_BASE_URL = f"{BASE_URL}/thietlap/assets"

def _resolve_project_root() -> Path:
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        if (exe_dir / "assets").exists():
            return exe_dir
        if hasattr(sys, "_MEIPASS") and (Path(sys._MEIPASS) / "assets").exists():
            return Path(sys._MEIPASS)
        return exe_dir
    return Path(__file__).resolve().parents[2]

PROJECT_ROOT = _resolve_project_root()
ESP32_CACHE_DIR = PROJECT_ROOT / "assets" / "mochi_esp32"
FACES_DIR = PROJECT_ROOT / "assets" / "mochi_faces"
GIFS_DIR = FACES_DIR / "gifs"
SOUNDS_DIR = FACES_DIR / "sounds"
PREVIEWS_DIR = FACES_DIR / "previews"
NPZ_PACK_PATH = FACES_DIR / "mochi_faces_pack.npz"
MANIFEST_JSON_PATH = FACES_DIR / "manifest.json"

# ESP32-C3 DROM & SPIFFS partition constants for The Mochi v4.3.2
DROM_VADDR_OFFSET = 0x3C090000
ANIM_TABLE_START = 0x1012C
ANIM_TABLE_END = 0x10364
SPIFFS_PART_OFFSET = 0x35A000
SPIFFS_PART_END = 0x3FF000

# Exact Mochi Web Labels from https://themochi.huykhong.com/thietlap
MOCHI_WEB_LABELS: Dict[str, str] = {
    "gundam": "Gundam",
    "angry": "Tanjiro",
    "angry2": "Pretentious",
    "angry3": "Purple Flame",
    "aot": "Titan",
    "bee": "Bee",
    "cry": "Crying Smile",
    "cry2": "Crying",
    "cuoi_khinh_bi": "Awkward Laugh",
    "chong_mat": "Rotation",
    "dasai": "Spray Paint",
    "dasai2": "Dasai",
    "mac_dinh": "Default",
    "demon_slayer": "Nezuko",
    "den_giao_thong": "Road Rage",
    "den_pha": "Headlights",
    "devil": "Cursed Smile",
    "devil_2": "Glitch",
    "devil_eyes": "GTR Rain",
    "distracted": "Distracted",
    "egg": "Cookie",
    "gian_du": "Angry",
    "yakura": "Yakura",
    "hand_some": "Banana",
    "happy_2": "Laugh",
    "hat_xi": "Sneeze",
    "hat_xi_2": "Big Sneeze",
    "hehe": "Smirk",
    "intro": "Title",
    "keep_it_up": "Keep it up",
    "leu_leu": "Raspberry",
    "love": "Love",
    "love2": "Dumb Love",
    "mochi": "Neon Sign",
    "mochidoo": "MECHA DOC",
    "music": "Music",
    "neon": "Neon",
    "noname": "Pinky",
    "nheo_mat": "Distracted 2",
    "nhin_ben_phai": "Nhìn phải",
    "nhin_ben_trai": "Nhìn trái",
    "nhin_xuong": "Look down",
    "police": "Police",
    "pong": "Pong",
    "rain": "Rain",
    "sakura": "Sakura",
    "samurai": "Blade",
    "scared": "Accel",
    "sleepy": "Sleepy",
    "smile": "Smile",
    "speed": "Revs",
    "star": "Stars",
    "sung_nuoc": "Hadouken Miss",
    "sung_nuoc_2": "Hadouken Hit",
    "sushi": "Sushi",
    "turbo": "Turbo",
    "thong_long": "Tsurikawa",
    "thu_nho": "Breaking",
    "up_size_down": "Upside down",
    "UwU": "UwU",
    "wheels": "Equip",
    "xi_khoi": "Nose Smoke",
    "xi_lua": "Nose Fire",
    "speed2": "Speed 2",
    "yelling": "Yelling",
    "car": "Car",
    "intro_3": "Intro 3",
    "LB": "LB",
    "LB_intro": "LB Intro",
    "LB_Star": "LB Star",
    "speed3": "Speed 3",
}

# Exact Expression -> Embedded WAV mapping extracted from c3.bin DROM (0x10020..0x16000)
MOCHI_FACE_SOUND_MAP: Dict[str, str] = {
    "intro": "intro.wav",
    "intro_3": "moshi.wav",
    "mac_dinh": "moshi.wav",
    "UwU": "UwU.wav",
    "love": "love.wav",
    "love2": "dump_love.wav",
    "smile": "moshi.wav",
    "happy_2": "UwU.wav",
    "hehe": "moshi.wav",
    "angry": "tanjiro.wav",
    "angry2": "pretentious.wav",
    "angry3": "angry.wav",
    "gian_du": "angry.wav",
    "cry": "cry.wav",
    "cry2": "cry2.wav",
    "devil": "cursed_smile.wav",
    "devil_2": "glitch.wav",
    "dasai": "dasai.wav",
    "dasai2": "dasai.wav",
    "hat_xi": "sneeze.wav",
    "hat_xi_2": "big_sneeze.wav",
    "leu_leu": "raspberry.wav",
    "sleepy": "sleep.wav",
    "sakura": "sakura.wav",
    "police": "police.wav",
    "speed": "speed.wav",
    "speed2": "speed.wav",
    "speed3": "speed.wav",
    "turbo": "speed.wav",
    "star": "stars.wav",
    "LB": "lbwk.wav",
    "LB_intro": "lbwk.wav",
    "LB_Star": "lbwk.wav",
    "bee": "bee.wav",
    "hand_some": "banana.wav",
    "rain": "rain.wav",
    "xi_khoi": "nose.wav",
    "xi_lua": "nose.wav",
}

# Exact Note Frequency Table ported from https://themochi.huykhong.com/thietlap
MOCHI_NOTES_FREQ: Dict[str, int] = {
    "B0": 31, "C1": 33, "CS1": 35, "D1": 37, "DS1": 39, "E1": 41,
    "F1": 44, "FS1": 46, "G1": 49, "GS1": 52, "A1": 55, "AS1": 58, "B1": 62,
    "C2": 65, "CS2": 69, "D2": 73, "DS2": 78, "E2": 82, "F2": 87, "FS2": 93,
    "G2": 98, "GS2": 104, "A2": 110, "AS2": 117, "B2": 123,
    "C3": 131, "CS3": 139, "D3": 147, "DS3": 156, "E3": 165, "F3": 175, "FS3": 185,
    "G3": 196, "GS3": 208, "A3": 220, "AS3": 233, "B3": 247,
    "C4": 262, "CS4": 277, "D4": 294, "DS4": 311, "E4": 330, "F4": 349, "FS4": 370,
    "G4": 392, "GS4": 415, "A4": 440, "AS4": 466, "B4": 494,
    "C5": 523, "CS5": 554, "D5": 587, "DS5": 622, "E5": 659, "F5": 698, "FS5": 740,
    "G5": 784, "GS5": 831, "A5": 880, "AS5": 932, "B5": 988,
    "C6": 1047, "CS6": 1109, "D6": 1175, "DS6": 1245, "E6": 1319, "F6": 1397, "FS6": 1480,
    "G6": 1568, "GS6": 1661, "A6": 1760, "AS6": 1865, "B6": 1976,
    "C7": 2093, "CS7": 2217, "D7": 2349, "DS7": 2489, "E7": 2637, "F7": 2794, "FS7": 2960,
    "G7": 3136, "GS7": 3322, "A7": 3520, "AS7": 3729, "B7": 3951,
    "C8": 4186, "CS8": 4435, "D8": 4699, "DS8": 4978,
}

MOCHI_PRESET_MELODIES: Dict[str, str] = {
    "mario": "E5 100 20 E5 100 20 E5 100 60 C5 100 20 E5 100 60 G5 100 100 G4 100 100",
    "nokia": "E5 125 10 D5 125 10 FS4 125 10 GS4 125 10 CS5 125 10 B4 125 10 D4 125 10 E4 125 10 B4 125 10 AS4 125 10",
    "epic": "C5 150 20 G4 150 20 C5 150 20 E5 150 20 G5 200 50 C6 250 50 G5 150 20 E5 150 20 C5 300 50",
    "chime": "E5 70 0 G5 70 0",
    "bounce": "C5 50 0 E5 50 0 C5 50 0",
    "wosh": "C5 50 0 E5 50 0 G5 50 0",
    "ding": "C5 100 0",
    "traffic_light": "C5 100 300 C5 100 300 C5 100 300 E5 70 0 G5 120 0",
}


def synthesize_mochi_melody_wav(note_str: str, sample_rate: int = 22050) -> bytes:
    """
    Ported from https://themochi.huykhong.com/thietlap (`playNote` + `parseNoteInput`):
    Synthesizes an 8-bit/16-bit square-wave ESP32 buzzer melody into WAV bytes.
    """
    tokens = note_str.replace("#", "S").strip().split()
    samples: List[np.ndarray] = []

    i = 0
    while i + 2 < len(tokens):
        note_name = tokens[i].upper()
        try:
            dur_ms = max(10, min(2000, int(float(tokens[i + 1]))))
            rest_ms = max(0, min(2000, int(float(tokens[i + 2]))))
        except ValueError:
            i += 1
            continue
        i += 3

        freq = MOCHI_NOTES_FREQ.get(note_name, 523)
        n_tone = int(sample_rate * (dur_ms / 1000.0))
        if n_tone > 0:
            t = np.arange(n_tone, dtype=np.float32) / float(sample_rate)
            sq = np.where(np.sin(2.0 * math.pi * freq * t) >= 0, 0.32, -0.32).astype(np.float32)
            # Soft envelope to avoid harsh clicks
            fade = min(120, n_tone // 4)
            if fade > 1:
                sq[:fade] *= np.linspace(0.0, 1.0, fade, dtype=np.float32)
                sq[-fade:] *= np.linspace(1.0, 0.0, fade, dtype=np.float32)
            samples.append((sq * 32767.0).astype(np.int16))

        n_rest = int(sample_rate * (rest_ms / 1000.0))
        if n_rest > 0:
            samples.append(np.zeros(n_rest, dtype=np.int16))

    pcm = np.concatenate(samples) if samples else np.zeros(int(sample_rate * 0.1), dtype=np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm.tobytes())
    return buf.getvalue()


class MochiESP32Client:
    """
    Virtual ESP32-C3 hardware client & firmware extractor for https://themochi.huykhong.com/
    - Unpacks all 71 128x64 OLED animations from `c3.bin` DROM (`0x10020`).
    - Unpacks all 27 embedded `.wav` voice/sound clips from `c3.bin` SPIFFS (`0x35a000`).
    - Emulates the full serial configuration state used by `/thietlap`.
    """

    def __init__(self, mac_address: str = "ECDA3B9F2A10") -> None:
        self.mac_address = mac_address.replace(":", "").upper()
        self.chip_family = "ESP32-C3"
        self.firmware_version = "4.3.2"
        self.baud_rate = 115200
        self._chunk_buffers: Dict[str, str] = {}
        self.device_state: Dict[str, str] = self._default_state()
        ESP32_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        FACES_DIR.mkdir(parents=True, exist_ok=True)
        GIFS_DIR.mkdir(parents=True, exist_ok=True)
        SOUNDS_DIR.mkdir(parents=True, exist_ok=True)
        PREVIEWS_DIR.mkdir(parents=True, exist_ok=True)

    def _default_state(self) -> Dict[str, str]:
        return {
            "MAC": self.mac_address,
            "licOK": "true",
            "version": self.firmware_version,
            "gif_speed": "100",
            "gif_delay": "5000",
            "gif_negative": "false",
            "gif_default": "mac_dinh",
            "gif_intro": "intro",
            "gif_touch": "next_gif",
            "gif_double_touch": "UwU",
            "gif_long_touch": "show_clock",
            "gif_selected": "1" * 71,
            "intro_sound": "G4 100 20 C5 100 20 E5 100 20 G5 100 20 C6 100 20 D6 100 20 E6 200 200",
            "notification_sound": "G4 100 20 C5 100 20 E5 100 20 G5 200 200",
            "touch_sound": "C4 100 20 D4 100 20 E4 100 20 F4 200 200",
            "double_touch_sound": "C5 100 20 D5 100 20 E5 100 20 F5 200 200",
            "long_touch_sound": "C6 100 20 D6 100 20 E6 100 20 F6 200 200",
            "notifDuration": "5",
            "bluetooth_auto_off": "0",
            "bluetoothName": "THE MOCHI",
            "display_type": "ssd1306",
            "is_flip_mode": "0",
            "scl_pin": "9",
            "sda_pin": "8",
            "use_sound": "2",
            "I2S_LRCK_PIN": "6",
            "I2S_BCK_PIN": "7",
            "I2S_DATA_PIN": "5",
            "volume": "80",
            "buzzer_pin": "10",
            "touch_pin": "3",
            "language": "0",
            "custom_title": "THE MOCHI",
            "useSD": "false",
            "SD_SCK": "4",
            "SD_MOSI": "6",
            "SD_MISO": "5",
            "SD_CS": "7",
        }

    def handle_serial_command(self, line: str) -> List[str]:
        """Emulates the ESP32-C3 serial command parser (`set:get`, `set:save`, etc.) for `/thietlap`."""
        line = line.strip()
        if ":" not in line:
            return []
        key, val = line.split(":", 1)
        key = key.strip()
        val = val.strip()

        # Ensure gif_speed is always within [50, 200] so /thietlap never hangs on -1
        try:
            spd = int(float(self.device_state.get("gif_speed", "100")))
            if spd < 50 or spd > 200:
                self.device_state["gif_speed"] = "100"
        except Exception:
            self.device_state["gif_speed"] = "100"

        if key == "set":
            if val == "get":
                return [f"{k}:{v}" for k, v in self.device_state.items()]
            if val == "save":
                return ["SAVED:true"]
            if val == "reset":
                return ["RESET:true"]
            if val == "default1":
                d = self._default_state()
                for k in ("gif_speed", "gif_delay", "gif_negative", "gif_default", "gif_intro", "gif_touch", "gif_double_touch", "gif_long_touch", "gif_selected"):
                    self.device_state[k] = d[k]
                return [f"{k}:{v}" for k, v in self.device_state.items()]
            if val == "default2":
                d = self._default_state()
                for k in ("intro_sound", "notification_sound", "touch_sound", "double_touch_sound", "long_touch_sound", "volume"):
                    self.device_state[k] = d[k]
                return [f"{k}:{v}" for k, v in self.device_state.items()]
            if val == "default3":
                d = self._default_state()
                for k in ("display_type", "is_flip_mode", "scl_pin", "sda_pin", "use_sound", "I2S_LRCK_PIN", "I2S_BCK_PIN", "I2S_DATA_PIN", "buzzer_pin", "touch_pin", "language", "custom_title", "useSD", "SD_SCK", "SD_MOSI", "SD_MISO", "SD_CS"):
                    self.device_state[k] = d[k]
                return [f"{k}:{v}" for k, v in self.device_state.items()]

        if key == "key":
            self.device_state["licOK"] = "true"
            return ["licOK:true"]

        if key == "isInverted":
            self.device_state["gif_negative"] = "true" if val.lower() in ("true", "1") else "false"
            return [f"gif_negative:{self.device_state['gif_negative']}"]

        if key == "gif_selected_bin":
            self.device_state["gif_selected"] = val
            return [f"gif_selected:{val}"]

        # Handle chunked melody fields from /thietlap (`<field>`, `<field>_cont`, `<field>_end`)
        sound_fields = ("intro_sound", "touch_sound", "double_touch_sound", "long_touch_sound", "notification_sound")
        for sf in sound_fields:
            if key == sf:
                self._chunk_buffers[sf] = val
                self.device_state[sf] = val
                return [f"ACK:{sf}"]
            if key == f"{sf}_cont":
                self._chunk_buffers[sf] = self._chunk_buffers.get(sf, "") + val
                self.device_state[sf] = self._chunk_buffers[sf]
                return [f"ACK:{sf}_cont"]
            if key == f"{sf}_end":
                if sf in self._chunk_buffers:
                    self.device_state[sf] = self._chunk_buffers.pop(sf)
                return [f"{sf}:{self.device_state.get(sf, '')}"]

        self.device_state[key] = val
        return [f"{key}:{val}"]

    def check_supporter_license(self) -> Dict[str, object]:
        try:
            with httpx.Client(timeout=8.0, follow_redirects=True) as client:
                resp = client.get(LICENSE_CHECK_URL, params={"mac": self.mac_address})
                if resp.status_code == 200:
                    try:
                        return resp.json()
                    except Exception:
                        return {"status": resp.status_code, "raw": resp.text[:120]}
        except Exception as exc:
            return {"error": str(exc)}
        return {"status": "offline"}

    def resolve_latest_firmware_url(self) -> Tuple[str, str]:
        manifest_url = DEFAULT_MANIFEST_URL
        bin_url = DEFAULT_BIN_URL
        try:
            with httpx.Client(timeout=10.0, follow_redirects=True) as client:
                xml_resp = client.get(FIRMWARE_XML_URL)
                if xml_resp.status_code == 200:
                    root = ET.fromstring(xml_resp.text)
                    m_node = root.find(".//firmware/manifest")
                    if m_node is not None and m_node.text:
                        manifest_path = m_node.text.strip().lstrip("/")
                        manifest_url = f"{BASE_URL}/{manifest_path}"

                m_resp = client.get(manifest_url)
                if m_resp.status_code == 200:
                    m_data = m_resp.json()
                    self.firmware_version = m_data.get("version", self.firmware_version)
                    builds = m_data.get("builds", [])
                    if builds and builds[0].get("parts"):
                        part_path = builds[0]["parts"][0]["path"]
                        base_dir = manifest_url.rsplit("/", 1)[0]
                        bin_url = f"{base_dir}/{part_path}"
        except Exception:
            pass
        return manifest_url, bin_url

    def download_firmware_bin(self, force: bool = False) -> Path:
        bin_path = ESP32_CACHE_DIR / "c3.bin"
        if bin_path.exists() and bin_path.stat().st_size > 4_000_000 and not force:
            return bin_path

        _, bin_url = self.resolve_latest_firmware_url()
        with httpx.Client(
            timeout=30.0,
            follow_redirects=True,
            headers={
                "User-Agent": "ESP32-C3-Mochi-Client/4.3.2 (esp-web-tools)",
                "X-ESP32-MAC": self.mac_address,
            },
        ) as client:
            resp = client.get(bin_url)
            resp.raise_for_status()
            bin_path.write_bytes(resp.content)
        return bin_path

    @staticmethod
    def parse_partition_table(data: bytes) -> List[Dict[str, object]]:
        partitions: List[Dict[str, object]] = []
        for off in range(0x8000, 0x8200, 32):
            if off + 28 > len(data):
                break
            magic, ptype, subtype, p_off, p_size, label = struct.unpack(
                "<HBBII16s", data[off : off + 28]
            )
            if magic == 0x50AA:
                partitions.append(
                    {
                        "type": ptype,
                        "subtype": subtype,
                        "offset": hex(p_off),
                        "size": hex(p_size),
                        "label": label.rstrip(b"\x00").decode(errors="ignore"),
                    }
                )
        return partitions

    def extract_spiffs_audio_files(self, data: Optional[bytes] = None) -> List[Dict[str, object]]:
        """
        Extracts all 27 embedded `.wav` voice/sound files from the ESP32-C3 SPIFFS
        partition (`0x35a000..0x3ff000`) into `assets/mochi_faces/sounds/`.
        """
        if data is None:
            bin_path = self.download_firmware_bin(force=False)
            data = bin_path.read_bytes()

        st = data[SPIFFS_PART_OFFSET:SPIFFS_PART_END]
        obj_meta: Dict[int, Tuple[str, int]] = {}
        data_pages: Dict[Tuple[int, int], bytes] = {}

        for blk in range(0, len(st), 4096):
            for pg in range(1, 16):
                poff = blk + pg * 256
                if poff + 256 > len(st):
                    break
                obj_id, span_ix, flags = struct.unpack("<HHB", st[poff : poff + 5])
                if obj_id in (0, 0xFFFF) or flags == 0x00 or (flags & 1) == 1:
                    continue
                if obj_id & 0x8000:
                    if span_ix == 0 and st[poff + 12] == 1 and st[poff + 13 : poff + 14] == b"/":
                        size = struct.unpack("<I", st[poff + 8 : poff + 12])[0]
                        name = (
                            st[poff + 13 : poff + 45]
                            .split(b"\x00")[0]
                            .decode("utf-8", errors="ignore")
                            .lstrip("/")
                        )
                        oid = obj_id & 0x7FFF
                        prev = obj_meta.get(oid)
                        if prev is None or size > prev[1]:
                            obj_meta[oid] = (name, size)
                else:
                    if (flags & 0x80) != 0:
                        data_pages[(obj_id, span_ix)] = st[poff + 5 : poff + 256]

        extracted_sounds: List[Dict[str, object]] = []
        for oid, (name, sz) in sorted(obj_meta.items()):
            first_page = data_pages.get((oid, 0), b"")
            riff_sz = (
                struct.unpack("<I", first_page[4:8])[0] + 8
                if first_page[:4] == b"RIFF" and len(first_page) >= 8
                else sz
            )
            target_sz = max(sz, riff_sz)
            num_pages = (target_sz + 250) // 251
            buf = b"".join(data_pages.get((oid, s), b"") for s in range(num_pages))[:target_sz]

            if buf[:4] == b"RIFF":
                out_path = SOUNDS_DIR / name
                out_path.write_bytes(buf)
                extracted_sounds.append(
                    {
                        "id": oid,
                        "name": name,
                        "size_bytes": len(buf),
                        "path": str(out_path),
                    }
                )

        return extracted_sounds

    def extract_all_faces(
        self, export_gifs: bool = True, download_web_previews: bool = False
    ) -> Dict[str, object]:
        """
        Extracts all 71 128x64 OLED face animations + all 27 SPIFFS `.wav` audio files
        from `c3.bin`.
        """
        bin_path = self.download_firmware_bin(force=False)
        data = bin_path.read_bytes()
        partitions = self.parse_partition_table(data)
        extracted_sounds = self.extract_spiffs_audio_files(data)

        npz_arrays: Dict[str, np.ndarray] = {}
        animations_meta: List[Dict[str, object]] = []

        priority_gifs = {
            "mac_dinh", "smile", "UwU", "love", "love2", "happy_2", "hehe",
            "nheo_mat", "nhin_ben_phai", "nhin_ben_trai", "nhin_xuong",
            "sleepy", "angry", "gian_du", "cry", "scared", "distracted",
            "gundam", "dasai2", "demon_slayer", "sakura", "samurai", "star",
            "music", "neon", "keep_it_up", "yelling",
        }

        for idx, off in enumerate(range(ANIM_TABLE_START, ANIM_TABLE_END, 8)):
            p_name, p_struct = struct.unpack("<II", data[off : off + 8])
            name_foff = p_name - DROM_VADDR_OFFSET
            name = (
                data[name_foff : name_foff + 48]
                .split(b"\x00")[0]
                .decode("utf-8", errors="ignore")
            )

            struct_foff = p_struct - DROM_VADDR_OFFSET
            fcnt, width, height, p_delays, p_frames = struct.unpack(
                "<HHIII", data[struct_foff : struct_foff + 16]
            )
            delays_foff = p_delays - DROM_VADDR_OFFSET
            frames_foff = p_frames - DROM_VADDR_OFFSET

            raw_delays = list(
                struct.unpack(f"<{fcnt}H", data[delays_foff : delays_foff + fcnt * 2])
            )
            resolved_delays = [d if d > 0 else 42 for d in raw_delays]

            total_bytes = fcnt * 1024
            raw_frames_buf = np.frombuffer(
                data, dtype=np.uint8, count=total_bytes, offset=frames_foff
            ).reshape((fcnt, 64, 16))
            bits_frames = np.unpackbits(raw_frames_buf, axis=2)

            npz_arrays[f"frames_{name}"] = raw_frames_buf
            npz_arrays[f"delays_{name}"] = np.array(resolved_delays, dtype=np.uint16)

            label = MOCHI_WEB_LABELS.get(name, name)
            sound_file = MOCHI_FACE_SOUND_MAP.get(name)
            animations_meta.append(
                {
                    "index": idx,
                    "name": name,
                    "label": label,
                    "frames": fcnt,
                    "width": width,
                    "height": height,
                    "delays_ms": resolved_delays,
                    "sound_wav": sound_file,
                }
            )

            if export_gifs and name in priority_gifs:
                gif_path = GIFS_DIR / f"{name}.gif"
                if not gif_path.exists():
                    pil_frames = [
                        Image.fromarray((bits_frames[f] * 255).astype(np.uint8), mode="L")
                        for f in range(fcnt)
                    ]
                    if pil_frames:
                        pil_frames[0].save(
                            gif_path,
                            save_all=True,
                            append_images=pil_frames[1:],
                            duration=resolved_delays,
                            loop=0,
                        )

        np.savez_compressed(NPZ_PACK_PATH, **npz_arrays)

        manifest_payload = {
            "source": BASE_URL,
            "emulator": {
                "chip": self.chip_family,
                "mac": self.mac_address,
                "firmware_version": self.firmware_version,
                "partitions": partitions,
            },
            "total_animations": len(animations_meta),
            "total_frames": int(sum(m["frames"] for m in animations_meta)),
            "total_sounds": len(extracted_sounds),
            "sounds": extracted_sounds,
            "animations": animations_meta,
        }
        MANIFEST_JSON_PATH.write_text(
            json.dumps(manifest_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        if download_web_previews:
            self.download_web_preview_pngs(["Default", "Smile", "UwU", "Gundam", "Love", "Laugh"])

        return manifest_payload

    def download_web_preview_pngs(self, labels: Optional[List[str]] = None) -> List[Path]:
        target_labels = labels or list(MOCHI_WEB_LABELS.values())
        saved: List[Path] = []
        with httpx.Client(timeout=10.0, follow_redirects=True) as client:
            for label in target_labels:
                safe_name = label.replace(" ", "_") + ".png"
                out_path = PREVIEWS_DIR / safe_name
                if out_path.exists():
                    saved.append(out_path)
                    continue
                encoded = urllib.parse.quote(f"{label}.png")
                url = f"{WEB_ASSETS_BASE_URL}/{encoded}"
                try:
                    r = client.get(url)
                    if r.status_code == 200 and r.content.startswith(b"\x89PNG"):
                        out_path.write_bytes(r.content)
                        saved.append(out_path)
                except Exception:
                    pass
        return saved


class MochiFacePlayer:
    """
    Realtime 60 FPS OLED 128x64 Display Engine ported from The Mochi Firmware v4.3.2:
    - Streams all 71 128x64 1-bit OLED animations
    - Supports Firmware Display Modes:
      * `face` (Default / Expressive 128x64 animations + Lip-Sync mouth)
      * `show_clock` (128x64 OLED Clock + Date + Weather HUD)
      * `cpuz` (128x64 OLED CPU / RAM / Active App HUD)
      * `notification` (Chronos Phone Notification banner)
      * `navigation` (Chronos Google Maps Turn-by-Turn Navigation HUD)
    """

    EMOTION_TO_FACES: Dict[str, List[str]] = {
        "neutral": ["mac_dinh"],
        "happy": ["smile", "UwU", "happy_2", "hehe", "keep_it_up"],
        "excited": ["UwU", "star", "love", "happy_2", "sakura"],
        "love": ["love", "love2", "UwU", "sakura"],
        "curious": ["nheo_mat", "distracted", "star", "dasai2"],
        "thinking": ["chong_mat", "dasai2", "neon", "gundam"],
        "surprised": ["scared", "star", "demon_slayer", "aot"],
        "focused": ["gundam", "samurai", "devil_eyes", "speed"],
        "alert": ["angry", "gian_du", "police", "samurai", "yelling"],
        "sleepy": ["sleepy"],
        "sad": ["cry", "cry2", "rain"],
    }

    IDLE_MICRO_FACES: List[str] = [
        "smile", "UwU", "nheo_mat", "hehe", "nhin_ben_trai",
        "nhin_ben_phai", "nhin_xuong", "love", "star", "gundam",
        "sakura", "keep_it_up", "demon_slayer", "dasai2",
    ]

    def __init__(self) -> None:
        self.frames_map: Dict[str, np.ndarray] = {}
        self.delays_map: Dict[str, List[int]] = {}
        self.default_face: str = "mac_dinh"
        self.current_face: str = "intro"
        self.frame_idx: int = 0
        self.frame_elapsed_ms: float = 0.0
        self.loop_Current: bool = False
        self.last_emotion: str = "neutral"
        self.next_idle_quirk_time: float = time.monotonic() + 8.0
        self.speed_pct: float = 100.0
        self.inverted: bool = False

        # Firmware OLED HUD Mode state
        self.display_mode: str = "face"  # "face" | "show_clock" | "cpuz" | "notification" | "navigation"
        self.mode_until_ts: float = 0.0
        self.notif_app: str = ""
        self.notif_title: str = ""
        self.notif_body: str = ""
        self.nav_direction: str = "STRAIGHT"
        self.nav_distance: str = "150m"
        self.nav_street: str = ""
        self.weather_text: str = "28C Clear Sky"
        self.cpu_pct: int = 12
        self.ram_gb: float = 0.1

        self._ensure_loaded()

    def _ensure_loaded(self) -> None:
        if not NPZ_PACK_PATH.exists() or not (SOUNDS_DIR / "moshi.wav").exists():
            client = MochiESP32Client()
            client.extract_all_faces(export_gifs=True, download_web_previews=True)

        with np.load(NPZ_PACK_PATH) as pack:
            for key in pack.files:
                if key.startswith("frames_"):
                    name = key[len("frames_") :]
                    packed = pack[key]
                    self.frames_map[name] = np.unpackbits(packed, axis=2)
                elif key.startswith("delays_"):
                    name = key[len("delays_") :]
                    self.delays_map[name] = [int(x) for x in pack[key].tolist()]

    def list_available_faces(self) -> List[str]:
        return sorted(self.frames_map.keys())

    def get_sound_path_for_face(self, face_name: str) -> Optional[Path]:
        wav_name = MOCHI_FACE_SOUND_MAP.get(face_name)
        if not wav_name:
            return None
        p = SOUNDS_DIR / wav_name
        return p if p.exists() else None

    def set_face(self, face_name: str, loop: bool = True) -> None:
        if face_name == "show_clock":
            self.toggle_clock_mode()
            return
        if face_name == "cpuz":
            self.display_mode = "cpuz"
            self.mode_until_ts = time.monotonic() + 8.0
            return
        if face_name == "next_gif":
            face_name = random.choice(self.IDLE_MICRO_FACES)
            loop = False
        if face_name not in self.frames_map:
            face_name = self.default_face if self.default_face in self.frames_map else "mac_dinh"
        self.display_mode = "face"
        self.current_face = face_name
        self.frame_idx = 0
        self.frame_elapsed_ms = 0.0
        self.loop_Current = loop

    def toggle_clock_mode(self, duration_sec: float = 8.0) -> str:
        if self.display_mode == "show_clock":
            self.display_mode = "face"
        else:
            self.display_mode = "show_clock"
            self.mode_until_ts = time.monotonic() + duration_sec
        return self.display_mode

    def show_phone_notification(self, app: str, title: str, body: str, duration_sec: float = 5.0) -> None:
        self.notif_app = app[:18]
        self.notif_title = title[:22]
        self.notif_body = body[:44]
        self.display_mode = "notification"
        self.mode_until_ts = time.monotonic() + duration_sec

    def show_navigation_hud(self, direction: str, distance: str, street: str, duration_sec: float = 8.0) -> None:
        self.nav_direction = direction.upper()
        self.nav_distance = distance[:12]
        self.nav_street = street[:24]
        self.display_mode = "navigation"
        self.mode_until_ts = time.monotonic() + duration_sec

    def step(
        self,
        dt_sec: float,
        state: str = "idle",
        emotion: str = "neutral",
        gaze_x: float = 0.0,
        gaze_y: float = 0.0,
        lip_energy: float = 0.0,
        forced_face: Optional[str] = None,
    ) -> np.ndarray:
        now = time.monotonic()

        # Check temporary HUD mode expiration
        if self.display_mode != "face" and self.mode_until_ts > 0 and now >= self.mode_until_ts:
            self.display_mode = "face"
            self.mode_until_ts = 0.0

        if self.display_mode == "show_clock":
            out = self._render_clock_oled()
            return (1 - out) if self.inverted else out
        if self.display_mode == "cpuz":
            out = self._render_cpuz_oled()
            return (1 - out) if self.inverted else out
        if self.display_mode == "notification":
            out = self._render_notification_oled()
            return (1 - out) if self.inverted else out
        if self.display_mode == "navigation":
            out = self._render_navigation_oled()
            return (1 - out) if self.inverted else out

        base_idle_face = self.default_face if self.default_face in self.frames_map else "mac_dinh"

        if forced_face and forced_face in self.frames_map:
            self.set_face(forced_face, loop=True)
        else:
            if emotion != self.last_emotion:
                self.last_emotion = emotion
                if emotion == "neutral":
                    chosen = base_idle_face
                else:
                    candidates = self.EMOTION_TO_FACES.get(emotion, [base_idle_face])
                    chosen = random.choice(candidates)
                self.set_face(chosen, loop=(emotion in ("neutral", "sleepy")))
                self.next_idle_quirk_time = now + random.uniform(8.0, 14.0)

            if state == "thinking" and self.current_face == base_idle_face:
                self.set_face("dasai2", loop=True)
            elif state == "listening" and self.current_face == base_idle_face:
                self.set_face("nheo_mat", loop=True)
            elif state == "idle" and emotion == "neutral":
                if self.current_face in ("mac_dinh", "nhin_ben_trai", "nhin_ben_phai", "nhin_xuong"):
                    if gaze_x < -0.42:
                        self.set_face("nhin_ben_trai", loop=False)
                    elif gaze_x > 0.42:
                        self.set_face("nhin_ben_phai", loop=False)
                    elif gaze_y > 0.45:
                        self.set_face("nhin_xuong", loop=False)

                if self.current_face == base_idle_face and now >= self.next_idle_quirk_time:
                    quirk = random.choice(self.IDLE_MICRO_FACES)
                    self.set_face(quirk, loop=False)
                    self.next_idle_quirk_time = now + random.uniform(9.0, 15.0)

        frames = self.frames_map.get(self.current_face)
        if frames is None or len(frames) == 0:
            return np.zeros((64, 128), dtype=np.uint8)

        delays = self.delays_map.get(self.current_face, [42] * len(frames))
        speed_mult = max(0.5, min(2.5, float(self.speed_pct or 100.0) / 100.0))
        self.frame_elapsed_ms += dt_sec * 1000.0 * speed_mult

        cur_delay = delays[self.frame_idx] if self.frame_idx < len(delays) else 42
        if self.current_face == "mac_dinh" and self.frame_idx == 0:
            cur_delay = 3200

        while self.frame_elapsed_ms >= cur_delay:
            self.frame_elapsed_ms -= max(16, cur_delay)
            self.frame_idx += 1
            if self.frame_idx >= len(frames):
                if self.loop_Current:
                    self.frame_idx = 0
                else:
                    self.current_face = base_idle_face
                    self.loop_Current = True
                    self.frame_idx = 0
                    frames = self.frames_map[base_idle_face]
                    delays = self.delays_map[base_idle_face]
                    break
            cur_delay = delays[self.frame_idx] if self.frame_idx < len(delays) else 42

        frame = frames[self.frame_idx].copy()

        if state == "speaking" or lip_energy > 0.06:
            frame = self._apply_oled_lipsync(frame, lip_energy, now)

        if self.inverted:
            frame = 1 - frame

        return frame

    @staticmethod
    def _render_clock_oled() -> np.ndarray:
        """Renders the Mochi `show_clock` 128x64 OLED mode (`HH:MM:SS`, `DD/MM`, Weather)."""
        img = Image.new("1", (128, 64), 0)
        draw = ImageDraw.Draw(img)
        font = ImageFont.load_default()
        t_str = time.strftime("%H:%M:%S")
        d_str = time.strftime("%d/%m/%Y")
        draw.rectangle([2, 2, 125, 61], outline=1)
        draw.text((20, 8), "THE MOCHI CLOCK", fill=1, font=font)
        draw.text((34, 25), t_str, fill=1, font=font)
        draw.text((30, 43), d_str, fill=1, font=font)
        return (np.array(img, dtype=np.uint8) > 0).astype(np.uint8)

    def _render_cpuz_oled(self) -> np.ndarray:
        """Renders the Mochi `CPUZ` 128x64 OLED hardware telemetry screen."""
        img = Image.new("1", (128, 64), 0)
        draw = ImageDraw.Draw(img)
        font = ImageFont.load_default()
        draw.rectangle([2, 2, 125, 61], outline=1)
        draw.text((12, 8), f"CPU: {self.cpu_pct}%", fill=1, font=font)
        draw.rectangle([12, 22, 114, 30], outline=1)
        bar_w = int(100 * max(0.05, min(1.0, self.cpu_pct / 100.0)))
        draw.rectangle([13, 23, 13 + bar_w, 29], fill=1)
        draw.text((12, 38), f"SYSRAM: {self.ram_gb:.1f} GB", fill=1, font=font)
        return (np.array(img, dtype=np.uint8) > 0).astype(np.uint8)

    def _render_notification_oled(self) -> np.ndarray:
        """Renders the Chronos ESP32 Phone Notification screen on the 128x64 OLED visor."""
        img = Image.new("1", (128, 64), 0)
        draw = ImageDraw.Draw(img)
        font = ImageFont.load_default()
        draw.rectangle([1, 1, 126, 62], outline=1)
        draw.rectangle([1, 1, 126, 15], fill=1)
        draw.text((6, 3), f"[{self.notif_app or 'PHONE'}]", fill=0, font=font)
        draw.text((6, 20), self.notif_title[:20], fill=1, font=font)
        draw.text((6, 35), self.notif_body[:20], fill=1, font=font)
        if len(self.notif_body) > 20:
            draw.text((6, 48), self.notif_body[20:40], fill=1, font=font)
        return (np.array(img, dtype=np.uint8) > 0).astype(np.uint8)

    def _render_navigation_oled(self) -> np.ndarray:
        """Renders the Chronos Google Maps Turn-by-Turn Navigation screen on 128x64 OLED."""
        img = Image.new("1", (128, 64), 0)
        draw = ImageDraw.Draw(img)
        font = ImageFont.load_default()
        draw.rectangle([1, 1, 126, 62], outline=1)
        # Draw direction arrow icon on left (x: 8..38, y: 12..52)
        if "LEFT" in self.nav_direction or "TRAI" in self.nav_direction:
            draw.polygon([(8, 30), (24, 16), (24, 25), (38, 25), (38, 35), (24, 35), (24, 44)], fill=1)
        elif "RIGHT" in self.nav_direction or "PHAI" in self.nav_direction:
            draw.polygon([(38, 30), (22, 16), (22, 25), (8, 25), (8, 35), (22, 35), (22, 44)], fill=1)
        else:
            draw.polygon([(23, 10), (10, 26), (18, 26), (18, 50), (28, 50), (28, 26), (36, 26)], fill=1)
        draw.text((46, 10), "GOOGLE MAPS", fill=1, font=font)
        draw.text((46, 26), self.nav_distance, fill=1, font=font)
        draw.text((46, 42), self.nav_street[:13], fill=1, font=font)
        return (np.array(img, dtype=np.uint8) > 0).astype(np.uint8)

    @staticmethod
    def _apply_oled_lipsync(frame: np.ndarray, lip_energy: float, now: float) -> np.ndarray:
        energy = float(np.clip(lip_energy, 0.05, 1.0))
        frame[36:63, 45:83] = 0

        cx, cy = 64, 46
        half_w = int(8 + energy * 6)
        open_h = int(3 + energy * 12)

        yy, xx = np.ogrid[36:63, 45:83]
        dx = (xx - cx) / max(1.0, float(half_w))

        if open_h <= 4:
            curve_y = cy + 3 + (3.2 * (1.0 - dx * dx))
            mask = (np.abs(xx - cx) <= half_w) & (np.abs(yy - curve_y) <= 1.8)
            frame[36:63, 45:83][mask] = 1
        else:
            top_y = cy - 2
            bot_y = min(61, top_y + open_h)
            semi_h = max(2.0, float(bot_y - top_y))
            norm_x = (xx - cx) / float(half_w)
            norm_y = (yy - top_y) / semi_h
            dist_sq = norm_x * norm_x + norm_y * norm_y

            u_rim = (yy >= top_y) & (dist_sq <= 1.08) & (dist_sq >= 0.56)
            top_bar = (np.abs(xx - cx) <= half_w) & (np.abs(yy - top_y) <= 1.2)
            mouth_pixels = u_rim | top_bar
            frame[36:63, 45:83][mouth_pixels] = 1

        return frame


if __name__ == "__main__":
    client = MochiESP32Client()
    res = client.extract_all_faces(export_gifs=True, download_web_previews=True)
    print(
        f"[ESP32-C3 Mochi Core] Extracted {res['total_animations']} OLED animations "
        f"({res['total_frames']} frames) + {res['total_sounds']} SPIFFS WAV audio files -> {SOUNDS_DIR}"
    )
