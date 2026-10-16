import json
import random
import re
import time
from typing import Dict, Any, List, Optional, AsyncGenerator
import httpx

from backend.core.config import config_manager
from backend.core.protocol_engine import protocol_engine
from backend.core.window_watcher import window_watcher
from backend.vision.eye_engine import eye_engine


class AutonomousBrainRouter:
    """
    Autonomous Multi-Provider Brain for Neito-agent:
    - Connects to Local LLMs (Ollama, LM Studio, vLLM) and Cloud APIs (OpenAI, Gemini, DeepSeek, Groq).
    - Integrates Agent Tools:
        1. `scan_screen_yolo11n` (Live screen vision analysis)
        2. `train_eye_yolo_world` (Open-vocabulary auto-labeling & YOLO11n dataset builder)
        3. `build_reflex_protocol` (Generates & saves permanent high-speed Protocol Cartridges)
    - Includes a zero-latency Local Tactical Brain fallback so the app runs 100% standalone even before
      an external LLM server or API key is configured.
    """

    def __init__(self):
        self.history: List[Dict[str, str]] = []
        self.max_history = 10

    def _resolve_endpoint(self) -> Dict[str, str]:
        llm_cfg = config_manager.config.llm
        prov = llm_cfg.active_provider
        providers = llm_cfg.providers

        if prov in providers:
            base_url = llm_cfg.base_url or providers[prov]["base_url"]
            model = llm_cfg.model_name or providers[prov]["default_model"]
        else:
            base_url = llm_cfg.base_url or "http://localhost:11434/v1"
            model = llm_cfg.model_name or "qwen2.5:7b"

        # Auto-upgrade deprecated Google Gemini model names to the active standard
        if prov == "gemini":
            if not model or any(dep in model for dep in ("2.5", "2.0", "1.5", "default_model")):
                model = "gemini-flash-lite-latest"

        return {
            "provider": prov,
            "base_url": base_url.rstrip("/"),
            "model": model,
            "api_key": llm_cfg.api_key.strip(),
        }

    def _offline_conversational_reflex(self, text: str, win_title: str, proto_name: str) -> str:
        """
        Rich, human-like offline companion dialogue when external LLM is offline or unconfigured.
        Answers greetings, identity, time, math, questions, and small talk naturally.
        """
        import datetime
        t = text.lower().strip()

        # 1. Greetings (explicit greeting words, avoiding false positives like 'chơi')
        if re.search(r"(?:\b|^)(?:chào|hello|hi|alo|helo|neito\s*ơi|ơi\s+neito)(?:\b|$|[!?,.])", t) or t in ["hi", "ê", "alo"]:
            return random.choice([
                "Chào bạn! Neito đây, có chuyện gì thú vị không?",
                "Moshi moshi! Mình nghe đây, bạn cần mình giúp gì nào?",
                "Chào bạn nhé! Mình vẫn đang đồng hành cùng bạn đây.",
            ])

        # 2. Identity & Name
        if any(w in t for w in ["tên gì", "là ai", "bạn là ai", "giới thiệu"]):
            return "Mình là Neito, linh vật AI thông minh đồng hành trực tiếp trên màn hình desktop của bạn!"

        # 3. How are you / Health
        if any(w in t for w in ["khỏe không", "thế nào", "ổn không", "bạn sao rồi"]):
            return "Mình lúc nào cũng tràn đầy 100% năng lượng! Còn bạn hôm nay thế nào?"

        # 4. Capabilities / What can you do
        if any(w in t for w in ["làm được gì", "biết làm gì", "chức năng", "giúp gì"]):
            return "Mình có thể trò chuyện, nhìn màn hình bằng YOLO11n, nhận diện app/game và phản xạ tương tác realtime!"

        # 5. Clock / Time
        if any(w in t for w in ["mấy giờ", "thời gian", "ngày mấy", "hôm nay ngày"]):
            now_str = datetime.datetime.now().strftime("%H:%M, ngày %d/%m/%Y")
            return f"Bây giờ là {now_str} nhé bạn!"

        # 6. Basic Math Calculation (e.g. 5 + 7, 100 * 2)
        math_match = re.search(r"(\d+(?:\.\d+)?)\s*([\+\-\*\/xX])\s*(\d+(?:\.\d+)?)", t)
        if math_match:
            try:
                a = float(math_match.group(1))
                op = math_match.group(2).lower()
                b = float(math_match.group(3))
                if op in ("+",): res = a + b
                elif op in ("-",): res = a - b
                elif op in ("*", "x"): res = a * b
                elif op in ("/",): res = a / b if b != 0 else "vô cực"
                else: res = 0
                res_fmt = int(res) if isinstance(res, (int, float)) and res == int(res) else res
                return f"Kết quả là {res_fmt} nhé!"
            except Exception:
                pass

        # 7. Thanks & Compliments
        if any(w in t for w in ["cảm ơn", "thank", "tuyệt", "giỏi", "cute", "dễ thương"]):
            return "Hihi, cảm ơn bạn nhiều nhé! Có bạn cùng làm việc là vui nhất rồi."

        # 8. Active App / Game Inquiry
        if any(w in t for w in ["đang làm gì", "đang mở gì", "thấy gì"]):
            return f"Bạn đang mở {win_title} ({proto_name}), mình đang quan sát cùng bạn đây."

        # 9. Natural Varied Companion Reflections
        return random.choice([
            f"Mình hiểu ý bạn rồi! Đang tập trung theo dõi cùng bạn trên {win_title}.",
            "Câu này hay đấy! Bạn cần mình phân tích sâu hơn hay cứ tiếp tục công việc nhé?",
            f"Neito đã ghi nhận! Mình luôn túc trực hỗ trợ bạn mọi lúc.",
        ])

    async def synthesize_protocol_with_llm_and_tools(
        self,
        topic_or_app: str,
        process_name: str = "",
        custom_classes: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Uses LLM + Vision Tools (YOLO-World discovery) to create a permanent high-speed
        Reflex Protocol Cartridge for any Game, App, or Knowledge Domain.
        """
        t0 = time.perf_counter()
        clean_topic = topic_or_app.strip()
        proto_id = re.sub(r"[^a-z0-9_]+", "_", clean_topic.lower()).strip("_") or f"proto_{int(time.time())}"

        # Step 1: Capture current window context & run YOLO-World discovery if applicable
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

        # Step 2: Try asking configured LLM to generate rich domain rules & knowledge
        ep = self._resolve_endpoint()
        llm_generated: Optional[Dict[str, Any]] = None

        prompt = (
            f"Hãy thiết kế 1 bộ giao thức phản xạ tốc độ cao (JSON) cho chủ đề/game/ứng dụng: '{clean_topic}'.\n"
            f"Process gợi ý: '{inferred_proc}'.\n"
            "Trả về DUY NHẤT 1 JSON object hợp lệ với cấu trúc:\n"
            "{\n"
            '  "name": "Tên giao thức",\n'
            '  "category": "game | app | knowledge",\n'
            '  "process_matches": ["ten_process.exe"],\n'
            '  "title_keywords": ["tu_khoa_cua_so"],\n'
            '  "yolo_classes": ["class_1", "class_2", "class_3"],\n'
            '  "system_prompt_addon": "Chỉ dẫn ngắn gọn cho AI khi ở chế độ này",\n'
            '  "knowledge_pack": {"chu_de_1": "Kiến thức cốt lõi ngắn gọn", "chu_de_2": "Mẹo phản xạ nhanh"},\n'
            '  "reflex_rules": [\n'
            '    {"id": "rx_1", "trigger_type": "keyword", "patterns": ["từ khóa 1", "từ khóa 2"], '
            '"response": "Câu phản hồi tức thì dưới 20 từ", "emotion": "speaking", "cooldown_sec": 4},\n'
            '    {"id": "rx_vis_1", "trigger_type": "vision", "target_class": "class_1", '
            '"min_conf": 0.45, "response": "Cảnh báo thị giác tức thì", "emotion": "alert", "cooldown_sec": 15}\n'
            "  ]\n"
            "}"
        )

        try:
            headers = {"Content-Type": "application/json"}
            if ep["api_key"]:
                headers["Authorization"] = f"Bearer {ep['api_key']}"
            async with httpx.AsyncClient(timeout=6.0) as client:
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
                        "max_tokens": 600,
                    },
                )
                if resp.status_code == 200:
                    raw = resp.json()["choices"][0]["message"]["content"]
                    json_match = re.search(r"\{.*\}", raw, re.DOTALL)
                    if json_match:
                        llm_generated = json.loads(json_match.group(0))
        except Exception:
            llm_generated = None

        # Step 3: Merge LLM output or high-speed Autonomous Template Builder
        if not isinstance(llm_generated, dict):
            kw_short = clean_topic.lower()
            llm_generated = {
                "id": proto_id,
                "name": f"{clean_topic.title()} Reflex Protocol",
                "category": "game" if ".exe" in inferred_proc else "knowledge",
                "process_matches": [inferred_proc] if inferred_proc and inferred_proc != "desktop" else [],
                "title_keywords": [kw_short],
                "yolo_classes": base_classes,
                "yolo_weights": f"yolo11n_{proto_id}.pt",
                "system_prompt_addon": (
                    f"Chế độ phản xạ tốc độ cao cho {clean_topic}. "
                    "Trả lời cực nhanh, ưu tiên chiến thuật và dữ liệu thực chiến."
                ),
                "knowledge_pack": {
                    kw_short: f"Bộ giao thức {clean_topic} đã nạp: theo dõi { ', '.join(base_classes[:3]) } ở tốc độ cao.",
                    "chiến thuật": f"Ưu tiên quan sát HUD {clean_topic} và kích hoạt phản xạ <15ms khi có biến động.",
                },
                "reflex_rules": [
                    {
                        "id": f"rx_{proto_id}_guide",
                        "trigger_type": "keyword",
                        "patterns": [kw_short, "hướng dẫn", "mẹo", "combo", "chiến thuật"],
                        "response": f"Giao thức {clean_topic} đang kích hoạt! Mắt YOLO11n đang khóa mục tiêu: {', '.join(base_classes[:3])}.",
                        "emotion": "happy",
                        "cooldown_sec": 3,
                    },
                    {
                        "id": f"rx_{proto_id}_vision",
                        "trigger_type": "vision",
                        "target_class": base_classes[0],
                        "min_conf": 0.45,
                        "response": f"Phát hiện tín hiệu {base_classes[0]} trong {clean_topic}! Chú ý xử lý tình huống ngay!",
                        "emotion": "alert",
                        "cooldown_sec": 18,
                    },
                ],
            }
        else:
            llm_generated["id"] = proto_id
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

    async def generate_response(self, user_text: str) -> Dict[str, Any]:
        """
        Full Autonomous Response Pipeline:
        1. Sync Active Window -> Auto-load matching Protocol Cartridge (<1ms)
        2. Check Instant Reflex Cache (<10ms)
        3. Check Autonomous Tool Triggers (Screen Vision Scan, YOLO-World Training, Protocol Creation)
        4. Query Configured Multi-Provider LLM (or Zero-Latency Local Tactical Brain fallback)
        """
        t0 = time.perf_counter()
        win = window_watcher.get_active_window()
        protocol_changed, active_proto = protocol_engine.match_window_to_protocol(
            win.process_name, win.window_title
        )

        text_lower = user_text.strip().lower()

        # --- A. Autonomous Tool 1: Create / Compile New Protocol ---
        create_proto_match = re.search(
            r"(?:tạo giao thức|học giao thức|tạo bộ não|build protocol|thêm game|học chủ đề)\s+(?:cho\s+)?(.+)",
            text_lower,
        )
        if create_proto_match:
            topic = create_proto_match.group(1).strip()
            res = await self.synthesize_protocol_with_llm_and_tools(topic)
            proto = res["protocol"]
            return {
                "text": f"Đã học xong {proto['name']}.",
                "emotion": "happy",
                "mode": "protocol_builder",
                "latency_ms": res["elapsed_ms"],
                "protocol": proto,
                "protocol_changed": True,
            }

        # --- B. Autonomous Tool 2: Self-Train Eye with YOLO-World ---
        train_match = re.search(
            r"(?:huấn luyện mắt|train yolo|dạy mắt tìm|học vật thể|yolo-world)\s*[:\-]?\s*(.+)",
            text_lower,
        )
        if train_match:
            raw_classes = [c.strip() for c in re.split(r"[,;]+", train_match.group(1)) if c.strip()]
            yw_res = eye_engine.auto_train_yolo_world(active_proto["id"], raw_classes)
            active_proto["yolo_classes"] = list(dict.fromkeys(active_proto.get("yolo_classes", []) + raw_classes))
            protocol_engine.save_protocol(active_proto)
            return {
                "text": f"Đã ghi nhớ hình ảnh: {', '.join(yw_res['classes'])}.",
                "emotion": "scanning",
                "mode": "yolo_world_trainer",
                "latency_ms": yw_res["elapsed_ms"],
                "protocol": active_proto,
                "vision": yw_res,
            }

        # --- C. Autonomous Tool 3: On-Demand Screen Vision Scan (YOLO11n) ---
        if any(
            k in text_lower
            for k in ["nhìn màn hình", "quét màn hình", "trên màn hình", "đang mở gì", "mắt thấy gì", "scan screen"]
        ):
            scan = eye_engine.scan_screen_yolo11n(active_proto.get("yolo_classes"))
            det_list = scan.get("detections", [])
            det_str = ", ".join(d["class_name"] for d in det_list) if det_list else "bình thường"
            return {
                "text": f"Đang thấy {win.window_title}, tín hiệu {det_str}.",
                "emotion": "scanning",
                "mode": "yolo11n_vision",
                "latency_ms": scan["latency_ms"],
                "protocol": active_proto,
                "vision": scan,
            }

        # --- D. Sub-15ms Instant Reflex Protocol Lookup ---
        reflex_hit = protocol_engine.evaluate_text_reflex(user_text)
        if reflex_hit:
            latency_ms = round((time.perf_counter() - t0) * 1000, 2)
            return {
                "text": reflex_hit["response"],
                "emotion": reflex_hit["emotion"],
                "mode": reflex_hit["mode"],
                "latency_ms": latency_ms,
                "protocol": active_proto,
                "protocol_changed": protocol_changed,
            }

        # --- E. Neural Visual-Cognitive Context + Multi-Provider LLM Inference ---
        needs_vision = any(
            k in text_lower
            for k in ["nhìn màn hình", "quét màn hình", "trên màn hình", "đang mở gì", "mắt thấy gì", "màn hình", "scan screen"]
        )
        if needs_vision:
            scan_ctx = eye_engine.scan_screen_yolo11n(active_proto.get("yolo_classes"))
        else:
            scan_ctx = {"latency_ms": 0.0, "detections": [], "screen_summary": "bình thường", "neural": {"affect": {"surprise": 0.0, "focus": 0.75}}}

        neural_info = scan_ctx.get("neural", {})
        affect = neural_info.get("affect", {})
        cfg = config_manager.config
        sys_prompt = (
            f"{cfg.system_persona}\n"
            "QUY TẮC SỐNG CÒN: Trả lời tự nhiên như con người, tối đa 1 câu cực ngắn (dưới 18 từ), đi thẳng vào trọng tâm, "
            "KHÔNG dùng ngoặc vuông, KHÔNG giải thích dài dòng.\n"
            f"Ngữ cảnh đang mở: {win.window_title} ({active_proto['name']}).\n"
            f"Kiến thức nền: {json.dumps(active_proto.get('knowledge_pack', {}), ensure_ascii=False)}"
        )

        messages = [{"role": "system", "content": sys_prompt}]
        for h in self.history[-6:]:
            messages.append(h)
        messages.append({"role": "user", "content": user_text})

        ep = self._resolve_endpoint()
        llm_reply: Optional[str] = None
        provider_used = ep["provider"]

        # 1. Native Mochi Core Brain (Free Firmware Gốc - Sub-10ms latency, zero API key)
        if ep["provider"] == "mochi_core":
            llm_reply = self._offline_conversational_reflex(
                user_text, win.window_title, active_proto.get("name", "Desktop")
            )
            provider_used = f"mochi-core:{ep.get('model', 'smart-v4')}"

        # 2. External Cloud / Local LLMs (Gemini, OpenAI, DeepSeek, Groq, Ollama)
        else:
            try:
                headers = {"Content-Type": "application/json"}
                if ep["api_key"]:
                    headers["Authorization"] = f"Bearer {ep['api_key']}"
                gen_tokens = min(120, cfg.llm.max_tokens or 120)
                async with httpx.AsyncClient(timeout=3.5) as client:
                    resp = await client.post(
                        f"{ep['base_url']}/chat/completions",
                        headers=headers,
                        json={
                            "model": ep["model"],
                            "messages": messages,
                            "temperature": cfg.llm.temperature,
                            "max_tokens": gen_tokens,
                        },
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        llm_reply = data["choices"][0]["message"]["content"].strip()
                        provider_used = f"{ep['provider']}:{ep['model']}"
                    elif ep["provider"] == "gemini" and resp.status_code in (404, 503):
                        alt_model = "gemini-flash-lite-latest" if ep["model"] != "gemini-flash-lite-latest" else "gemini-3.8-flash"
                        resp2 = await client.post(
                            f"{ep['base_url']}/chat/completions",
                            headers=headers,
                            json={
                                "model": alt_model,
                                "messages": messages,
                                "temperature": cfg.llm.temperature,
                                "max_tokens": gen_tokens,
                            },
                        )
                        if resp2.status_code == 200:
                            data = resp2.json()
                            llm_reply = data["choices"][0]["message"]["content"].strip()
                            provider_used = f"gemini:{alt_model}"
            except Exception:
                llm_reply = None

        # --- F. Human-like Neural Intuition Fallback (Offline Ready, Zero Clutter) ---
        if not llm_reply:
            provider_used = "neural-reflex"
            llm_reply = self._offline_conversational_reflex(
                user_text, win.window_title, active_proto.get("name", "Desktop")
            )

        self.history.append({"role": "user", "content": user_text})
        self.history.append({"role": "assistant", "content": llm_reply})
        if len(self.history) > self.max_history:
            self.history = self.history[-self.max_history :]

        latency_ms = round((time.perf_counter() - t0) * 1000, 1)
        return {
            "text": llm_reply,
            "emotion": neural_info.get("emotion", "speaking"),
            "mode": f"llm ({provider_used})",
            "latency_ms": latency_ms,
            "protocol": active_proto,
            "protocol_changed": protocol_changed,
            "vision": scan_ctx,
        }


brain_router = AutonomousBrainRouter()
