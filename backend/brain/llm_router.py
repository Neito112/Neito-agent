import datetime
import json
import re
import time
from typing import Any, Dict, List, Optional, Tuple
import httpx

from backend.core.config import config_manager
from backend.core.esp32_hardware_emulator import esp32_emulator
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


# Valid Mochi Firmware OLED face names for emotional expression
VALID_MOCHI_FACES = {
    "mac_dinh", "smile", "happy_2", "UwU", "hehe", "laugh", "love", "love2",
    "star", "cool", "wink", "nheo_mat", "angry", "angry2", "angry3", "cry",
    "cry2", "scared", "sleepy", "distracted", "cuoi_khinh_bi", "yelling",
    "chong_mat", "samurai", "gundam", "neon", "sakura", "music", "show_clock", "cpuz",
}

EMOJI_AND_SYMBOL_RE = re.compile(
    "["
    "\U00010000-\U0010ffff"  # Supplementary planes (all emojis, pictographs, transport/map symbols)
    "\u2600-\u27bf"          # Misc symbols & dingbats
    "\u2300-\u23ff"          # Misc technical symbols
    "\u2b00-\u2bff"          # Misc symbols and arrows
    "\ufe00-\ufe0f"          # Variation selectors
    "\u200d"                 # Zero width joiner
    "]+",
    flags=re.UNICODE,
)


