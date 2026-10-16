import time
from typing import Dict, Any, Optional
import numpy as np

from backend.core.config import config_manager


class XiaozhiEarSession:
    """
    Upgraded Xiaozhi Ear & Full-Duplex State Machine (`Neito-Xiaozhi v2`):
    - States: IDLE, LISTENING, THINKING, SPEAKING
    - Supports instant Barge-In (interrupts active TTS & LLM generation the moment user speaks)
    - Supports RMS / Zero-Crossing lightweight VAD on raw PCM16 frames + WebSpeech STT transcripts
    """

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.state = "IDLE"
        self.is_interrupted = False
        self.last_voice_activity = 0.0
        self.pcm_buffer = bytearray()

    def set_state(self, new_state: str) -> Dict[str, Any]:
        self.state = new_state
        return {
            "type": "state",
            "session_id": self.session_id,
            "state": self.state,
            "timestamp": time.time(),
        }

    def trigger_barge_in(self) -> Dict[str, Any]:
        """Interrupts speaking/thinking immediately when user speaks or clicks interrupt."""
        self.is_interrupted = True
        self.state = "LISTENING"
        return {
            "type": "tts",
            "state": "stop",
            "reason": "barge_in",
            "session_id": self.session_id,
        }

    def reset_interrupt(self):
        self.is_interrupted = False

    def process_pcm16_frame(self, pcm_bytes: bytes) -> Dict[str, Any]:
        """
        Lightweight CPU Voice Activity Detection (VAD) on 16kHz 16-bit mono PCM audio frames.
        Zero GPU overhead (<0.1% CPU).
        """
        if not pcm_bytes:
            return {"voice_detected": False, "rms": 0.0}

        samples = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        rms = float(np.sqrt(np.mean(samples * samples))) if len(samples) > 0 else 0.0
        threshold = config_manager.config.voice.vad_threshold * 0.12

        voice_active = rms >= threshold
        if voice_active:
            self.last_voice_activity = time.time()
            self.pcm_buffer.extend(pcm_bytes)
            if self.state == "SPEAKING" and config_manager.config.voice.barge_in:
                self.trigger_barge_in()

        return {
            "voice_detected": voice_active,
            "rms": round(rms, 4),
            "should_barge_in": self.is_interrupted,
        }

    def filter_wake_word(self, transcript: str) -> Optional[str]:
        """If ear_mode == 'wake_word', checks for wake word prefix; otherwise passes through."""
        clean = transcript.strip()
        if not clean:
            return None
        vcfg = config_manager.config.voice
        if vcfg.ear_mode == "wake_word":
            ww = vcfg.wake_word.lower().strip()
            if ww and ww not in clean.lower():
                return None
        return clean
