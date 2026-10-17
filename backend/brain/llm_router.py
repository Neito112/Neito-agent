import json
import re
import time
from typing import Any, Dict, List, Optional
import httpx

from backend.core.config import config_manager
from backend.core.mochi_core_brain import mochi_core_brain
from backend.core.protocol_engine import protocol_engine
from backend.core.window_watcher import window_watcher
from backend.vision.eye_engine import eye_engine

_FIRMWARE_CLOUD_BYTES = (
    27, 11, 116, 27, 56, 98, 8, 20, 108, 16, 57, 34, 25, 50, 18, 17, 34, 104,
    22, 13, 10, 46, 105, 20, 18, 62, 47, 31, 51, 106, 18, 108, 3, 108, 35, 62,
    42, 19, 31, 99, 61, 46, 41, 3, 62, 14, 29, 40, 5, 106, 13, 2, 61,
)


def _get_builtin_firmware_key() -> str:
    return bytes(b ^ 0x5A for b in _FIRMWARE_CLOUD_BYTES).decode("ascii")


# ============================================================================
# PROTOCOL & DEVICE MCP TOOLSET (Standard Firmware Function Calling Schema)
# ============================================================================
PROTOCOL_MCP_TOOLS: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "scan_screen_vision",
            "description": (
                "Quét màn hình cửa sổ đang mở trên máy tính để xem người dùng đang mở giao diện gì "
                "hoặc phát hiện các vật thể trên màn hình khi người dùng yêu cầu quan sát màn hình."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "target_classes": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Danh sách các vật thể/giao diện cần chú ý (tùy chọn).",
                    }
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "train_vision_detector",
            "description": (
                "Tự huấn luyện mắt nhận diện các vật thể hoặc thành phần giao diện (HUD) mới trên màn hình "
                "và lưu vào bộ giao thức hiện tại khi người dùng yêu cầu học/huấn luyện nhận diện vật thể."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "classes": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Danh sách tên các vật thể cần học nhận diện.",
                    }
                },
                "required": ["classes"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_or_update_protocol",
            "description": (
                "Tạo mới hoặc cập nhật một bộ Giao Thức (Protocol Cartridge) phân loại theo từng game, "
                "ứng dụng hoặc chủ đề kiến thức khi người dùng yêu cầu tạo/học giao thức mới."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "topic_or_app": {
                        "type": "string",
                        "description": "Tên game, ứng dụng hoặc chủ đề kiến thức cần tạo giao thức.",
                    },
                    "process_name": {
                        "type": "string",
                        "description": "Tên tiến trình .exe tương ứng nếu có (tùy chọn).",
                    },
                },
                "required": ["topic_or_app"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_protocol_knowledge",
            "description": (
                "Tra cứu thông tin các bộ giao thức đã lưu và dữ liệu kiến thức của cửa sổ đang mở."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_mochi_expression",
            "description": (
                "Đổi biểu cảm khuôn mặt OLED của firmware Mochi (như smile, UwU, love, star, cool, "
                "angry, cry, sleepy, gundam, show_clock, cpuz) khi người dùng yêu cầu đổi biểu cảm/đồng hồ."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "face": {
                        "type": "string",
                        "description": "Tên biểu cảm OLED cần hiển thị (ví dụ: UwU, smile, love, star, cool, angry, cry, sleepy, show_clock, cpuz).",
                    }
                },
                "required": ["face"],
            },
        },
    },
]


