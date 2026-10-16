import json
import os
import sys
import shutil
from pathlib import Path
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field

def _resolve_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent.parent

BASE_DIR = _resolve_base_dir()
CONFIG_PATH = BASE_DIR / "config.json"


class LLMProviderConfig(BaseModel):
    active_provider: str = "mochi_core"  # mochi_core (Free), gemini, openai, deepseek, groq, ollama, lmstudio
    model_name: str = "mochi-smart-v4 (Free)"
    api_key: str = ""
    base_url: str = "local:mochi_firmware"
    temperature: float = 0.4
    max_tokens: int = 350
    providers: Dict[str, Dict[str, Any]] = Field(
        default_factory=lambda: {
            "mochi_core": {
                "name": "Mochi Core (Firmware Gốc • Free)",
                "base_url": "local:mochi_firmware",
                "default_model": "mochi-smart-v4 (Free)",
                "models": ["mochi-smart-v4 (Free)", "mochi-fast-v4 (Free)", "mochi-waifu-v4 (Free)"],
            },
            "ollama": {
                "name": "Ollama (Local)",
                "base_url": "http://localhost:11434/v1",
                "default_model": "qwen2.5:7b",
                "models": ["qwen2.5:7b", "llama3.2:3b", "deepseek-r1:8b", "gemma2:9b"],
            },
            "lmstudio": {
                "name": "LM Studio / vLLM (Local)",
                "base_url": "http://localhost:1234/v1",
                "default_model": "local-model",
                "models": ["local-model", "qwen2.5-7b-instruct", "llama-3.2-3b-instruct"],
            },
            "openai": {
                "name": "OpenAI",
                "base_url": "https://api.openai.com/v1",
                "default_model": "gpt-4o-mini",
                "models": ["gpt-4o-mini", "gpt-4o", "o3-mini"],
            },
            "gemini": {
                "name": "Google Gemini",
                "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
                "default_model": "gemini-2.5-flash",
                "models": ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.0-flash"],
            },
            "deepseek": {
                "name": "DeepSeek",
                "base_url": "https://api.deepseek.com/v1",
                "default_model": "deepseek-chat",
                "models": ["deepseek-chat", "deepseek-reasoner"],
            },
            "groq": {
                "name": "Groq (Ultra-Fast)",
                "base_url": "https://api.groq.com/openai/v1",
                "default_model": "llama-3.3-70b-versatile",
                "models": ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "qwen-2.5-32b"],
            },
        }
    )


class VoiceConfig(BaseModel):
    engine: str = "omnivoice"  # omnivoice, edge_tts, browser
    voice_preset: str = "omnivoice:neito_vi_female"
    omnivoice_url: str = "http://localhost:8020/v1/audio/speech"
    omnivoice_voice: str = "neito_vi_female"
    edge_voice: str = "vi-VN-HoaiMyNeural"
    speed: float = 1.12
    mic_enabled: bool = True
    speaker_enabled: bool = True
    ear_mode: str = "auto_vad"  # auto_vad, push_to_talk, wake_word
    wake_word: str = "neito"
    barge_in: bool = True
    vad_threshold: float = 0.45


class VisionConfig(BaseModel):
    enabled: bool = True
    detector_model: str = "yolo11n.pt"
    trainer_model: str = "yolov8s-worldv2.pt"
    fps_mode: str = "eco"  # eco (1 FPS), balanced (4 FPS), combat (10 FPS)
    confidence_threshold: float = 0.38
    use_half_precision: bool = True
    capture_active_window_only: bool = True
    auto_reflex_on_detection: bool = True


class MascotConfig(BaseModel):
    scale: float = 1.0
    opacity: float = 0.96
    theme_color: str = "#00f2fe"
    always_on_top: bool = True
    gaming_eco_mode: bool = True


class AppConfig(BaseModel):
    agent_name: str = "Neito"
    system_persona: str = (
        "Bạn là Neito, một sinh vật AI sống động trên màn hình desktop. "
        "Phong cách: Nhanh - Mạnh - Văn phong tinh gọn, thông minh, sắc bén, "
        "trả lời cực kỳ súc tích (1-2 câu ngắn) để đọc/nói realtime khi người dùng đang chơi game hoặc làm việc."
    )
    llm: LLMProviderConfig = Field(default_factory=LLMProviderConfig)
    voice: VoiceConfig = Field(default_factory=VoiceConfig)
    vision: VisionConfig = Field(default_factory=VisionConfig)
    mascot: MascotConfig = Field(default_factory=MascotConfig)


class ConfigManager:
    def __init__(self, path: Path = CONFIG_PATH):
        self.path = path
        self.config = self._load()

    def _load(self) -> AppConfig:
        if not self.path.exists() and getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
            bundled = Path(sys._MEIPASS) / "config.json"
            if bundled.exists():
                try:
                    shutil.copyfile(bundled, self.path)
                except Exception:
                    pass
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                return AppConfig(**data)
            except Exception:
                pass
        cfg = AppConfig()
        try:
            self.save(cfg)
        except Exception:
            pass
        return cfg

    def save(self, cfg: Optional[AppConfig] = None) -> AppConfig:
        if cfg is not None:
            self.config = cfg
        self.path.write_text(
            json.dumps(self.config.model_dump(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return self.config

    def update_partial(self, patch: Dict[str, Any]) -> AppConfig:
        current = self.config.model_dump()
        for key, value in patch.items():
            if isinstance(value, dict) and key in current and isinstance(current[key], dict):
                current[key].update(value)
            else:
                current[key] = value
        self.config = AppConfig(**current)
        return self.save()


config_manager = ConfigManager()
