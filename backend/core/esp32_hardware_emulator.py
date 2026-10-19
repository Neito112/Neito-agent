import asyncio
import datetime
import io
import json
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Coroutine, Dict, List, Optional

import base64
import httpx
import websockets

from backend.core.config import BASE_DIR, config_manager
from backend.core.mochi_core_brain import mochi_core_brain
from backend.core.protocol_engine import protocol_engine
from backend.core.window_watcher import window_watcher
from backend.vision.eye_engine import eye_engine
from backend.voice.xiaozhi_opus import OpusStreamDecoder, text_to_mic_opus_frames

ESP32_STATE_PATH = BASE_DIR / "esp32_hardware_state.json"


class ESP32S3UltimateEmulator:
    """
    ESP32-S3 Ultimate Hardware Emulator (`ESP32-S3-N16R8-CAM-BOX3`)
    ==============================================================
    Emulates the highest-spec multi-purpose ESP32-S3 AI board with full peripheral set:
      - SoC: ESP32-S3-WROOM-1-N16R8 (Dual-Core XTensa LX7 @ 240MHz + Vector AI PIE, 16MB Octal Flash, 8MB Octal PSRAM)
      - Camera Peripheral (`OV2640-ScreenCam`): Hardware frame buffer routed to PC Desktop/Active Window capture
      - Vision NPU Co-Processor (`ESP-DL YOLO11n + YOLO-World`): Built-in hardware MCP server for real-time screen
        detection, HUD scanning, open-vocabulary self-training, and Reflex Protocol Cartridges
      - Audio Peripheral (`ES8311 + MAX98357A`): Full-duplex 16kHz/24kHz I2S Codec + Dual Mic Array + Hardware AEC/VAD
      - Display Peripheral (`SSD1306 128x64 OLED + ST7789 240x240 IPS`): 71 Mochi OLED faces, Clock, CPU-Z, Nav HUD
      - Connectivity: Wi-Fi 802.11n + BLE 5.0 GATT (`Chronos` 6e400001-...) + Web-Serial COM9 + `xiaozhi.me` Cloud Bridge

    Supports both:
      1. Live `xiaozhi.me/console/agents` Cloud Console connection (`https://api.tenclass.net/xiaozhi/ota/` &
         `wss://api.tenclass.net/xiaozhi/v1/`) with 6-digit device binding code and full JSON-RPC 2.0 MCP protocol.
      2. Direct LLM API Key mode (`gemini`, `openai`, `deepseek`, `groq`, `ollama`, `lmstudio`, `mochi_core`) using the
         exact same built-in Hardware & YOLO MCP tools.
    """

    def __init__(self) -> None:
        self.state = self._load_or_create_state()
        self.mac_address: str = self.state["mac_address"]
        self.client_id: str = self.state["client_id"]
        self.board_name: str = "esp32-s3-n16r8-cam-box3"
        self.firmware_version: str = "2.0.0"

        # Xiaozhi Cloud Console (`https://xiaozhi.me/console/agents`) state
        self.ota_url: str = self.state.get("ota_url", "https://api.tenclass.net/xiaozhi/ota/")
        self.ws_url: str = self.state.get("ws_url", "wss://api.tenclass.net/xiaozhi/v1/")
        self.ws_token: str = self.state.get("ws_token", "test-token")
        self.activation_code: str = self.state.get("activation_code", "")
        self.activation_message: str = self.state.get("activation_message", "")
        self.vision_explain_url: str = "http://api.xiaozhi.me/vision/explain"
        self.vision_explain_token: str = ""
        self.cloud_connected: bool = False
        self.cloud_session_id: str = ""
        self.last_ota_check: float = 0.0
        self.mcp_call_log: List[Dict[str, Any]] = []

        # Hardware YOLO Co-processor state
        self.yolo_hardware_mode: str = self.state.get("yolo_hardware_mode", "eco_1fps")
        self._hw_yolo_task: Optional[asyncio.Task] = None
        self._event_listeners: List[Callable[[Dict[str, Any]], Coroutine[Any, Any, None]]] = []

    def _load_or_create_state(self) -> Dict[str, Any]:
        if ESP32_STATE_PATH.exists():
            try:
                data = json.loads(ESP32_STATE_PATH.read_text(encoding="utf-8"))
                if data.get("mac_address") and data.get("client_id"):
                    return data
            except Exception:
                pass
        # Generate a deterministic Espressif OUI MAC (`ec:da:3b:xx:xx:xx`) + UUIDv4 Client-Id
        node = uuid.getnode()
        b3 = (node >> 16) & 0xFF
        b4 = (node >> 8) & 0xFF
        b5 = node & 0xFF
        mac = f"ec:da:3b:{b3:02x}:{b4:02x}:{b5:02x}"
        state = {
            "mac_address": mac,
            "client_id": str(uuid.uuid4()),
            "ota_url": "https://api.tenclass.net/xiaozhi/ota/",
            "ws_url": "wss://api.tenclass.net/xiaozhi/v1/",
            "ws_token": "test-token",
            "activation_code": "",
            "activation_message": "",
            "yolo_hardware_mode": "eco_1fps",
        }
        try:
            ESP32_STATE_PATH.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass
        return state

    def save_state(self) -> None:
        self.state.update(
            {
                "mac_address": self.mac_address,
                "client_id": self.client_id,
                "ota_url": self.ota_url,
                "ws_url": self.ws_url,
                "ws_token": self.ws_token,
                "activation_code": self.activation_code,
                "activation_message": self.activation_message,
                "yolo_hardware_mode": self.yolo_hardware_mode,
            }
        )
        try:
            ESP32_STATE_PATH.write_text(json.dumps(self.state, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass

    def register_listener(self, cb: Callable[[Dict[str, Any]], Coroutine[Any, Any, None]]) -> None:
        if cb not in self._event_listeners:
            self._event_listeners.append(cb)

    def unregister_listener(self, cb: Callable[[Dict[str, Any]], Coroutine[Any, Any, None]]) -> None:
        if cb in self._event_listeners:
            self._event_listeners.remove(cb)

    async def broadcast_hardware_event(self, packet: Dict[str, Any]) -> None:
        for cb in list(self._event_listeners):
            try:
                await cb(packet)
            except Exception:
                pass

    # =========================================================================
    # 1. FULL ESP32-S3 HARDWARE MANIFEST & OTA DESCRIPTOR
    # =========================================================================
    def get_hardware_manifest(self) -> Dict[str, Any]:
        telem = window_watcher.get_resource_telemetry()
        win = window_watcher.get_active_window()
        proto = protocol_engine.get_active_protocol()
        hw = config_manager.config.esp32_hardware
        flash_num = 16
        try:
            flash_num = int("".join(filter(str.isdigit, hw.flash_size)) or "16")
        except Exception:
            pass
        psram_num = 8
        try:
            psram_num = int("".join(filter(str.isdigit, hw.psram_size)) or "8")
        except Exception:
            pass

        return {
            "board_model": f"{hw.chip_model} (Flash {hw.flash_size} • PSRAM {hw.psram_size})",
            "chip_model_name": hw.chip_model.lower().replace("-", ""),
            "cpu": "Dual-Core XTensa LX7 @ 240MHz + Vector AI PIE Extensions" if "S3" in hw.chip_model else "Single-Core 32-bit RISC-V @ 160MHz",
            "flash_size_mb": flash_num,
            "psram_size_mb": psram_num,
            "mac_address": hw.mac_address or self.mac_address,
            "client_id": self.client_id,
            "esp32_hardware": hw.model_dump(),
            "firmware": {
                "xiaozhi_version": self.firmware_version,
                "mochi_version": "4.3.2",
                "elf_sha256": "c8a4e91f20d73b856a12f9b03e4d7c8a9102f3e4d5c6b7a890123456789abcde",
            },
            "peripherals": {
                "camera": {
                    "sensor": "OV2640 / SC031GS Virtual Screen-Capture Camera",
                    "source": "PC Desktop / Active Foreground Window (MSS Zero-Copy)",
                    "resolution": "960x540 RGB888 / JPEG",
                    "status": "READY",
                },
                "npu_coprocessor": {
                    "engine": "Built-in Hardware YOLO11n + YOLO-World Open-Vocab MCP",
                    "mode": self.yolo_hardware_mode,
                    "detector_weights": config_manager.config.vision.detector_model,
                    "trainer_weights": config_manager.config.vision.trainer_model,
                    "active_protocol": proto.get("name", "Global"),
                    "yolo_classes": proto.get("yolo_classes", []),
                    "last_latency_ms": eye_engine.last_scan_result.get("latency_ms", 0.0),
                },
                "display": {
                    "primary": "SSD1306 128x64 OLED (71 Mochi Expressions)",
                    "secondary": "ST7789 240x240 IPS RGB HUD",
                    "current_face": mochi_core_brain.current_face,
                    "inverted": mochi_core_brain.nvs.get("inverted", "0") == "1",
                },
                "audio_codec": {
                    "codec": "ES8311 DAC + Dual MEMS Mic Array (Hardware AEC + VAD)",
                    "sample_rate_hz": 16000,
                    "volume": int(mochi_core_brain.nvs.get("volume", "85")),
                },
                "connectivity": {
                    "wifi_ssid": "Neito-Virtual-LAN-5G",
                    "wifi_rssi": -38,
                    "ble_gatt": "THE MOCHI (6e400001-b5a3-f393-e0a9-e50e24dcca9e)",
                    "serial_bridge": "COM9 (115200 8N1)",
                    "xiaozhi_console_url": "https://xiaozhi.me/console/agents",
                    "xiaozhi_ota_url": self.ota_url,
                    "xiaozhi_ws_url": self.ws_url,
                    "activation_code": self.activation_code,
                    "activation_message": self.activation_message,
                    "cloud_bound": not bool(self.activation_code),
                },
            },
            "active_window": win.to_dict(),
            "telemetry": telem,
            "mcp_tools_count": len(self.get_mcp_tools_list()),
            "recent_mcp_calls": self.mcp_call_log[-8:],
        }

    def update_hardware_config(self, patch: Dict[str, Any]) -> Dict[str, Any]:
        updated = config_manager.update_partial({"esp32_hardware": patch})
        hw = updated.esp32_hardware
        if hw.mac_address:
            self.mac_address = hw.mac_address
            self.state["mac_address"] = hw.mac_address
            self._save_state()
        return hw.model_dump()

    def build_xiaozhi_ota_payload(self) -> Dict[str, Any]:
        """Builds the exact JSON body expected by `https://api.tenclass.net/xiaozhi/ota/`."""
        return {
            "version": 2,
            "language": "vi-VN",
            "flash_size": 16777216,
            "minimum_free_heap_size": 8126464,
            "mac_address": self.mac_address,
            "uuid": self.client_id,
            "chip_model_name": "esp32s3",
            "chip_info": {
                "model": 9,
                "cores": 2,
                "revision": 2,
                "features": 18,
            },
            "application": {
                "name": "xiaozhi",
                "version": self.firmware_version,
                "compile_time": "Oct 19 2026 10:00:00",
                "idf_version": "v5.3.2-dirty",
                "elf_sha256": "c8a4e91f20d73b856a12f9b03e4d7c8a9102f3e4d5c6b7a89012f3e4d5c6b7a8",
            },
            "partition_table": [
                {"label": "nvs", "type": 1, "subtype": 2, "address": 36864, "size": 24576},
                {"label": "otadata", "type": 1, "subtype": 0, "address": 61440, "size": 8192},
                {"label": "phy_init", "type": 1, "subtype": 1, "address": 69632, "size": 4096},
                {"label": "model", "type": 1, "subtype": 130, "address": 73728, "size": 983040},
                {"label": "ota_0", "type": 0, "subtype": 16, "address": 1114112, "size": 6291456},
            ],
            "ota": {"label": "ota_0"},
            "board": {
                "type": self.board_name,
                "name": "ESP32-S3-N16R8-CAM-BOX3",
                "ssid": "Neito-Virtual-LAN-5G",
                "rssi": -38,
                "channel": 6,
                "ip": "192.168.1.168",
                "mac": self.mac_address,
            },
        }

    # =========================================================================
    # 2. BUILT-IN HARDWARE & SCREEN-YOLO MCP SERVER (JSON-RPC 2.0 + OpenAI Tools)
    # =========================================================================
    def get_mcp_tools_list(self) -> List[Dict[str, Any]]:
        """
        Returns the complete MCP Tool definitions exposed by the ESP32-S3 Hardware Emulator.
        Compatible with `xiaozhi.me/console/agents` JSON-RPC 2.0 `tools/list`.
        """
        return [
            {
                "name": "self.camera.take_photo",
                "description": (
                    "Chụp ảnh màn hình máy tính đang mở thông qua Camera ảo phần cứng ESP32-S3 (OV2640-ScreenCam), "
                    "đồng thời chạy chip NPU YOLO11n nhận diện vật thể/HUD và phân tích hình ảnh trên màn hình. "
                    "Sử dụng khi người dùng hỏi trên màn hình đang có gì, nhìn màn hình, xem game/ứng dụng đang mở."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "question": {
                            "type": "string",
                            "description": "Câu hỏi hoặc yêu cầu cần quan sát trên màn hình máy tính.",
                        }
                    },
                    "required": ["question"],
                },
            },
            {
                "name": "self.yolo.scan_screen",
                "description": (
                    "Kích hoạt chip phần cứng NPU YOLO11n tích hợp trong ESP32-S3 để quét nhanh các vật thể, "
                    "thanh máu, bản đồ nhỏ (minimap), đối thủ hoặc giao diện trên màn hình máy tính."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "target_classes": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Danh sách các vật thể/HUD cần quét (tùy chọn).",
                        }
                    },
                },
            },
            {
                "name": "self.yolo.set_mode",
                "description": (
                    "Chuyển đổi chế độ hoạt động của phần cứng YOLO11n tích hợp trong mạch ESP32-S3: "
                    "'off' (tắt), 'eco_1fps' (tiết kiệm 1 FPS), 'balanced_4fps' (cân bằng 4 FPS), "
                    "'combat_10fps' (chiến đấu 10 FPS tốc độ cao), hoặc 'auto_reflex' (tự động phản xạ)."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "mode": {
                            "type": "string",
                            "enum": ["off", "eco_1fps", "balanced_4fps", "combat_10fps", "auto_reflex"],
                            "description": "Chế độ phần cứng YOLO cần kích hoạt.",
                        }
                    },
                    "required": ["mode"],
                },
            },
            {
                "name": "self.yolo.train_open_vocab",
                "description": (
                    "Sử dụng phần cứng YOLO-World tích hợp để tự động học và gán nhãn các vật thể/giao diện (HUD) mới "
                    "trên màn hình máy tính, lưu vào bộ giao thức (Protocol Cartridge) hiện tại."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "classes": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Danh sách tên các vật thể/HUD cần học nhận diện.",
                        }
                    },
                    "required": ["classes"],
                },
            },
            {
                "name": "self.protocol.create_or_update",
                "description": (
                    "Tạo mới hoặc cập nhật một bộ Giao Thức (Protocol Cartridge) cho game, phần mềm hoặc chủ đề "
                    "đang mở trên màn hình và lưu vào thẻ nhớ SD ảo của ESP32-S3."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "topic_or_app": {
                            "type": "string",
                            "description": "Tên game, phần mềm hoặc chủ đề cần tạo giao thức.",
                        },
                        "process_name": {
                            "type": "string",
                            "description": "Tên tiến trình .exe nếu có (tùy chọn).",
                        },
                    },
                    "required": ["topic_or_app"],
                },
            },
            {
                "name": "self.protocol.get_status",
                "description": "Đọc thông tin giao thức (Protocol Cartridge) đang nạp và cửa sổ đang mở trên màn hình.",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                },
            },
            {
                "name": "self.screen.set_expression",
                "description": (
                    "Điều khiển màn hình OLED SSD1306/ST7789 của ESP32-S3 đổi sang 1 trong 71 biểu cảm khuôn mặt Mochi "
                    "(smile, UwU, happy_2, hehe, laugh, love, star, cool, wink, angry, cry, sleepy, gundam, show_clock, cpuz)."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "face": {
                            "type": "string",
                            "description": "Tên biểu cảm OLED cần hiển thị.",
                        }
                    },
                    "required": ["face"],
                },
            },
            {
                "name": "self.audio.set_volume",
                "description": "Điều chỉnh âm lượng chip giải mã âm thanh I2S ES8311 của ESP32-S3 (0 - 100).",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "volume": {
                            "type": "integer",
                            "minimum": 0,
                            "maximum": 100,
                            "description": "Mức âm lượng từ 0 đến 100.",
                        }
                    },
                    "required": ["volume"],
                },
            },
            {
                "name": "self.system.get_hardware_status",
                "description": (
                    "Đọc thông số phần cứng của mạch giả lập ESP32-S3-N16R8-CAM-BOX3 (CPU, PSRAM, Camera màn hình, "
                    "chế độ NPU YOLO, kết nối Chronos BLE và trạng thái xiaozhi.me)."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                },
            },
        ]

    def get_openai_function_tools(self) -> List[Dict[str, Any]]:
        """
        Converts the ESP32-S3 Hardware MCP tools into OpenAI Function Calling format
        so Direct LLM API Key mode (`gemini`, `openai`, `deepseek`, `groq`, `ollama`, `mochi_core`)
        can invoke the exact same hardware MCP tools!
        """
        openai_tools: List[Dict[str, Any]] = []
        for t in self.get_mcp_tools_list():
            safe_fn_name = t["name"].replace(".", "_")
            openai_tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": safe_fn_name,
                        "description": t["description"],
                        "parameters": t["inputSchema"],
                    },
                }
            )
        return openai_tools

    async def set_yolo_hardware_mode(self, mode: str) -> Dict[str, Any]:
        valid_modes = {"off", "eco_1fps", "balanced_4fps", "combat_10fps", "auto_reflex"}
        clean_mode = mode.strip().lower()
        if clean_mode not in valid_modes:
            clean_mode = "eco_1fps"
        self.yolo_hardware_mode = clean_mode
        self.save_state()

        if clean_mode == "off":
            config_manager.update_partial({"vision": {"enabled": False}})
        elif clean_mode == "eco_1fps":
            config_manager.update_partial({"vision": {"enabled": True, "fps_mode": "eco", "auto_reflex_on_detection": False}})
        elif clean_mode == "balanced_4fps":
            config_manager.update_partial({"vision": {"enabled": True, "fps_mode": "balanced", "auto_reflex_on_detection": False}})
        elif clean_mode == "combat_10fps":
            config_manager.update_partial({"vision": {"enabled": True, "fps_mode": "combat", "auto_reflex_on_detection": False}})
        elif clean_mode == "auto_reflex":
            config_manager.update_partial({"vision": {"enabled": True, "fps_mode": "balanced", "auto_reflex_on_detection": True}})

        pkt = {
            "type": "esp32_hardware_event",
            "event": "yolo_mode_changed",
            "yolo_mode": self.yolo_hardware_mode,
        }
        await self.broadcast_hardware_event(pkt)
        return {
            "status": "ok",
            "yolo_hardware_mode": self.yolo_hardware_mode,
            "vision_enabled": config_manager.config.vision.enabled,
            "fps_mode": config_manager.config.vision.fps_mode,
        }

    async def execute_mcp_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """
        Executes a built-in ESP32-S3 Hardware MCP tool (invoked either by `xiaozhi.me/console/agents`
        via JSON-RPC 2.0 `tools/call` OR by Direct LLM API Key mode).
        """
        t0 = time.perf_counter()
        # Normalize both `self.camera.take_photo` and `self_camera_take_photo`
        norm_name = tool_name.replace("_", ".")
        active_proto = protocol_engine.get_active_protocol()
        result_payload: Dict[str, Any] = {}

        if norm_name in ("self.camera.take.photo", "self.camera.take_photo") or tool_name in (
            "self.camera.take_photo",
            "self_camera_take_photo",
            "scan_screen_vision",
        ):
            question = arguments.get("question") or "Quan sát màn hình máy tính hiện tại"
            cap = eye_engine.capture_screen(active_window_only=False, max_dim=960)
            scan = eye_engine.scan_screen_yolo11n(active_proto.get("yolo_classes"))

            # If connected to Xiaozhi Cloud Vision endpoint (`http://api.xiaozhi.me/vision/explain`),
            # also upload the screen JPEG exactly like `esp32_camera.cc` in `78/xiaozhi-esp32`!
            cloud_vision_explanation = ""
            if self.vision_explain_url and self.vision_explain_token:
                try:
                    buf = io.BytesIO()
                    cap["image"].save(buf, format="JPEG", quality=80)
                    jpeg_bytes = buf.getvalue()
                    headers = {
                        "Authorization": f"Bearer {self.vision_explain_token}",
                        "Device-Id": self.mac_address,
                        "Client-Id": self.client_id,
                    }
                    files = {
                        "question": (None, question),
                        "file": ("screen_camera.jpg", jpeg_bytes, "image/jpeg"),
                    }
                    async with httpx.AsyncClient(timeout=8.0) as client:
                        v_resp = await client.post(self.vision_explain_url, headers=headers, files=files)
                        if v_resp.status_code == 200:
                            cloud_vision_explanation = v_resp.text.strip()
                except Exception:
                    cloud_vision_explanation = ""

            result_payload = {
                "camera_sensor": "OV2640-ScreenCam (PC Desktop Screen Capture)",
                "active_window": scan.get("window", {}),
                "yolo11n_hardware_detections": scan.get("detections", []),
                "screen_brightness": scan.get("brightness", 0),
                "active_protocol": active_proto.get("name", "Global"),
                "xiaozhi_vision_analysis": cloud_vision_explanation or scan.get("screen_summary", ""),
                "latency_ms": scan.get("latency_ms", 0),
            }

        elif tool_name in ("self.yolo.scan_screen", "self_yolo_scan_screen"):
            target_cls = arguments.get("target_classes") or active_proto.get("yolo_classes")
            scan = eye_engine.scan_screen_yolo11n(target_cls)
            result_payload = {
                "hardware_coprocessor": "ESP-DL YOLO11n",
                "mode": self.yolo_hardware_mode,
                "active_window": scan.get("window", {}),
                "detections": scan.get("detections", []),
                "brightness": scan.get("brightness", 0),
                "latency_ms": scan.get("latency_ms", 0),
            }

        elif tool_name in ("self.yolo.set_mode", "self_yolo_set_mode"):
            mode = arguments.get("mode", "eco_1fps")
            result_payload = await self.set_yolo_hardware_mode(mode)

        elif tool_name in ("self.yolo.train_open_vocab", "self_yolo_train_open_vocab", "train_vision_detector"):
            raw_classes = arguments.get("classes") or []
            if isinstance(raw_classes, str):
                raw_classes = [c.strip() for c in raw_classes.split(",") if c.strip()]
            yw_res = eye_engine.auto_train_yolo_world(active_proto["id"], raw_classes)
            active_proto["yolo_classes"] = list(
                dict.fromkeys(active_proto.get("yolo_classes", []) + yw_res.get("classes", []))
            )
            protocol_engine.save_protocol(active_proto)
            result_payload = {
                "status": "trained",
                "protocol_id": active_proto["id"],
                "learned_classes": yw_res.get("classes", []),
                "labeled_frames": yw_res.get("labeled_frames", 0),
            }

        elif tool_name in (
            "self.protocol.create_or_update",
            "self_protocol_create_or_update",
            "create_or_update_protocol",
        ):
            from backend.brain.llm_router import brain_router

            topic = arguments.get("topic_or_app") or "Custom Protocol"
            proc_name = arguments.get("process_name") or ""
            res = await brain_router.synthesize_protocol_with_llm_and_tools(topic, process_name=proc_name)
            result_payload = {
                "status": "created",
                "protocol": res["protocol"],
            }

        elif tool_name in ("self.protocol.get_status", "self_protocol_get_status", "get_protocol_knowledge"):
            win = window_watcher.get_active_window()
            result_payload = {
                "active_window": win.to_dict(),
                "active_protocol": active_proto,
                "available_protocols": [
                    {"id": p["id"], "name": p["name"], "category": p.get("category", "")}
                    for p in protocol_engine.list_protocols()
                ],
            }

        elif tool_name in ("self.screen.set_expression", "self_screen_set_expression", "set_mochi_expression"):
            face = arguments.get("face", "smile")
            mochi_core_brain.current_face = face
            mochi_core_brain.display_mode = face if face in ("show_clock", "cpuz") else "face"
            pkt = {
                "type": "mochi_firmware_event",
                "event": "set_face",
                "face": face,
                "display_mode": mochi_core_brain.display_mode,
                "emotion": "happy",
            }
            await mochi_core_brain.broadcast_event(pkt)
            result_payload = {"status": "ok", "face": face, "display_mode": mochi_core_brain.display_mode}

        elif tool_name in ("self.audio.set_volume", "self_audio_set_volume"):
            vol = max(0, min(100, int(arguments.get("volume", 85))))
            mochi_core_brain.nvs["volume"] = str(vol)
            mochi_core_brain.save_nvs()
            result_payload = {"status": "ok", "volume": vol}

        elif tool_name in ("self.system.get_hardware_status", "self_system_get_hardware_status"):
            result_payload = self.get_hardware_manifest()

        else:
            result_payload = {"error": f"Unknown hardware MCP tool: {tool_name}"}

        elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)
        self.mcp_call_log.append(
            {
                "timestamp": datetime.datetime.now().strftime("%H:%M:%S"),
                "tool": tool_name,
                "elapsed_ms": elapsed_ms,
            }
        )
        if len(self.mcp_call_log) > 25:
            self.mcp_call_log = self.mcp_call_log[-25:]

        return result_payload

    async def handle_jsonrpc_mcp_message(self, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Handles incoming JSON-RPC 2.0 MCP messages from `wss://api.tenclass.net/xiaozhi/v1/`
        (`initialize`, `notifications/initialized`, `tools/list`, `tools/call`).
        """
        method = payload.get("method", "")
        msg_id = payload.get("id")
        params = payload.get("params") or {}

        if method == "initialize":
            caps = params.get("capabilities") or {}
            vision_cfg = caps.get("vision") or {}
            if vision_cfg.get("url"):
                self.vision_explain_url = vision_cfg["url"]
            if vision_cfg.get("token"):
                self.vision_explain_token = vision_cfg["token"]

            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {
                        "name": self.board_name,
                        "version": self.firmware_version,
                    },
                },
            }

        if method == "notifications/initialized":
            return None

        if method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "tools": self.get_mcp_tools_list(),
                },
            }

        if method == "tools/call":
            tool_name = params.get("name", "")
            arguments = params.get("arguments") or {}
            res = await self.execute_mcp_tool(tool_name, arguments)
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(res, ensure_ascii=False),
                        }
                    ],
                    "isError": False,
                },
            }

        if msg_id is not None:
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {},
            }
        return None

    # =========================================================================
    # 3. LIVE XIAOZHI.ME CLOUD CONSOLE OTA & WEBSOCKET CLIENT
    # =========================================================================
    async def check_xiaozhi_ota(self, custom_ota_url: Optional[str] = None) -> Dict[str, Any]:
        """
        Contacts `https://api.tenclass.net/xiaozhi/ota/` (or user-specified OTA URL)
        to register this ESP32-S3 emulator, retrieve WebSocket credentials, and obtain
        the 6-digit `activation.code` for `https://xiaozhi.me/console/agents`.
        """
        if custom_ota_url:
            self.ota_url = custom_ota_url.strip()

        headers = {
            "Device-Id": self.mac_address,
            "Client-Id": self.client_id,
            "User-Agent": f"{self.board_name}/{self.firmware_version}",
            "Accept-Language": "vi-VN",
            "Content-Type": "application/json",
        }
        body = self.build_xiaozhi_ota_payload()

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(self.ota_url, headers=headers, json=body)
                if resp.status_code == 200:
                    data = resp.json()
                    ws_info = data.get("websocket") or {}
                    if ws_info.get("url"):
                        self.ws_url = ws_info["url"]
                    if ws_info.get("token"):
                        self.ws_token = ws_info["token"]

                    act = data.get("activation") or {}
                    self.activation_code = str(act.get("code", "")).strip()
                    self.activation_message = str(act.get("message", "")).strip()
                    self.last_ota_check = time.time()
                    self.save_state()
                    return {
                        "ok": True,
                        "mac_address": self.mac_address,
                        "client_id": self.client_id,
                        "ws_url": self.ws_url,
                        "activation_code": self.activation_code,
                        "activation_message": self.activation_message,
                        "is_bound": not bool(self.activation_code),
                        "console_url": "https://xiaozhi.me/console/agents",
                        "raw": data,
                    }
                return {"ok": False, "error": f"HTTP {resp.status_code}: {resp.text[:200]}"}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    async def chat_via_xiaozhi_cloud(self, user_text: str) -> Dict[str, Any]:
        """
        Sends a user message directly to `wss://api.tenclass.net/xiaozhi/v1/`
        as an ESP32-S3 hardware client, handles all MCP `initialize` / `tools/list` / `tools/call`
        requests from the Xiaozhi Cloud agent in real time, and returns the agent's spoken reply
        and emotion!
        """
        if time.time() - self.last_ota_check > 300:
            await self.check_xiaozhi_ota()

        ws_headers = {
            "Authorization": f"Bearer {self.ws_token}",
            "Protocol-Version": "1",
            "Device-Id": self.mac_address,
            "Client-Id": self.client_id,
        }

        sentences: List[str] = []
        emotion_tag: str = "smile"
        tools_invoked: List[str] = []
        server_opus_frames: List[bytes] = []
        decoder = OpusStreamDecoder(sample_rate=24000)

        try:
            async with websockets.connect(
                self.ws_url,
                additional_headers=ws_headers,
                open_timeout=8.0,
                close_timeout=3.0,
            ) as ws:
                self.cloud_connected = True
                hello_pkt = {
                    "type": "hello",
                    "version": 1,
                    "transport": "websocket",
                    "features": {"mcp": True, "aec": True},
                    "audio_params": {
                        "format": "opus",
                        "sample_rate": 16000,
                        "channels": 1,
                        "frame_duration": 60,
                    },
                }
                await ws.send(json.dumps(hello_pkt))

                sent_user_prompt = False
                deadline = time.time() + 22.0

                async def _send_audio_utterance():
                    nonlocal sent_user_prompt
                    if sent_user_prompt:
                        return
                    sent_user_prompt = True
                    await ws.send(
                        json.dumps(
                            {
                                "session_id": self.cloud_session_id,
                                "type": "listen",
                                "state": "start",
                                "mode": "manual",
                            }
                        )
                    )
                    frames = await text_to_mic_opus_frames(user_text)
                    for f in frames:
                        await ws.send(f)
                        await asyncio.sleep(0.018)
                    await ws.send(
                        json.dumps(
                            {
                                "session_id": self.cloud_session_id,
                                "type": "listen",
                                "state": "stop",
                            }
                        )
                    )

                while time.time() < deadline:
                    try:
                        msg = await asyncio.wait_for(ws.recv(), timeout=4.5)
                    except asyncio.TimeoutError:
                        if sent_user_prompt and (sentences or server_opus_frames):
                            break
                        if not sent_user_prompt:
                            await _send_audio_utterance()
                            continue
                        break

                    if isinstance(msg, bytes):
                        # Binary Opus audio frame from Xiaozhi Cloud TTS
                        server_opus_frames.append(msg)
                        continue

                    data = json.loads(msg)
                    mtype = data.get("type", "")

                    if mtype == "hello":
                        self.cloud_session_id = data.get("session_id", "")

                    elif mtype == "mcp":
                        mcp_payload = data.get("payload") or {}
                        method = mcp_payload.get("method", "")
                        if method == "tools/call":
                            tname = (mcp_payload.get("params") or {}).get("name", "")
                            if tname:
                                tools_invoked.append(tname)
                            deadline = time.time() + 15.0

                        mcp_reply = await self.handle_jsonrpc_mcp_message(mcp_payload)
                        if mcp_reply is not None:
                            await ws.send(
                                json.dumps(
                                    {
                                        "session_id": self.cloud_session_id,
                                        "type": "mcp",
                                        "payload": mcp_reply,
                                    }
                                )
                            )

                        # Right after answering `tools/list`, stream the user's speech audio
                        if method == "tools/list" and not sent_user_prompt:
                            await _send_audio_utterance()

                    elif mtype == "llm":
                        emo = data.get("emotion", "")
                        if emo:
                            emotion_tag = emo

                    elif mtype == "tts":
                        state = data.get("state", "")
                        if state == "sentence_start":
                            txt = (data.get("text") or "").strip()
                            if txt:
                                sentences.append(txt)
                                # Check if cloud returned a 6-digit verification code prompt
                                for token in txt.replace(".", " ").split():
                                    if len(token) == 6 and token.isdigit():
                                        self.activation_code = token
                                        self.save_state()
                        elif state == "stop":
                            break

            full_text = " ".join(sentences).strip()
            wav_bytes = decoder.decode_many_to_wav(server_opus_frames) if server_opus_frames else None
            audio_b64 = base64.b64encode(wav_bytes).decode("ascii") if wav_bytes else ""

            return {
                "ok": bool(full_text or audio_b64),
                "text": full_text,
                "audio_base64": audio_b64,
                "emotion": emotion_tag,
                "tools_invoked": tools_invoked,
                "activation_code": self.activation_code,
            }
        except Exception as e:
            self.cloud_connected = False
            return {
                "ok": False,
                "text": "",
                "error": str(e),
                "activation_code": self.activation_code,
            }


esp32_emulator = ESP32S3UltimateEmulator()
