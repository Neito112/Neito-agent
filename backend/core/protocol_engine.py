import json
import re
import time
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

import sys

def _resolve_protocols_dir() -> Path:
    if getattr(sys, "frozen", False):
        exe_p = Path(sys.executable).resolve().parent / "backend" / "protocols"
        if exe_p.exists():
            return exe_p
        if hasattr(sys, "_MEIPASS"):
            bundle_p = Path(sys._MEIPASS) / "backend" / "protocols"
            if bundle_p.exists():
                return bundle_p
    return Path(__file__).resolve().parent.parent / "protocols"

PROTOCOLS_DIR = _resolve_protocols_dir()
try:
    PROTOCOLS_DIR.mkdir(parents=True, exist_ok=True)
except Exception:
    pass


DEFAULT_PROTOCOLS: List[Dict[str, Any]] = [
    {
        "id": "global_default",
        "name": "Global Desktop & General Knowledge",
        "category": "system",
        "process_matches": ["explorer.exe", "chrome.exe", "msedge.exe", "firefox.exe", "desktop"],
        "title_keywords": ["desktop", "browser", "google", "youtube"],
        "yolo_classes": ["notification_popup", "dialog_box", "video_player", "error_alert", "person"],
        "yolo_weights": "yolo11n.pt",
        "system_prompt_addon": (
            "Chế độ: Trợ lý toàn cục siêu tốc. Phản hồi cực ngắn gọn, sắc sảo, "
            "ưu tiên giải quyết vấn đề ngay trong 1-2 câu."
        ),
        "knowledge_pack": {
            "shortcuts": "Alt+Space: Gọi nhanh Neito | Cuộn chuột giữa trên Mascot: Phóng to/Thu nhỏ.",
            "capabilities": "Nghe (Xiaozhi VAD), Nói (OmniVoice), Nhìn (YOLO11n), Tự học vật thể mới (YOLO-World).",
        },
        "reflex_rules": [
            {
                "id": "rx_hello",
                "trigger_type": "keyword",
                "patterns": ["chào", "hello", "hi neito", "neito ơi"],
                "response": "Neito sẵn sàng! Mắt YOLO11n và bộ não phản xạ đang trực chiến.",
                "emotion": "happy",
                "cooldown_sec": 3,
            },
            {
                "id": "rx_status",
                "trigger_type": "keyword",
                "patterns": ["tình trạng", "status", "ram", "cấu hình", "fps"],
                "response": "Hệ thống đang chạy ở chế độ Gaming Eco siêu nhẹ, mắt YOLO11n và tai Xiaozhi hoạt động ổn định.",
                "emotion": "speaking",
                "cooldown_sec": 3,
            },
            {
                "id": "rx_vision_error",
                "trigger_type": "vision",
                "target_class": "error_alert",
                "min_conf": 0.55,
                "response": "Cảnh báo! Mắt YOLO11n vừa phát hiện hộp thoại báo lỗi hoặc cảnh báo đỏ trên màn hình.",
                "emotion": "alert",
                "cooldown_sec": 25,
            },
        ],
    },
    {
        "id": "elden_ring_combat",
        "name": "Elden Ring / Souls-like Combat Protocol",
        "category": "game",
        "process_matches": ["eldenring.exe", "nightreign.exe", "sekiro.exe", "darksoulsiii.exe", "nioh.exe", "nioh2.exe"],
        "title_keywords": ["elden ring", "sekiro", "nioh", "dark souls", "boss"],
        "yolo_classes": ["player_hp_low", "stamina_depleted", "boss_health_bar", "you_died_banner", "flask_icon"],
        "yolo_weights": "yolo11n_souls.pt",
        "system_prompt_addon": (
            "Đang trong giao thức chiến đấu Souls-like (Elden Ring / Nioh). "
            "Cảnh báo máu/thể lực cực ngắn (dưới 12 từ), gợi ý nhịp né đòn (dodge roll / Ki Pulse) và điểm yếu Boss tức thì."
        ),
        "knowledge_pack": {
            "malenia": "Yếu với Frostbite & Bleed. Khi bay lên chuẩn bị Waterfowl Dance: chạy xa đợt 1, lăn vào trong đợt 2, lăn ngược đợt 3.",
            "radahn": "Ưu tiên khiên kháng Holy/Magic ở Phase 2, giữ khoảng cách sát chân để tránh chuỗi chém quang năng.",
            "nioh_ki": "Nhớ bấm R1 đúng nhịp Ki Pulse để hồi thể lực và thanh tẩy Yokai Realm ngay lập tức!",
        },
        "reflex_rules": [
            {
                "id": "rx_hp_critical",
                "trigger_type": "vision",
                "target_class": "player_hp_low",
                "min_conf": 0.45,
                "response": "Máu báo động đỏ! Lùi nhịp và hồi bình ngay!",
                "emotion": "alert",
                "cooldown_sec": 15,
            },
            {
                "id": "rx_boss_engage",
                "trigger_type": "vision",
                "target_class": "boss_health_bar",
                "min_conf": 0.50,
                "response": "Phát hiện thanh máu Boss! Giữ thể lực, quan sát nhịp ra đòn đầu tiên.",
                "emotion": "alert",
                "cooldown_sec": 35,
            },
            {
                "id": "rx_malenia_tip",
                "trigger_type": "keyword",
                "patterns": ["malenia", "waterfowl", "múa kiếm"],
                "response": "Khắc chế Malenia: Dùng băng/chảy máu. Khi cô ta nhảy lên không trung: chạy lùi nhịp 1, roll xuyên qua nhịp 2!",
                "emotion": "speaking",
                "cooldown_sec": 5,
            },
            {
                "id": "rx_nioh_tip",
                "trigger_type": "keyword",
                "patterns": ["nioh", "ki pulse", "hồi ki", "burst counter"],
                "response": "Mẹo Nioh: Luôn Ki Pulse sau mỗi chuỗi đòn và canh đòn đỏ để Burst Counter phá thanh Ki của Yokai!",
                "emotion": "happy",
                "cooldown_sec": 5,
            },
        ],
    },
    {
        "id": "valorant_tactical",
        "name": "Valorant / Tactical FPS Protocol",
        "category": "game",
        "process_matches": ["valorant-win64-shipping.exe", "valorant.exe", "cs2.exe"],
        "title_keywords": ["valorant", "counter-strike"],
        "yolo_classes": ["spike_planted_icon", "low_ammo_warning", "low_hp_hud", "minimap_ping", "buy_phase_menu"],
        "yolo_weights": "yolo11n_fps.pt",
        "system_prompt_addon": (
            "Đang trong giao thức FPS chiến thuật (Valorant/CS2). "
            "Báo callout cực gọn: thời gian Spike (45s), quản lý kinh tế (Eco/Full Buy) và kiểm soát tâm ngắm."
        ),
        "knowledge_pack": {
            "spike_timer": "Spike nổ sau 45s. Gỡ mất 7s (nửa vạch là 3.5s). Tiếng bíp tăng tốc gấp đôi khi còn 10s cuối.",
            "economy": "Thua 1 round: +1900, thua 2: +2400, thua 3+: +2900. Đảm bảo còn ít nhất 3900 cho round sau để Full Buy.",
        },
        "reflex_rules": [
            {
                "id": "rx_spike_planted",
                "trigger_type": "vision",
                "target_class": "spike_planted_icon",
                "min_conf": 0.45,
                "response": "Spike đã đặt! Đếm ngược 45 giây, giữ góc hoặc retake theo đội!",
                "emotion": "alert",
                "cooldown_sec": 30,
            },
            {
                "id": "rx_eco_query",
                "trigger_type": "keyword",
                "patterns": ["eco", "mua súng", "tiền", "full buy", "spike"],
                "response": "Chuẩn kinh tế: Giữ tối thiểu 3900 Creds cho round kế tiếp để mua Vandal/Phantom + Giáp dày. Spike nổ sau 45s, gỡ mất 7s.",
                "emotion": "speaking",
                "cooldown_sec": 5,
            },
        ],
    },
    {
        "id": "league_of_legends",
        "name": "League of Legends / MOBA Macro Protocol",
        "category": "game",
        "process_matches": ["league of legends.exe", "leagueclientux.exe", "dota2.exe"],
        "title_keywords": ["league of legends", "dota 2", "lmht"],
        "yolo_classes": ["minimap_jungler", "dragon_timer", "baron_timer", "low_mana_bar", "player_hp_low"],
        "yolo_weights": "yolo11n_moba.pt",
        "system_prompt_addon": (
            "Đang trong giao thức MOBA (LMHT/Dota 2). "
            "Nhắc kiểm soát tầm nhìn, thời gian Rồng/Baron và vị trí rừng đối phương cực nhanh."
        ),
        "knowledge_pack": {
            "objectives": "Sâu Hư Không xuất hiện phút 6:00, Rồng đầu 5:00 (hồi sau 5 phút), Sứ Giả 14:00, Baron 20:00.",
            "wave_management": "Đóng băng lính (Freeze) khi cần giữ khoảng cách 4 lính đánh xa của địch ngoài tầm trụ.",
        },
        "reflex_rules": [
            {
                "id": "rx_moba_timer",
                "trigger_type": "keyword",
                "patterns": ["rồng", "baron", "sâu hư không", "thời gian mục tiêu"],
                "response": "Mốc mục tiêu: Rồng 5:00 (hồi 5p), Sâu Hư Không 6:00, Sứ Giả 14:00, Baron 20:00. Cắm mắt trước 45 giây!",
                "emotion": "speaking",
                "cooldown_sec": 5,
            }
        ],
    },
    {
        "id": "vscode_developer",
        "name": "Developer IDE & Code Copilot Protocol",
        "category": "app",
        "process_matches": ["code.exe", "cursor.exe", "pycharm64.exe", "devenv.exe", "windowsterminal.exe"],
        "title_keywords": ["visual studio code", "pycharm", "terminal", ".py", ".js", ".ts", ".rs"],
        "yolo_classes": ["terminal_traceback", "syntax_error_squiggly", "build_failed_banner", "debugger_paused"],
        "yolo_weights": "yolo11n.pt",
        "system_prompt_addon": (
            "Đang trong giao thức Lập trình & Kỹ thuật phần mềm. "
            "Trả lời trực diện vào giải pháp code, độ phức tạp thuật toán và cách sửa lỗi nhanh nhất."
        ),
        "knowledge_pack": {
            "debugging": "Đọc dòng cuối cùng của Traceback trước để xác định loại Exception, sau đó dò ngược lên file thuộc project.",
        },
        "reflex_rules": [
            {
                "id": "rx_code_error",
                "trigger_type": "vision",
                "target_class": "terminal_traceback",
                "min_conf": 0.50,
                "response": "Phát hiện Traceback lỗi trên màn hình! Cần mình phân tích nguyên nhân gốc ngay không?",
                "emotion": "thinking",
                "cooldown_sec": 25,
            }
        ],
    },
]