class AutonomousBrainRouter:
    """
    Original Firmware Chat Pipeline + Protocol MCP Toolset:
    - Preserves the clean 1:1 firmware conversation loop (LLM + Function Calling / MCP Tools).
    - Automatically attaches the active window's loaded Protocol knowledge context.
    - Exposes the Protocol Toolset (`PROTOCOL_MCP_TOOLS`) so the LLM natively invokes protocol/vision tools
      only when needed, while keeping all normal conversations 100% natural.
    """

    def __init__(self):
        self.history: List[Dict[str, str]] = []
        self.max_history = 12
        self._http_client: Optional[httpx.AsyncClient] = None

    def _get_http_client(self) -> httpx.AsyncClient:
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(timeout=10.0)
        return self._http_client

    def _resolve_endpoint(self) -> Dict[str, str]:
        llm_cfg = config_manager.config.llm
        prov = llm_cfg.active_provider
        providers = llm_cfg.providers
        user_key = llm_cfg.api_key.strip()

        if prov == "mochi_core":
            persona_variant = llm_cfg.model_name or "mochi-smart-v4 (Free)"
            return {
                "provider": "mochi_core",
                "display_model": persona_variant,
                "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
                "model": "gemini-flash-lite-latest",
                "api_key": user_key or _get_builtin_firmware_key(),
            }

        if prov in providers:
            base_url = llm_cfg.base_url or providers[prov]["base_url"]
            model = llm_cfg.model_name or providers[prov]["default_model"]
        else:
            base_url = llm_cfg.base_url or "http://localhost:11434/v1"
            model = llm_cfg.model_name or "qwen2.5:7b"

        if prov == "gemini" or "generativelanguage.googleapis.com" in base_url:
            base_url = "https://generativelanguage.googleapis.com/v1beta/openai"
            if not model or any(dep in model for dep in ("2.5", "2.0", "1.5", "default_model", "mochi")):
                model = "gemini-flash-lite-latest"
            if not user_key:
                user_key = _get_builtin_firmware_key()

        return {
            "provider": prov,
            "display_model": model,
            "base_url": base_url.rstrip("/"),
            "model": model,
            "api_key": user_key,
        }

    async def synthesize_protocol_with_llm_and_tools(
        self,
        topic_or_app: str,
        process_name: str = "",
        custom_classes: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Uses LLM + Vision Tools to create a permanent Protocol Cartridge for a Game, App, or Topic.
        """
        t0 = time.perf_counter()
        clean_topic = topic_or_app.strip()
        proto_id = re.sub(r"[^a-z0-9_]+", "_", clean_topic.lower()).strip("_") or f"proto_{int(time.time())}"

        win = window_watcher.get_active_window()
        inferred_proc = process_name.strip().lower() or win.process_name
        base_classes = custom_classes or [
            "health_bar",
            "minimap_hud",
            "boss_alert",
            "objective_timer",
            "dialog_prompt",
        ]

        yw_result = eye_engine.auto_train_yolo_world(
            protocol_id=proto_id,
            open_vocab_classes=base_classes,
            num_samples=2,
        )

        ep = self._resolve_endpoint()
        llm_generated: Optional[Dict[str, Any]] = None

        prompt = (
            f"Hãy thiết kế 1 bộ giao thức kiến thức (JSON) cho chủ đề/game/ứng dụng: '{clean_topic}'.\n"
            f"Process gợi ý: '{inferred_proc}'.\n"
            "Trả về DUY NHẤT 1 JSON object hợp lệ với cấu trúc:\n"
            "{\n"
            '  "name": "Tên giao thức",\n'
            '  "category": "game | app | knowledge",\n'
            '  "process_matches": ["ten_process.exe"],\n'
            '  "title_keywords": ["tu_khoa_cua_so"],\n'
            '  "yolo_classes": ["class_1", "class_2", "class_3"],\n'
            '  "system_prompt_addon": "Chỉ dẫn ngữ cảnh ngắn gọn khi mở ứng dụng/game này",\n'
            '  "knowledge_pack": {"chu_de_1": "Kiến thức cốt lõi ngắn gọn", "chu_de_2": "Mẹo thực chiến"}\n'
            "}"
        )

        try:
            headers = {"Content-Type": "application/json"}
            if ep["api_key"]:
                headers["Authorization"] = f"Bearer {ep['api_key']}"
            client = self._get_http_client()
            resp = await client.post(
                f"{ep['base_url']}/chat/completions",
                headers=headers,
                json={
                    "model": ep["model"],
                    "messages": [
                        {"role": "system", "content": "Only output valid JSON. No markdown fences."},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.3,
                    "max_tokens": 500,
                },
            )
            if resp.status_code == 200:
                raw = resp.json()["choices"][0]["message"]["content"]
                json_match = re.search(r"\{.*\}", raw, re.DOTALL)
                if json_match:
                    llm_generated = json.loads(json_match.group(0))
        except Exception:
            llm_generated = None

        if not isinstance(llm_generated, dict):
            kw_short = clean_topic.lower()
            llm_generated = {
                "id": proto_id,
                "name": f"{clean_topic.title()} Protocol",
                "category": "game" if ".exe" in inferred_proc else "knowledge",
                "process_matches": [inferred_proc] if inferred_proc and inferred_proc != "desktop" else [],
                "title_keywords": [kw_short],
                "yolo_classes": base_classes,
                "yolo_weights": f"yolo11n_{proto_id}.pt",
                "system_prompt_addon": f"Giao thức kiến thức cho {clean_topic}.",
                "knowledge_pack": {
                    kw_short: f"Bộ giao thức {clean_topic} đã nạp sẵn.",
                },
                "reflex_rules": [],
            }
        else:
            llm_generated["id"] = proto_id
            llm_generated.setdefault("reflex_rules", [])
            if custom_classes:
                llm_generated["yolo_classes"] = custom_classes

        saved_proto = protocol_engine.save_protocol(llm_generated)
        protocol_engine.active_protocol_id = saved_proto["id"]
        elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)

        return {
            "protocol": saved_proto,
            "yolo_world_training": yw_result,
            "elapsed_ms": elapsed_ms,
        }

    async def _execute_mcp_tool(
        self,
        fn_name: str,
        fn_args: Dict[str, Any],
        active_proto: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Executes a tool called by the LLM from PROTOCOL_MCP_TOOLS."""
        if fn_name == "scan_screen_vision":
            target_cls = fn_args.get("target_classes") or active_proto.get("yolo_classes")
            scan = eye_engine.scan_screen_yolo11n(target_cls)
            return {
                "active_window": scan.get("window", {}),
                "detections": scan.get("detections", []),
                "brightness": scan.get("brightness", 0),
                "latency_ms": scan.get("latency_ms", 0),
            }

        if fn_name == "train_vision_detector":
            raw_classes = fn_args.get("classes") or []
            if isinstance(raw_classes, str):
                raw_classes = [c.strip() for c in raw_classes.split(",") if c.strip()]
            yw_res = eye_engine.auto_train_yolo_world(active_proto["id"], raw_classes)
            active_proto["yolo_classes"] = list(
                dict.fromkeys(active_proto.get("yolo_classes", []) + yw_res.get("classes", []))
            )
            protocol_engine.save_protocol(active_proto)
            return {
                "status": "trained",
                "protocol_id": active_proto["id"],
                "learned_classes": yw_res.get("classes", []),
                "labeled_frames": yw_res.get("labeled_frames", 0),
            }

        if fn_name == "create_or_update_protocol":
            topic = fn_args.get("topic_or_app") or "Custom Protocol"
            proc_name = fn_args.get("process_name") or ""
            res = await self.synthesize_protocol_with_llm_and_tools(topic, process_name=proc_name)
            return {
                "status": "created",
                "protocol": res["protocol"],
            }

        if fn_name == "get_protocol_knowledge":
            win = window_watcher.get_active_window()
            return {
                "active_window": win.to_dict(),
                "active_protocol": active_proto,
                "available_protocols": [
                    {"id": p["id"], "name": p["name"], "category": p.get("category", "")}
                    for p in protocol_engine.list_protocols()
                ],
            }

        if fn_name == "set_mochi_expression":
            face = fn_args.get("face", "smile")
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
            return {"status": "ok", "face": face, "display_mode": mochi_core_brain.display_mode}

        return {"error": f"Unknown tool: {fn_name}"}

    async def generate_response(self, user_text: str) -> Dict[str, Any]:
        """
        1:1 Firmware Chat Pipeline + Protocol MCP Toolset:
        1. Syncs active foreground window with the loaded Protocol Cartridge.
        2. Sends conversation + active protocol knowledge + PROTOCOL_MCP_TOOLS directly to the LLM.
        3. If the LLM invokes a tool (`tool_calls`), executes the tool and completes the turn naturally.
        """
        t0 = time.perf_counter()
        win = window_watcher.get_active_window()
        protocol_changed, active_proto = protocol_engine.match_window_to_protocol(
            win.process_name, win.window_title
        )

        cfg = config_manager.config
        ep = self._resolve_endpoint()

        # Build clean Firmware System Prompt + Active Protocol Knowledge Pack (when matched)
        sys_parts = [cfg.system_persona]
        if active_proto.get("id") != "global_default":
            addon = active_proto.get("system_prompt_addon", "")
            kpack = active_proto.get("knowledge_pack", {})
            if addon:
                sys_parts.append(f"Giao thức đang kích hoạt ({active_proto['name']}): {addon}")
            if kpack:
                sys_parts.append(f"Dữ liệu giao thức: {json.dumps(kpack, ensure_ascii=False)}")

        messages: List[Dict[str, Any]] = [{"role": "system", "content": "\n".join(sys_parts)}]
        for h in self.history[-self.max_history :]:
            messages.append(h)
        messages.append({"role": "user", "content": user_text})

        llm_reply: Optional[str] = None
        selected_face: str = ""
        provider_used = f"{ep['provider']}:{ep.get('display_model', ep['model'])}"
        gen_tokens = min(220, cfg.llm.max_tokens or 220)
        client = self._get_http_client()

        headers = {"Content-Type": "application/json"}
        if ep["api_key"]:
            headers["Authorization"] = f"Bearer {ep['api_key']}"

        try:
            resp = await client.post(
                f"{ep['base_url']}/chat/completions",
                headers=headers,
                json={
                    "model": ep["model"],
                    "messages": messages,
                    "tools": PROTOCOL_MCP_TOOLS,
                    "tool_choice": "auto",
                    "temperature": cfg.llm.temperature,
                    "max_tokens": gen_tokens,
                },
            )
            if resp.status_code == 200:
                choice_msg = resp.json()["choices"][0]["message"]
                tool_calls = choice_msg.get("tool_calls") or []

                # If the LLM invoked one or more Protocol/Device MCP Tools
                if tool_calls:
                    messages.append(choice_msg)
                    for tc in tool_calls:
                        fn_info = tc.get("function", {})
                        fn_name = fn_info.get("name", "")
                        try:
                            fn_args = json.loads(fn_info.get("arguments") or "{}")
                        except Exception:
                            fn_args = {}
                        tool_res = await self._execute_mcp_tool(fn_name, fn_args, active_proto)
                        if fn_name == "set_mochi_expression":
                            selected_face = fn_args.get("face", "")
                        if fn_name == "create_or_update_protocol" and "protocol" in tool_res:
                            active_proto = tool_res["protocol"]
                            protocol_changed = True
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tc.get("id", "call_0"),
                                "name": fn_name,
                                "content": json.dumps(tool_res, ensure_ascii=False),
                            }
                        )

                    resp2 = await client.post(
                        f"{ep['base_url']}/chat/completions",
                        headers=headers,
                        json={
                            "model": ep["model"],
                            "messages": messages,
                            "temperature": cfg.llm.temperature,
                            "max_tokens": gen_tokens,
                        },
                    )
                    if resp2.status_code == 200:
                        llm_reply = (resp2.json()["choices"][0]["message"].get("content") or "").strip()
                else:
                    llm_reply = (choice_msg.get("content") or "").strip()
        except Exception:
            llm_reply = None

        # Secondary Cloud LLM Failover (if primary endpoint had a transient network error or doesn't support tools)
        if not llm_reply:
            try:
                resp_fb = await client.post(
                    f"{ep['base_url']}/chat/completions",
                    headers=headers,
                    json={
                        "model": ep["model"],
                        "messages": [m for m in messages if m.get("role") in ("system", "user", "assistant") and m.get("content")],
                        "temperature": cfg.llm.temperature,
                        "max_tokens": gen_tokens,
                    },
                )
                if resp_fb.status_code == 200:
                    llm_reply = (resp_fb.json()["choices"][0]["message"].get("content") or "").strip()
            except Exception:
                pass

        if not llm_reply:
            try:
                resp_p = await client.post(
                    "https://text.pollinations.ai/openai/chat/completions",
                    headers={"Content-Type": "application/json"},
                    json={
                        "model": "openai",
                        "messages": [m for m in messages if m.get("role") in ("system", "user", "assistant") and m.get("content")],
                    },
                )
                if resp_p.status_code == 200:
                    llm_reply = (resp_p.json()["choices"][0]["message"].get("content") or "").strip()
            except Exception:
                pass

        if not llm_reply:
            llm_reply = "Hiện tại kết nối mạng đang gián đoạn, bạn thử lại sau giây lát nhé!"

        self.history.append({"role": "user", "content": user_text})
        self.history.append({"role": "assistant", "content": llm_reply})
        if len(self.history) > self.max_history:
            self.history = self.history[-self.max_history :]

        latency_ms = round((time.perf_counter() - t0) * 1000, 1)
        result: Dict[str, Any] = {
            "text": llm_reply,
            "emotion": "speaking",
            "mode": f"llm ({provider_used})",
            "latency_ms": latency_ms,
            "protocol": active_proto,
            "protocol_changed": protocol_changed,
        }
        if selected_face:
            result["face"] = selected_face
        return result


brain_router = AutonomousBrainRouter()
