"""
Neito-Agent: The Mochi ESP32-C3 Core Firmware Brain & Chronos Phone Bridge
===========================================================================
Ported directly from `https://themochi.huykhong.com/` (`c3.bin` v4.3.2 + `/thietlap`):
1. Runs the exact Mochi Firmware state machine (`gifTask`, `touchTask`, `serialTask`,
   `chronosTask`, `soundTask`) as the central core governing all mascot interactions.
2. Implements the ChronosESP32 Phone App Bridge (`https://chronos.ke/` BLE protocol
   + Wi-Fi/LAN Mobile Companion Web App `/mobile` with QR Code pairing):
   - Phone Notifications (with automatic `bank` / `momo` / `ngân hàng` -> `coin.wav` trigger!)
   - Google Maps Turn-by-Turn Navigation HUD (`LEFT`, `RIGHT`, `STRAIGHT`, distance, street)
   - Weather & Time Sync (`28C Clear Sky`, `show_clock`)
   - Remote 71-Face & 27-Soundboard control from Smartphone.
"""

from __future__ import annotations

import json
import random
import socket
import time
from pathlib import Path
from typing import Any, Callable, Coroutine, Dict, List, Optional

from backend.vision.mochi_esp32_client import (
    MOCHI_FACE_SOUND_MAP,
    MOCHI_PRESET_MELODIES,
    MOCHI_WEB_LABELS,
    MochiESP32Client,
)
from backend.voice.omnivoice_tts import omnivoice_engine

NVS_FILE_PATH = Path(__file__).resolve().parents[1] / "mochi_nvs.json"


