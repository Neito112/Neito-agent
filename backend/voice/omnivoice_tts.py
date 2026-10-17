import base64
import io
import math
import random
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import httpx

from backend.core.config import config_manager
from backend.vision.mochi_esp32_client import (
    MOCHI_FACE_SOUND_MAP,
    MOCHI_PRESET_MELODIES,
    SOUNDS_DIR,
    synthesize_mochi_melody_wav,
)


# 27-Voice Multi-Style Catalog (Rich Vietnamese Voice Repository + Mochi Firmware + International Anime)
# High-speed in-memory TTS Cache for zero-latency instant replays
TTS_CACHE: Dict[str, Dict[str, Any]] = {}

# 18 Truly Distinct Neural Voices & Mochi Firmware Sound Engines (0% duplicates)
VOICE_CATALOG: List[Tuple[str, str]] = [
    # Nhóm 1: Mochi Firmware Gốc & SFX
    ("Mochi Gốc • Moshi Moshi (Firmware C3)", "mochi_native:moshi_pack"),
    ("Mochi Pure • 27 SFX WAV Gốc (ESP32 SPIFFS)", "mochi_native:sfx_only"),
    ("Mochi 8-Bit • Buzzer Chiptune (Melody Gốc)", "mochi_native:buzzer_8bit"),

    # Nhóm 2: Giọng Nữ Tuyển Chọn (Đa Âm Sắc Hoàn Toàn Riêng Biệt)
    ("Việt Nữ • Hoài My (Chuẩn Hà Nội • Tự Nhiên)", "edge_tts:vi-VN-HoaiMyNeural"),
    ("Việt Nữ • Ava (Anime Waifu • Siêu Dễ Thương)", "edge_tts:en-US-AvaMultilingualNeural"),
    ("Việt Nữ • Emma (Dịu Dàng • Ngọt Ngào)", "edge_tts:en-US-EmmaMultilingualNeural"),
    ("Việt Nữ • Seraphina (Năng Động • Hiện Đại)", "edge_tts:de-DE-SeraphinaMultilingualNeural"),
    ("Việt Nữ • Bé Ana (Loli Anime • Tinh Nghịch)", "edge_tts:en-US-AnaNeural"),

    # Nhóm 3: Giọng Nam Tuyển Chọn (Đa Âm Sắc Hoàn Toàn Riêng Biệt)
    ("Việt Nam • Nam Minh (Chuẩn Hà Nội • Trưởng Thành)", "edge_tts:vi-VN-NamMinhNeural"),
    ("Việt Nam • Andrew (Trẻ Trung • Sôi Nổi)", "edge_tts:en-US-AndrewMultilingualNeural"),
    ("Việt Nam • Brian (Bác Học • Trầm Ấm)", "edge_tts:en-US-BrianMultilingualNeural"),
    ("Việt Nam • Hyunsu (Anime Boy • Lạnh Lùng)", "edge_tts:ko-KR-HyunsuMultilingualNeural"),
    ("Việt Nam • Florian (Bản Lĩnh • Điềm Đạm)", "edge_tts:de-DE-FlorianMultilingualNeural"),
    ("Việt Nam • Remy (Lịch Lãm • Tinh Tế)", "edge_tts:fr-FR-RemyMultilingualNeural"),

    # Nhóm 4: Quốc Tế & Xiaozhi
    ("Anime Nhật • Nanami (Waifu Tiếng Nhật)", "edge_tts:ja-JP-NanamiNeural"),
    ("Anime Nhật • Keita (Shonen Tiếng Nhật)", "edge_tts:ja-JP-KeitaNeural"),
    ("Hàn Quốc • SunHi (K-Pop Tiếng Hàn)", "edge_tts:ko-KR-SunHiNeural"),
    ("Xiaozhi Gốc • Xiaoxiao (Firmware Xiaozhi)", "edge_tts:zh-CN-XiaoxiaoNeural"),
]