class ReflexProtocolEngine:
    """
    Permanent High-Speed Brain Engine.
    - Stores modular protocol cartridges per Game / App / Topic on disk.
    - Automatically switches active cartridge based on foreground process/window.
    - Executes sub-15ms instant reflex responses for visual detections & voice/text keywords.
    - Allows LLM + Tools + YOLO-World to synthesize new permanent protocols at runtime.
    """

    def __init__(self):
        self.protocols: Dict[str, Dict[str, Any]] = {}
        self.active_protocol_id: str = "global_default"
        self.locked_protocol_id: Optional[str] = None  # If user pins a protocol manually
        self._cooldown_tracker: Dict[str, float] = {}
        self._ensure_defaults()
        self.reload_all()

    def _ensure_defaults(self):
        for proto in DEFAULT_PROTOCOLS:
            path = PROTOCOLS_DIR / f"{proto['id']}.json"
            if not path.exists():
                path.write_text(json.dumps(proto, indent=2, ensure_ascii=False), encoding="utf-8")

    def reload_all(self):
        self.protocols.clear()
        for file in sorted(PROTOCOLS_DIR.glob("*.json")):
            try:
                data = json.loads(file.read_text(encoding="utf-8"))
                if "id" in data:
                    self.protocols[data["id"]] = data
            except Exception:
                continue
        if "global_default" not in self.protocols and DEFAULT_PROTOCOLS:
            self.protocols["global_default"] = DEFAULT_PROTOCOLS[0]

    def get_active_protocol(self) -> Dict[str, Any]:
        return self.protocols.get(self.active_protocol_id) or self.protocols["global_default"]

    def list_protocols(self) -> List[Dict[str, Any]]:
        return list(self.protocols.values())

    def set_manual_protocol(self, protocol_id: Optional[str]) -> Dict[str, Any]:
        """Set or unlock (None/'auto') a manually pinned protocol."""
        if not protocol_id or protocol_id == "auto":
            self.locked_protocol_id = None
            return self.get_active_protocol()
        if protocol_id in self.protocols:
            self.locked_protocol_id = protocol_id
            self.active_protocol_id = protocol_id
        return self.get_active_protocol()

    def match_window_to_protocol(self, process_name: str, window_title: str) -> Tuple[bool, Dict[str, Any]]:
        """
        100% Autonomous Context Loader:
        Matches active OS process/title to the right Protocol Cartridge.
        If a new app/game is opened for the first time, automatically synthesizes
        and persists a dedicated Protocol Cartridge for it without manual user action.
        """
        proc_lower = (process_name or "").lower().strip()
        title_lower = (window_title or "").lower().strip()

        matched_id = None
        for pid, proto in self.protocols.items():
            if pid == "global_default":
                continue
            proc_list = [p.lower() for p in proto.get("process_matches", [])]
            if any(p == proc_lower or (p and p in proc_lower) for p in proc_list):
                matched_id = pid
                break
            kw_list = [k.lower() for k in proto.get("title_keywords", [])]
            if any(k and k in title_lower for k in kw_list):
                matched_id = pid
                break

        # Auto-generate a permanent protocol cartridge for any newly encountered app/game
        generic_procs = {
            "",
            "desktop",
            "explorer.exe",
            "unknown.exe",
            "searchhost.exe",
            "shellexperiencehost.exe",
            "applicationframehost.exe",
        }
        if matched_id is None and proc_lower not in generic_procs:
            app_stem = proc_lower.replace(".exe", "").strip()
            clean_id = re.sub(r"[^a-z0-9_]+", "_", app_stem).strip("_")
            if clean_id and len(clean_id) >= 2:
                display_name = window_title.split("-")[-1].strip() if "-" in window_title else app_stem.title()
                auto_proto = {
                    "id": f"auto_{clean_id}",
                    "name": display_name[:32] or app_stem.title(),
                    "category": "auto",
                    "process_matches": [proc_lower],
                    "title_keywords": [app_stem],
                    "yolo_classes": ["hud_element", "health_bar", "dialog_box", "error_alert"],
                    "yolo_weights": "yolo11n.pt",
                    "system_prompt_addon": f"Tự động tối ưu phản xạ cho '{display_name}' ({proc_lower}).",
                    "knowledge_pack": {
                        "context": f"Đang đồng bộ thời gian thực với {display_name}."
                    },
                    "reflex_rules": [
                        {
                            "id": f"rx_{clean_id}_alert",
                            "trigger_type": "vision",
                            "target_class": "player_hp_low",
                            "min_conf": 0.48,
                            "response": "Chú ý trạng thái trên màn hình!",
                            "emotion": "alert",
                            "cooldown_sec": 20,
                        }
                    ],
                }
                saved = self.save_protocol(auto_proto)
                matched_id = saved["id"]

        if matched_id is None:
            matched_id = "global_default"

        changed = matched_id != self.active_protocol_id
        self.active_protocol_id = matched_id
        return changed, self.get_active_protocol()

    def evaluate_text_reflex(self, user_text: str) -> Optional[Dict[str, Any]]:
        """
        Sub-10ms Reflex Lookup: Checks active protocol (and global fallback)
        for instant keyword/knowledge matches before invoking heavy LLM.
        """
        text_lower = user_text.strip().lower()
        if not text_lower:
            return None

        now = time.time()
        proto = self.get_active_protocol()
        candidates = [proto]
        if proto["id"] != "global_default" and "global_default" in self.protocols:
            candidates.append(self.protocols["global_default"])

        for p in candidates:
            for rule in p.get("reflex_rules", []):
                if rule.get("trigger_type") != "keyword":
                    continue
                rule_key = f"{p['id']}:{rule.get('id', 'rx')}"
                cooldown = float(rule.get("cooldown_sec", 2.0))
                if now - self._cooldown_tracker.get(rule_key, 0) < cooldown:
                    continue

                patterns = [pat.lower() for pat in rule.get("patterns", [])]
                if any(pat in text_lower for pat in patterns):
                    self._cooldown_tracker[rule_key] = now
                    return {
                        "reflex_id": rule.get("id", "rx_kw"),
                        "protocol_id": p["id"],
                        "protocol_name": p["name"],
                        "response": rule["response"],
                        "emotion": rule.get("emotion", "speaking"),
                        "mode": "reflex_instant",
                    }

            # Also check knowledge_pack exact topic match for fast queries
            kpack = p.get("knowledge_pack", {})
            for topic, content in kpack.items():
                if topic.lower() in text_lower and len(text_lower) <= 45:
                    return {
                        "reflex_id": f"kp_{topic}",
                        "protocol_id": p["id"],
                        "protocol_name": p["name"],
                        "response": content,
                        "emotion": "speaking",
                        "mode": "reflex_knowledge",
                    }

        return None

    def evaluate_vision_reflex(self, detections: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """
        Sub-5ms Vision Reflex Lookup: Matches YOLO11n screen detections
        against the active protocol's visual reflex rules.
        """
        if not detections:
            return None

        now = time.time()
        proto = self.get_active_protocol()
        rules = [r for r in proto.get("reflex_rules", []) if r.get("trigger_type") == "vision"]

        for det in detections:
            cls_name = det.get("class_name", "")
            conf = float(det.get("confidence", 0.0))
            for rule in rules:
                if rule.get("target_class") == cls_name and conf >= float(rule.get("min_conf", 0.4)):
                    rule_key = f"{proto['id']}:{rule.get('id', cls_name)}"
                    cooldown = float(rule.get("cooldown_sec", 15.0))
                    if now - self._cooldown_tracker.get(rule_key, 0) >= cooldown:
                        self._cooldown_tracker[rule_key] = now
                        return {
                            "reflex_id": rule.get("id", cls_name),
                            "protocol_id": proto["id"],
                            "protocol_name": proto["name"],
                            "response": rule["response"],
                            "emotion": rule.get("emotion", "alert"),
                            "detection": det,
                            "mode": "vision_reflex",
                        }
        return None

    def save_protocol(self, proto_data: Dict[str, Any]) -> Dict[str, Any]:
        """Persists a new or updated Protocol Cartridge to disk permanently."""
        raw_id = proto_data.get("id") or proto_data.get("name", "custom_protocol")
        clean_id = re.sub(r"[^a-z0-9_]+", "_", raw_id.lower()).strip("_") or f"proto_{int(time.time())}"
        proto_data["id"] = clean_id
        proto_data.setdefault("name", clean_id.replace("_", " ").title())
        proto_data.setdefault("category", "custom")
        proto_data.setdefault("process_matches", [])
        proto_data.setdefault("title_keywords", [])
        proto_data.setdefault("yolo_classes", ["hud_element", "health_bar", "dialog_box"])
        proto_data.setdefault("yolo_weights", "yolo11n.pt")
        proto_data.setdefault("system_prompt_addon", f"Giao thức chuyên biệt cho {proto_data['name']}.")
        proto_data.setdefault("knowledge_pack", {})
        proto_data.setdefault("reflex_rules", [])
        proto_data["updated_at"] = int(time.time())

        file_path = PROTOCOLS_DIR / f"{clean_id}.json"
        file_path.write_text(json.dumps(proto_data, indent=2, ensure_ascii=False), encoding="utf-8")
        self.protocols[clean_id] = proto_data
        return proto_data

    def delete_protocol(self, protocol_id: str) -> bool:
        if protocol_id == "global_default":
            return False
        file_path = PROTOCOLS_DIR / f"{protocol_id}.json"
        if file_path.exists():
            file_path.unlink()
        self.protocols.pop(protocol_id, None)
        if self.active_protocol_id == protocol_id:
            self.active_protocol_id = "global_default"
        return True


protocol_engine = ReflexProtocolEngine()