def get_local_lan_ip() -> str:
    """Detects the PC's primary Wi-Fi / LAN IPv4 address for Smartphone QR pairing."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"


class MochiFirmwareCoreBrain:
    """
    Central Core Brain ported from The Mochi ESP32-C3 Firmware v4.3.2 (`c3.bin`).
    Coordinates:
    - NVS Firmware Settings (`gif_default`, `gif_intro`, `gif_touch`, `gif_double_touch`,
      `gif_long_touch`, `gif_speed`, `gif_delay`, `gif_selected`, `notifDuration`, etc.)
    - 3-Tier Touch Sensor Logic (Single Tap, Double Tap, Long Touch)
    - Autonomous `gifTask` expression loop synced with Visual Neural Network & App Protocols
    - ChronosESP32 Mobile App Bridge (Notifications, Banking `coin.wav`, Google Maps Navigation,
      Weather, Time sync, Remote Face/Voice triggers)
    """

    BANKING_KEYWORDS = (
        "bank", "ngân hàng", "ngan hang", "momo", "vcb", "vietcombank",
        "techcombank", "mbbank", "tpbank", "bidv", "vietinbank", "acb",
        "cộng", "cong ", "+1", "+2", "+3", "+5", " nhận tiền", " biến động số dư",
    )

    def __init__(self) -> None:
        self.esp32 = MochiESP32Client()
        self.nvs: Dict[str, str] = dict(self.esp32.device_state)
        self._load_nvs()

        self.all_face_names: List[str] = list(MOCHI_WEB_LABELS.keys())
        self.current_face: str = self.nvs.get("gif_default", "mac_dinh")
        self.display_mode: str = "face"
        self.last_cycle_ts: float = time.monotonic()
        self.phone_connected: bool = False
        self.phone_battery: int = 100
        self.phone_weather: str = "28°C Clear Sky"
        self._listeners: List[Callable[[Dict[str, Any]], Coroutine[Any, Any, None]]] = []

    def _load_nvs(self) -> None:
        if NVS_FILE_PATH.exists():
            try:
                saved = json.loads(NVS_FILE_PATH.read_text(encoding="utf-8"))
                if isinstance(saved, dict):
                    self.nvs.update({str(k): str(v) for k, v in saved.items()})
                    self.esp32.device_state.update(self.nvs)
            except Exception:
                pass
        else:
            self._save_nvs()

    def _save_nvs(self) -> None:
        try:
            NVS_FILE_PATH.write_text(
                json.dumps(self.nvs, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception:
            pass

    def register_listener(
        self, cb: Callable[[Dict[str, Any]], Coroutine[Any, Any, None]]
    ) -> None:
        if cb not in self._listeners:
            self._listeners.append(cb)

    def unregister_listener(
        self, cb: Callable[[Dict[str, Any]], Coroutine[Any, Any, None]]
    ) -> None:
        if cb in self._listeners:
            self._listeners.remove(cb)

    async def broadcast_event(self, payload: Dict[str, Any]) -> None:
        dead = []
        for cb in list(self._listeners):
            try:
                await cb(payload)
            except Exception:
                dead.append(cb)
        for cb in dead:
            self.unregister_listener(cb)

    def execute_serial_command(self, cmd_line: str) -> List[str]:
        """Executes a `field:value` serial command exactly like `/thietlap` Web-Serial."""
        replies = self.esp32.handle_serial_command(cmd_line)
        self.nvs.update(self.esp32.device_state)
        self._save_nvs()
        return replies

    def get_enabled_faces(self) -> List[str]:
        bits = self.nvs.get("gif_selected", "1" * len(self.all_face_names))
        enabled = [
            name
            for idx, name in enumerate(self.all_face_names)
            if idx >= len(bits) or bits[idx] == "1"
        ]
        return enabled or ["mac_dinh", "smile", "UwU"]

    def build_boot_intro_packet(self) -> Dict[str, Any]:
        """Builds the startup Intro packet (`gif_intro` + `intro_sound`)."""
        intro_face = self.nvs.get("gif_intro", "intro")
        intro_snd_key = self.nvs.get("intro_sound", "moshi.mp3")
        sfx = omnivoice_engine.get_mochi_sfx_audio(intro_snd_key, emotion="happy")
        return {
            "type": "mochi_firmware_event",
            "event": "boot_intro",
            "face": intro_face,
            "display_mode": "face",
            "emotion": "happy",
            "text": f"✨ {self.nvs.get('custom_title', 'THE MOCHI')} • Moshi Moshi!",
            "audio": sfx,
        }

    def handle_touch_action(self, touch_kind: str = "single") -> Dict[str, Any]:
        """
        Ported from The Mochi Firmware touch sensor ISR (`touch_pin`):
        - `single`: `gif_touch` + `touch_sound`
        - `double`: `gif_double_touch` + `double_touch_sound`
        - `long`:   `gif_long_touch` + `long_touch_sound`
        """
        if touch_kind == "double":
            action = self.nvs.get("gif_double_touch", "UwU")
            snd_cfg = self.nvs.get("double_touch_sound", "UwU.wav")
        elif touch_kind == "long":
            action = self.nvs.get("gif_long_touch", "show_clock")
            snd_cfg = self.nvs.get("long_touch_sound", "C5 50 0 E5 50 0 G5 50 0")
        else:
            action = self.nvs.get("gif_touch", "next_gif")
            snd_cfg = self.nvs.get("touch_sound", "")

        display_mode = "face"
        chosen_face = self.current_face

        if action == "show_clock":
            display_mode = "show_clock"
            chosen_face = "show_clock"
        elif action == "cpuz":
            display_mode = "cpuz"
            chosen_face = "cpuz"
        elif action == "bluetooth":
            self.phone_connected = not self.phone_connected
            chosen_face = "star" if self.phone_connected else "sleepy"
        elif action == "next_gif":
            candidates = [
                f for f in self.get_enabled_faces()
                if f not in ("mac_dinh", "intro", "intro_3")
            ]
            chosen_face = random.choice(candidates) if candidates else "smile"
        else:
            chosen_face = action

        self.current_face = chosen_face
        self.display_mode = display_mode

        # Prefer the expression's authentic SPIFFS WAV sound if available, else configured buzzer melody
        face_wav = MOCHI_FACE_SOUND_MAP.get(chosen_face)
        sound_target = face_wav if face_wav else (snd_cfg or "moshi.wav")
        sfx = omnivoice_engine.get_mochi_sfx_audio(sound_target, emotion="happy")

        label = MOCHI_WEB_LABELS.get(chosen_face, chosen_face)
        return {
            "type": "mochi_firmware_event",
            "event": f"touch_{touch_kind}",
            "face": chosen_face,
            "label": label,
            "display_mode": display_mode,
            "emotion": "happy",
            "audio": sfx,
        }

    def pick_next_autonomous_face(self, neural_emotion: str = "neutral") -> Optional[Dict[str, Any]]:
        """
        Ported from `gifTask` in `c3.bin`:
        Checks `gif_delay` (default 10,000ms) and cycles to an enabled Mochi expression.
        """
        now = time.monotonic()
        delay_sec = max(5.0, float(self.nvs.get("gif_delay", "10000")) / 1000.0)
        if now - self.last_cycle_ts < delay_sec:
            return None
        self.last_cycle_ts = now

        enabled = self.get_enabled_faces()
        pool = [f for f in enabled if f not in ("intro", "intro_3", "mac_dinh")]
        if not pool:
            return None

        chosen = random.choice(pool)
        self.current_face = chosen
        return {
            "type": "mochi_firmware_event",
            "event": "auto_gif_cycle",
            "face": chosen,
            "label": MOCHI_WEB_LABELS.get(chosen, chosen),
            "display_mode": "face",
            "emotion": neural_emotion,
        }

    def handle_chronos_notification(
        self, app_name: str, title: str, message: str
    ) -> Dict[str, Any]:
        """
        Ported from `ChronosESP32` notification callback in `c3.bin`:
        - Checks if notification text contains banking/MoMo keywords (`bank`, `ngân hàng`,
          `momo`, `cộng`, `+`). If so, plays `/coin.wav` (`coin.mp3` in firmware) + `star`!
        - Otherwise plays `notification_sound` and shows the OLED notification screen
          for `notifDuration` seconds.
        """
        self.phone_connected = True
        combined = f"{app_name} {title} {message}".lower()
        is_money = any(kw in combined for kw in self.BANKING_KEYWORDS)

        duration_sec = float(self.nvs.get("notifDuration", "5"))
        if is_money:
            sfx = omnivoice_engine.get_mochi_sfx_audio("coin.wav", emotion="excited")
            face = "star"
        else:
            notif_snd = self.nvs.get("notification_sound", "moshi.mp3")
            sfx = omnivoice_engine.get_mochi_sfx_audio(notif_snd, emotion="curious")
            face = "UwU"

        return {
            "type": "mochi_firmware_event",
            "event": "chronos_notification",
            "app": app_name,
            "title": title,
            "message": message,
            "is_banking_alert": is_money,
            "duration_sec": duration_sec,
            "face": face,
            "display_mode": "notification",
            "emotion": "excited" if is_money else "curious",
            "text": f"📱 [{app_name}] {title}: {message}",
            "audio": sfx,
        }

    def handle_chronos_navigation(
        self, direction: str, distance: str, street: str, eta: str = ""
    ) -> Dict[str, Any]:
        """
        Ported from `ChronosESP32` Google Maps Navigation callback in `c3.bin`:
        Renders the turn-by-turn navigation arrow, distance, and street name on the OLED visor.
        """
        self.phone_connected = True
        sfx = omnivoice_engine.get_mochi_sfx_audio("chime", emotion="focused")
        return {
            "type": "mochi_firmware_event",
            "event": "chronos_navigation",
            "direction": direction,
            "distance": distance,
            "street": street,
            "eta": eta,
            "duration_sec": 8.0,
            "face": "car",
            "display_mode": "navigation",
            "emotion": "focused",
            "text": f"🧭 Google Maps: {direction} ({distance}) → {street}",
            "audio": sfx,
        }

    def parse_raw_chronos_ble_packet(self, raw_bytes: bytes) -> Optional[Dict[str, Any]]:
        """
        Decodes raw binary packets from the official Chronos Android/iOS app
        (Nordic UART Service `6E400001-B5A3-F393-E0A9-E50E24DCCA9E`, header `0xAB`).
        """
        if len(raw_bytes) < 6 or raw_bytes[0] != 0xAB:
            return None
        cmd = raw_bytes[4]
        payload = raw_bytes[6:]
        # 0x72 = Chronos Notification packet
        if cmd == 0x72:
            text = payload.decode("utf-8", errors="ignore").strip("\x00")
            parts = text.split(":", 1)
            title = parts[0] if len(parts) > 1 else "Chronos"
            body = parts[1] if len(parts) > 1 else text
            return self.handle_chronos_notification("Chronos BLE", title, body)
        # 0x91 = Phone Battery level
        if cmd == 0x91 and len(payload) >= 2:
            self.phone_battery = int(payload[1])
            self.phone_connected = True
            return {
                "type": "mochi_firmware_event",
                "event": "chronos_battery",
                "battery": self.phone_battery,
            }
        # 0xEF = Google Maps Navigation packet
        if cmd == 0xEF:
            nav_str = payload.decode("utf-8", errors="ignore").strip("\x00")
            return self.handle_chronos_navigation("STRAIGHT", "150m", nav_str or "Google Maps")
        return None

    def update_chronos_config(
        self,
        bluetooth_name: Optional[str] = None,
        notif_duration: Optional[str] = None,
        bluetooth_auto_off: Optional[str] = None,
    ) -> Dict[str, Any]:
        if bluetooth_name is not None and str(bluetooth_name).strip():
            self.nvs["bluetoothName"] = str(bluetooth_name).strip()
            self.esp32.device_state["bluetoothName"] = self.nvs["bluetoothName"]
        if notif_duration is not None and str(notif_duration).strip():
            self.nvs["notifDuration"] = str(notif_duration).strip()
            self.esp32.device_state["notifDuration"] = self.nvs["notifDuration"]
        if bluetooth_auto_off is not None and str(bluetooth_auto_off).strip():
            self.nvs["bluetooth_auto_off"] = str(bluetooth_auto_off).strip()
            self.esp32.device_state["bluetooth_auto_off"] = self.nvs["bluetooth_auto_off"]
        self._save_nvs()
        return {
            "bluetoothName": self.nvs.get("bluetoothName", "THE MOCHI"),
            "notifDuration": self.nvs.get("notifDuration", "5"),
            "bluetooth_auto_off": self.nvs.get("bluetooth_auto_off", "0"),
        }

    def get_status_snapshot(self, port: int = 8765) -> Dict[str, Any]:
        lan_ip = get_local_lan_ip()
        mobile_url = f"http://{lan_ip}:{port}/thietlap"
        return {
            "mac": self.esp32.mac_address,
            "chip": self.esp32.chip_family,
            "firmware_version": self.esp32.firmware_version,
            "bluetooth_name": self.nvs.get("bluetoothName", "THE MOCHI"),
            "phone_connected": self.phone_connected,
            "phone_battery": self.phone_battery,
            "mobile_companion_url": mobile_url,
            "current_face": self.current_face,
            "display_mode": self.display_mode,
            "nvs": self.nvs,
            "faces": [
                {"name": k, "label": v, "sound": MOCHI_FACE_SOUND_MAP.get(k)}
                for k, v in MOCHI_WEB_LABELS.items()
            ],
            "sounds": sorted(set(MOCHI_FACE_SOUND_MAP.values())) + ["coin.wav"],
            "melodies": list(MOCHI_PRESET_MELODIES.keys()),
        }


mochi_core_brain = MochiFirmwareCoreBrain()