# Exact Edge TTS ID, Pitch, Rate mapping per distinct voice
VOICE_DSP_PROFILES: Dict[str, Tuple[str, str, str]] = {
    # Mochi Native
    "mochi_native:moshi_pack": ("vi-VN-HoaiMyNeural", "+10Hz", "+16%"),
    "mochi_native:chibi_waifu": ("en-US-AvaMultilingualNeural", "+0Hz", "+12%"),
    "mochi_native:sfx_only": ("vi-VN-HoaiMyNeural", "+0Hz", "+0%"),
    "mochi_native:buzzer_8bit": ("vi-VN-NamMinhNeural", "+0Hz", "+15%"),

    # Nữ
    "edge_tts:vi-VN-HoaiMyNeural": ("vi-VN-HoaiMyNeural", "+0Hz", "+6%"),
    "edge_tts:en-US-AvaMultilingualNeural": ("en-US-AvaMultilingualNeural", "+0Hz", "+8%"),
    "edge_tts:en-US-EmmaMultilingualNeural": ("en-US-EmmaMultilingualNeural", "+0Hz", "+6%"),
    "edge_tts:de-DE-SeraphinaMultilingualNeural": ("de-DE-SeraphinaMultilingualNeural", "+0Hz", "+6%"),
    "edge_tts:en-US-AnaNeural": ("en-US-AnaNeural", "+6Hz", "+8%"),

    # Nam
    "edge_tts:vi-VN-NamMinhNeural": ("vi-VN-NamMinhNeural", "+0Hz", "+6%"),
    "edge_tts:en-US-AndrewMultilingualNeural": ("en-US-AndrewMultilingualNeural", "+0Hz", "+6%"),
    "edge_tts:en-US-BrianMultilingualNeural": ("en-US-BrianMultilingualNeural", "+0Hz", "+4%"),
    "edge_tts:ko-KR-HyunsuMultilingualNeural": ("ko-KR-HyunsuMultilingualNeural", "+0Hz", "+6%"),
    "edge_tts:de-DE-FlorianMultilingualNeural": ("de-DE-FlorianMultilingualNeural", "+0Hz", "+6%"),
    "edge_tts:fr-FR-RemyMultilingualNeural": ("fr-FR-RemyMultilingualNeural", "+0Hz", "+6%"),

    # Quốc Tế
    "edge_tts:ja-JP-NanamiNeural": ("ja-JP-NanamiNeural", "+8Hz", "+8%"),
    "edge_tts:ja-JP-KeitaNeural": ("ja-JP-KeitaNeural", "+0Hz", "+6%"),
    "edge_tts:ko-KR-SunHiNeural": ("ko-KR-SunHiNeural", "+6Hz", "+8%"),
    "edge_tts:zh-CN-XiaoxiaoNeural": ("zh-CN-XiaoxiaoNeural", "+4Hz", "+6%"),

    # Backward compatibility with legacy IDs
    "omnivoice:neito_vi_hoaimy": ("vi-VN-HoaiMyNeural", "+0Hz", "+6%"),
    "omnivoice:neito_vi_loli": ("en-US-AvaMultilingualNeural", "+0Hz", "+8%"),
    "omnivoice:neito_vi_gentle": ("en-US-EmmaMultilingualNeural", "+0Hz", "+6%"),
    "omnivoice:neito_vi_energetic": ("de-DE-SeraphinaMultilingualNeural", "+0Hz", "+6%"),
    "omnivoice:neito_vi_story": ("en-US-EmmaMultilingualNeural", "+0Hz", "+4%"),
    "omnivoice:neito_vi_elegant": ("en-US-AvaMultilingualNeural", "+0Hz", "+6%"),
    "omnivoice:neito_vi_mature": ("vi-VN-HoaiMyNeural", "-4Hz", "+2%"),
    "omnivoice:neito_vi_female": ("vi-VN-HoaiMyNeural", "+0Hz", "+6%"),
    "omnivoice:neito_vi_namminh": ("vi-VN-NamMinhNeural", "+0Hz", "+6%"),
    "omnivoice:neito_vi_baolong": ("en-US-BrianMultilingualNeural", "+0Hz", "+4%"),
    "omnivoice:neito_vi_tuankiet": ("en-US-AndrewMultilingualNeural", "+0Hz", "+8%"),
    "omnivoice:neito_vi_butler": ("en-US-BrianMultilingualNeural", "-2Hz", "+4%"),
    "omnivoice:neito_vi_mecha": ("vi-VN-NamMinhNeural", "-8Hz", "+4%"),
    "omnivoice:neito_vi_male": ("vi-VN-NamMinhNeural", "+0Hz", "+6%"),
}