def extract_face_and_clean_speech(raw_text: str) -> Tuple[str, str]:
    """
    Original Firmware Output Sanitizer:
    1. Strips any <think>...</think> or <thought>...</thought> reasoning blocks.
    2. Extracts [face:<name>] tag (if present) so the mascot expresses emotion via its OLED face.
    3. Strips kaomojis/stage directions like (UwU), (*cười*), *cười*, and all emojis/icons/markdown
       so only pure spoken Vietnamese dialogue is displayed and spoken by TTS.
    """
    if not raw_text:
        return "", ""

    text = raw_text

    # 1. Remove <think>...</think> or <thought>...</thought> blocks (including unclosed ones)
    text = re.sub(r"<think(?:ing)?>.*?(?:</think(?:ing)?>|$)", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<thought>.*?(?:</thought>|$)", "", text, flags=re.DOTALL | re.IGNORECASE)

    # 2. Extract [face:xxx] or [emotion:xxx] tag
    chosen_face = ""
    face_match = re.search(r"\[\s*(?:face|emotion|bieu_cam)\s*:\s*([a-zA-Z0-9_]+)\s*\]", text, flags=re.IGNORECASE)
    if face_match:
        candidate = face_match.group(1).strip()
        if candidate in VALID_MOCHI_FACES:
            chosen_face = candidate
        elif candidate.lower() == "uwu":
            chosen_face = "UwU"
        elif candidate.lower() in ("happy", "vui"):
            chosen_face = "smile"
        elif candidate.lower() in ("sad", "buon"):
            chosen_face = "cry"
    # Strip any bracket tags like [face:...] or [UwU]
    text = re.sub(r"\[[^\]]*\]", " ", text)

    # 3. Detect if LLM wrote (UwU) before stripping it
    if not chosen_face and re.search(r"\(\s*uwu\s*\)", text, flags=re.IGNORECASE):
        chosen_face = "UwU"

    # 4. Strip parenthetical stage directions / kaomojis / inline reasoning like (UwU), (cười), (Suy nghĩ: ...)
    text = re.sub(
        r"\(\s*(?:uwu|>\.<|\^_\^|suy nghĩ[^)]*|suy luận[^)]*|cười[^)]*|nháy mắt[^)]*|thở dài[^)]*|gật đầu[^)]*|lắc đầu[^)]*)\s*\)",
        " ",
        text,
        flags=re.IGNORECASE,
    )
    # Strip asterisk stage directions like *cười khúc khích* while keeping normal words if bolded
    text = re.sub(r"\*+[^*\n]{1,30}\*+", lambda m: m.group(0).strip("*"), text)

    # 5. Strip all markdown symbols and Unicode emojis/icons
    text = re.sub(r"[*#`_~|<>]+", "", text)
    text = EMOJI_AND_SYMBOL_RE.sub("", text)

    # 6. Normalize whitespace
    text = re.sub(r"\s+", " ", text).strip()

    # 7. Auto-select an expressive Mochi OLED face from dialogue tone if LLM didn't tag one
    if not chosen_face:
        tl = text.lower()
        if any(w in tl for w in ["yêu", "thương", "ngọt ngào", "thả tim", "nhớ bạn"]):
            chosen_face = "love"
        elif any(w in tl for w in ["haha", "hihi", "buồn cười", "trêu", "đùa"]):
            chosen_face = "hehe"
        elif any(w in tl for w in ["tuyệt vời", "xuất sắc", "đỉnh", "quá chuẩn"]):
            chosen_face = "star"
        elif any(w in tl for w in ["buồn", "tiếc", "khóc", "xin lỗi"]):
            chosen_face = "cry"
        elif any(w in tl for w in ["ngủ", "khuya", "mệt"]):
            chosen_face = "sleepy"
        elif any(w in tl for w in ["dễ thương", "đáng yêu", "nè", "nha"]):
            chosen_face = "UwU"
        else:
            chosen_face = "smile"

    return chosen_face, text


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
                "angry, cry, sleepy, gundam, show_clock, cpuz) khi người dùng yêu cầu đổi biểu cảm hoặc xem đồng hồ."
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
    - Uses Mochi/Xiaozhi Cloud Free LLM out of the box (plus optional user providers).
    - Expresses emotions visually via the 71 Mochi OLED faces (`face`), never via text emojis/icons.
    -Outputs clean, plain spoken Vietnamese sentences for Speech Bubble & TTS.
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
            proc_matches = llm_generated.get("process_matches")
            if not isinstance(proc_matches, list):
                proc_matches = []
            if inferred_proc and inferred_proc != "desktop":
                if not any(p.lower() == inferred_proc.lower() for p in proc_matches):
                    proc_matches.insert(0, inferred_proc.lower())
            llm_generated["process_matches"] = proc_matches
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
        """Executes a tool called by the LLM from PROTOCOL_MCP_TOOLS or ESP32-S3 Hardware MCP."""
        return await esp32_emulator.execute_mcp_tool(fn_name, fn_args)

    async def generate_response(self, user_text: str) -> Dict[str, Any]:
        """
        1:1 Firmware Chat Pipeline + ESP32-S3 Hardware & Screen-YOLO MCP Toolset:
        - Supports both Xiaozhi Cloud Console (`xiaozhi_cloud` -> https://xiaozhi.me/console/agents)
          AND Direct LLM API Key mode (`mochi_core`, `gemini`, `openai`, `deepseek`, `groq`, `ollama`, `lmstudio`).
        - Syncs active foreground window with the loaded Protocol Cartridge.
        - Drives the mascot's 71 OLED faces (`face`) directly from LLM emotion tag.
        - Strips all icons, emojis, markdown symbols, and reasoning blocks so only pure spoken text
          is sent to the speech bubble and TTS engine.
        """
        t0 = time.perf_counter()
        win = window_watcher.get_active_window()
        protocol_changed, active_proto = protocol_engine.match_window_to_protocol(
            win.process_name, win.window_title
        )

        cfg = config_manager.config

        # ------------------------------------------------------------------
        # MODE A: XIAOZHI.ME CLOUD CONSOLE (`wss://api.tenclass.net/xiaozhi/v1/`)
        # ------------------------------------------------------------------
        if cfg.llm.active_provider == "xiaozhi_cloud":
            cloud_res = await esp32_emulator.chat_via_xiaozhi_cloud(user_text)
            cloud_text = (cloud_res.get("text") or "").strip()
            act_code = cloud_res.get("activation_code", "")

            if "verification code" in cloud_text.lower() or "add this device" in cloud_text.lower():
                code_display = act_code or esp32_emulator.activation_code or "619847"
                raw_reply = (
                    f"[face:star] Mạch giả lập ESP32 S3 của mình đã kết nối tới hệ thống Xiaozhi. "
                    f"Mã xác thực 6 số của thiết bị là {code_display}. "
                    f"Bạn hãy mở trang xiaozhi.me/console/agents và nhập mã {code_display} để liên kết thiết bị nhé."
                )
            elif cloud_text:
                emo = cloud_res.get("emotion", "smile")
                face_tag = emo if emo in VALID_MOCHI_FACES else "smile"
                raw_reply = f"[face:{face_tag}] {cloud_text}"
            else:
                raw_reply = ""

            if raw_reply:
                parsed_face, clean_reply = extract_face_and_clean_speech(raw_reply)
                final_face = parsed_face or "smile"
                mochi_core_brain.current_face = final_face
                mochi_core_brain.display_mode = final_face if final_face in ("show_clock", "cpuz") else "face"
                self.history.append({"role": "user", "content": user_text})
                self.history.append({"role": "assistant", "content": clean_reply})
                latency_ms = round((time.perf_counter() - t0) * 1000, 1)
                return {
                    "text": clean_reply,
                    "audio_base64": cloud_res.get("audio_base64", ""),
                    "face": final_face,
                    "emotion": "speaking",
                    "mode": "xiaozhi_cloud (xiaozhi.me/console/agents)",
                    "latency_ms": latency_ms,
                    "protocol": active_proto,
                    "protocol_changed": protocol_changed,
                }

        # ------------------------------------------------------------------
        # MODE B: DIRECT LLM API KEY MODE + BUILT-IN ESP32-S3 HARDWARE & YOLO MCP
        # ------------------------------------------------------------------
        ep = self._resolve_endpoint()
        now_str = datetime.datetime.now().strftime("%H:%M, ngày %d/%m/%Y")

        sys_parts = [
            cfg.system_persona,
            (
                "QUY TẮC ĐẦU RA CỦA FIRMWARE:\n"
                "- Mở đầu câu trả lời bằng đúng 1 thẻ biểu cảm khuôn mặt: [face:<tên>] "
                "(chọn 1 trong: smile, UwU, happy_2, hehe, laugh, love, star, cool, wink, nheo_mat, angry, cry, scared, sleepy).\n"
                "- Theo sau thẻ [face:<tên>] là lời nói thuần túy bằng tiếng Việt tự nhiên (1-2 câu ngắn gọn).\n"
                "- TUYỆT ĐỐI KHÔNG dùng bất kỳ emoji/icon nào, KHÔNG viết chữ (UwU) hay *hành động*, KHÔNG dùng ký hiệu markdown (*, #, ~), và KHÔNG xuất phần suy luận.\n"
                "- Bình thường trong giao tiếp hằng ngày KHÔNG tự ý nhắc đến tên phần mềm bên trong; chỉ khi người dùng chủ động hỏi bạn được tạo ra như thế nào / cấu tạo phần cứng ra sao thì mới giải thích bạn đang chạy trên mạch giả lập phần cứng ESP32-S3-N16R8-CAM-BOX3 cấu hình mạnh nhất (kết nối được cả xiaozhi.me/console/agents, Chronos BLE và the-mochi), với Camera phần cứng nhìn thẳng vào màn hình máy tính và chip NPU YOLO11n tích hợp sẵn như một MCP phần cứng cùng hệ thống Giao thức thông minh.\n"
                f"- Thời gian hệ thống hiện tại: {now_str}."
            ),
        ]
        if active_proto.get("id") != "global_default":
            addon = active_proto.get("system_prompt_addon", "")
            kpack = active_proto.get("knowledge_pack", {})
            if addon:
                sys_parts.append(f"Giao thức đang mở ({active_proto['name']}): {addon}")
            if kpack:
                sys_parts.append(f"Dữ liệu giao thức: {json.dumps(kpack, ensure_ascii=False)}")

        messages: List[Dict[str, Any]] = [{"role": "system", "content": "\n".join(sys_parts)}]
        for h in self.history[-self.max_history :]:
            messages.append(h)
        messages.append({"role": "user", "content": user_text})

        raw_reply: Optional[str] = None
        tool_selected_face: str = ""
        provider_used = f"{ep['provider']}:{ep.get('display_model', ep['model'])}"
        gen_tokens = min(200, cfg.llm.max_tokens or 200)
        client = self._get_http_client()

        headers = {"Content-Type": "application/json"}
        if ep["api_key"]:
            headers["Authorization"] = f"Bearer {ep['api_key']}"

        combined_tools = esp32_emulator.get_openai_function_tools() + PROTOCOL_MCP_TOOLS

        try:
            resp = await client.post(
                f"{ep['base_url']}/chat/completions",
                headers=headers,
                json={
                    "model": ep["model"],
                    "messages": messages,
                    "tools": combined_tools,
                    "tool_choice": "auto",
                    "temperature": cfg.llm.temperature,
                    "max_tokens": gen_tokens,
                },
            )
            if resp.status_code == 200:
                choice_msg = resp.json()["choices"][0]["message"]
                tool_calls = choice_msg.get("tool_calls") or []

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
                        if fn_name in ("set_mochi_expression", "self_screen_set_expression"):
                            tool_selected_face = fn_args.get("face", "")
                        if fn_name in ("create_or_update_protocol", "self_protocol_create_or_update") and "protocol" in tool_res:
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
                        raw_reply = (resp2.json()["choices"][0]["message"].get("content") or "").strip()
                else:
                    raw_reply = (choice_msg.get("content") or "").strip()
        except Exception:
            raw_reply = None

        if not raw_reply:
            try:
                resp_fb = await client.post(
                    f"{ep['base_url']}/chat/completions",
                    headers=headers,
                    json={
                        "model": ep["model"],
                        "messages": [
                            m for m in messages
                            if m.get("role") in ("system", "user", "assistant") and m.get("content")
                        ],
                        "temperature": cfg.llm.temperature,
                        "max_tokens": gen_tokens,
                    },
                )
                if resp_fb.status_code == 200:
                    raw_reply = (resp_fb.json()["choices"][0]["message"].get("content") or "").strip()
            except Exception:
                pass

        if not raw_reply:
            raw_reply = "[face:sleepy] Kết nối mạng đang gián đoạn, bạn thử lại sau giây lát nhé."

        parsed_face, clean_reply = extract_face_and_clean_speech(raw_reply)
        final_face = tool_selected_face or parsed_face or "smile"
        if not clean_reply:
            clean_reply = "Mình nghe đây, bạn cần mình hỗ trợ gì nào?"

        # Update Mochi Firmware Core face state
        mochi_core_brain.current_face = final_face
        mochi_core_brain.display_mode = final_face if final_face in ("show_clock", "cpuz") else "face"

        self.history.append({"role": "user", "content": user_text})
        self.history.append({"role": "assistant", "content": clean_reply})
        if len(self.history) > self.max_history:
            self.history = self.history[-self.max_history :]

        latency_ms = round((time.perf_counter() - t0) * 1000, 1)
        return {
            "text": clean_reply,
            "face": final_face,
            "emotion": "speaking",
            "mode": f"llm ({provider_used})",
            "latency_ms": latency_ms,
            "protocol": active_proto,
            "protocol_changed": protocol_changed,
        }


brain_router = AutonomousBrainRouter()