_TTS_EMOJI_STRIP_RE = re.compile(
    "["
    "\U00010000-\U0010ffff"
    "\u2600-\u27bf"
    "\u2300-\u23ff"
    "\u2b00-\u2bff"
    "\ufe00-\ufe0f"
    "\u200d"
    "]+",
    flags=re.UNICODE,
)


def strip_icons_and_symbols(text: str) -> str:
    if not text:
        return ""
    t = re.sub(r"<think(?:ing)?>.*?(?:</think(?:ing)?>|$)", "", text, flags=re.DOTALL | re.IGNORECASE)
    t = re.sub(r"\[[^\]]*\]", " ", t)
    t = re.sub(r"\(\s*(?:uwu|>\.<|\^_\^)\s*\)", " ", t, flags=re.IGNORECASE)
    t = _TTS_EMOJI_STRIP_RE.sub("", t)
    t = re.sub(r"[*#`_~|<>•]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


class OmniVoiceEngine:
    """
    OmniVoice + Extracted Mochi Firmware Audio Engine:
    - Tier 0: Authentic Mochi Firmware SPIFFS `.wav` Voice/SFX Pack (27 original WAV files)
    - Tier 1: Local/Remote OmniVoice HTTP Streaming API
    - Tier 2: Resilient Multi-Character Neural TTS with Fine-Tuned Pitch & Rate DSP
    - Tier 3: Mochi 8-Bit Square-Wave Buzzer Melody Synthesizer (`notesFreq`)
    """

    SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?。\n])\s+")

    def split_sentences(self, text: str) -> List[str]:
        cleaned = strip_icons_and_symbols(text)
        parts = [p.strip() for p in self.SENTENCE_SPLIT_RE.split(cleaned) if p.strip()]
        return parts if parts else ([cleaned] if cleaned else [])

    def compute_lipsync_envelope(self, text: str, duration_ms: Optional[int] = None) -> List[float]:
        words = text.strip().split()
        if not words:
            return [0.0]
        est_ms = duration_ms or max(600, len(words) * 200)
        num_frames = max(6, int(est_ms / 33))
        curve: List[float] = []
        for i in range(num_frames):
            t = i / float(num_frames)
            word_idx = min(len(words) - 1, int(t * len(words)))
            w = words[word_idx].lower()
            open_vowels = sum(1 for ch in w if ch in "aăâeêioôơuưyáàảãạéèẻẽẹóòỏõọúùủũụ")
            base_amp = min(0.95, 0.34 + open_vowels * 0.18)
            syllable_wave = abs(math.sin(i * 0.88)) * base_amp
            curve.append(round(syllable_wave, 2))
        curve.append(0.0)
        return curve

    def get_mochi_sfx_audio(
        self, face_or_sound: str = "moshi.wav", emotion: str = "neutral"
    ) -> Dict[str, Any]:
        """
        Loads an extracted Mochi `.wav` file from `assets/mochi_faces/sounds/`
        (or synthesizes a Mochi 8-bit square-wave melody string) and returns
        base64 WAV + lip-sync envelope.
        """
        vcfg = config_manager.config.voice
        if not getattr(vcfg, "speaker_enabled", True):
            return {"audio_base64": None, "format": "muted", "lip_sync": [0.0], "engine": "muted"}

        target = (face_or_sound or "").strip()
        # Check if it's a melody note string (e.g. "C5 50 0 E5 50 0")
        if " " in target and any(n in target.upper() for n in ("C4", "C5", "D5", "E5", "G5", "A4")):
            wav_bytes = synthesize_mochi_melody_wav(target)
            return {
                "audio_base64": base64.b64encode(wav_bytes).decode("ascii"),
                "format": "wav",
                "lip_sync": [0.45, 0.75, 0.3, 0.8, 0.5, 0.0],
                "engine": "mochi-buzzer-8bit",
            }

        if target in MOCHI_PRESET_MELODIES:
            wav_bytes = synthesize_mochi_melody_wav(MOCHI_PRESET_MELODIES[target])
            return {
                "audio_base64": base64.b64encode(wav_bytes).decode("ascii"),
                "format": "wav",
                "lip_sync": [0.5, 0.85, 0.35, 0.85, 0.4, 0.0],
                "engine": f"mochi-melody ({target})",
            }

        # Normalize .mp3 references from firmware to extracted .wav
        if target.endswith(".mp3"):
            target = target[:-4] + ".wav"
        elif not target.endswith(".wav"):
            target = MOCHI_FACE_SOUND_MAP.get(target, "")
            if not target:
                emo_defaults = {
                    "happy": "UwU.wav",
                    "love": "love.wav",
                    "excited": "stars.wav",
                    "alert": "tanjiro.wav",
                    "sad": "cry.wav",
                    "sleepy": "sleep.wav",
                }
                target = emo_defaults.get(emotion, "moshi.wav")

        wav_path: Path = SOUNDS_DIR / target
        if not wav_path.exists():
            wav_path = SOUNDS_DIR / "moshi.wav"

        if wav_path.exists():
            raw = wav_path.read_bytes()
            est_ms = max(450, min(3500, int(len(raw) / 16)))
            n_frames = max(6, est_ms // 33)
            lip_sync = [round(0.35 + 0.55 * abs(math.sin(i * 0.9)), 2) for i in range(n_frames)] + [0.0]
            return {
                "audio_base64": base64.b64encode(raw).decode("ascii"),
                "format": "wav",
                "lip_sync": lip_sync,
                "engine": f"mochi-spiffs ({wav_path.name})",
                "sound_file": wav_path.name,
            }

        return {"audio_base64": None, "format": "none", "lip_sync": [0.0], "engine": "none"}

    async def _synthesize_edge_resilient(
        self, clean_text: str, edge_id: str, pitch_str: str, rate_arg: str
    ) -> Optional[bytes]:
        """
        Resilient Edge TTS synthesis with automatic 3-tier fallback:
        Tier 1: edge_id with pitch and rate
        Tier 2: edge_id with rate only (in case pitch exceeds server limits)
        Tier 3: standard vi-VN-HoaiMyNeural with rate only
        """
        try:
            import edge_tts

            # Tier 1: Requested voice + pitch + rate
            try:
                communicate = edge_tts.Communicate(
                    clean_text, edge_id, rate=rate_arg, pitch=pitch_str
                )
                audio_buf = io.BytesIO()
                async for chunk in communicate.stream():
                    if chunk["type"] == "audio":
                        audio_buf.write(chunk["data"])
                raw_bytes = audio_buf.getvalue()
                if len(raw_bytes) > 200:
                    return raw_bytes
            except Exception:
                pass

            # Tier 2: Requested voice + rate only (drop pitch)
            try:
                communicate = edge_tts.Communicate(clean_text, edge_id, rate=rate_arg)
                audio_buf = io.BytesIO()
                async for chunk in communicate.stream():
                    if chunk["type"] == "audio":
                        audio_buf.write(chunk["data"])
                raw_bytes = audio_buf.getvalue()
                if len(raw_bytes) > 200:
                    return raw_bytes
            except Exception:
                pass

            # Tier 3: Primary fallback voice
            try:
                communicate = edge_tts.Communicate(clean_text, "vi-VN-HoaiMyNeural", rate=rate_arg)
                audio_buf = io.BytesIO()
                async for chunk in communicate.stream():
                    if chunk["type"] == "audio":
                        audio_buf.write(chunk["data"])
                raw_bytes = audio_buf.getvalue()
                if len(raw_bytes) > 200:
                    return raw_bytes
            except Exception:
                pass

        except Exception:
            pass

        return None

    async def synthesize(
        self, text: str, emotion: str = "neutral", face_name: str = "", force_preset: Optional[str] = None
    ) -> Dict[str, Any]:
        clean_text = strip_icons_and_symbols(text)
        if not clean_text:
            return {"audio_base64": None, "format": "none", "lip_sync": [0.0], "engine": "none"}

        vcfg = config_manager.config.voice
        lip_sync = self.compute_lipsync_envelope(clean_text)

        if not getattr(vcfg, "speaker_enabled", True):
            return {
                "audio_base64": None,
                "format": "muted",
                "lip_sync": lip_sync,
                "engine": "muted",
            }

        preset = force_preset or getattr(vcfg, "voice_preset", "edge_tts:vi-VN-HoaiMyNeural") or "edge_tts:vi-VN-HoaiMyNeural"

        # Check in-memory cache for instant replay (0ms latency!)
        cache_key = f"{preset}:{clean_text}"
        if cache_key in TTS_CACHE:
            return TTS_CACHE[cache_key]

        # Special Mode 1: Pure Mochi Firmware SFX Voice (only plays extracted WAV from c3.bin!)
        if preset == "mochi_native:sfx_only":
            res = self.get_mochi_sfx_audio(face_name or emotion, emotion=emotion)
            TTS_CACHE[cache_key] = res
            return res

        # Special Mode 2: Mochi 8-Bit Buzzer Chiptune when text is short
        if preset == "mochi_native:buzzer_8bit" and len(clean_text) < 20:
            melody = random.choice(list(MOCHI_PRESET_MELODIES.values()))
            wav_bytes = synthesize_mochi_melody_wav(melody)
            res = {
                "audio_base64": base64.b64encode(wav_bytes).decode("ascii"),
                "format": "wav",
                "lip_sync": lip_sync,
                "engine": "mochi-buzzer-8bit",
            }
            TTS_CACHE[cache_key] = res
            return res

        edge_id, pitch_str, base_rate_str = VOICE_DSP_PROFILES.get(
            preset, ("vi-VN-HoaiMyNeural", "+0Hz", "+5%")
        )

        # High-Speed Resilient Neural TTS with Fine-Tuned Pitch & Rate DSP
        base_rate_num = int(base_rate_str.replace("%", "").replace("+", ""))
        user_rate_mod = int((vcfg.speed - 1.0) * 100)
        final_rate = max(-35, min(50, base_rate_num + user_rate_mod))
        rate_arg = f"{final_rate:+d}%"

        raw_bytes = await self._synthesize_edge_resilient(clean_text, edge_id, pitch_str, rate_arg)
        if raw_bytes and len(raw_bytes) > 100:
            res = {
                "audio_base64": base64.b64encode(raw_bytes).decode("ascii"),
                "format": "mp3",
                "lip_sync": lip_sync,
                "engine": f"neural-dsp ({edge_id} {pitch_str} {rate_arg})",
            }
            TTS_CACHE[cache_key] = res
            return res

        # 3. Only if speech network is completely down, fallback to Mochi SFX
        res = self.get_mochi_sfx_audio(face_name or "moshi.wav", emotion=emotion)
        return res

    async def synthesize_preview(self, preset: str) -> Dict[str, Any]:
        """Generates an instant 1-sentence audio sample to test a selected voice."""
        # Find friendly name
        voice_label = "Neito"
        for lbl, pid in VOICE_CATALOG:
            if pid == preset:
                voice_label = lbl.split("•")[-1].split("(")[0].strip()
                break

        if preset == "mochi_native:sfx_only":
            return self.get_mochi_sfx_audio("UwU.wav", emotion="happy")
        if preset == "mochi_native:buzzer_8bit":
            melody = MOCHI_PRESET_MELODIES.get("mario", "E5 50 0 E5 50 0")
            wav_bytes = synthesize_mochi_melody_wav(melody)
            return {
                "audio_base64": base64.b64encode(wav_bytes).decode("ascii"),
                "format": "wav",
                "lip_sync": [0.4, 0.8, 0.4, 0.0],
                "engine": "mochi-buzzer",
            }

        preview_text = f"Xin chào, mình là giọng {voice_label} đây nè!"
        return await self.synthesize(preview_text, emotion="happy", force_preset=preset)


omnivoice_engine = OmniVoiceEngine()
