"""
Xiaozhi Opus Audio Codec (ESP32-S3 I2S <-> Opus 60ms frames)
============================================================
`xiaozhi.me` only accepts `listen: detect` for short wake words, so free-form user
requests must be streamed as real Opus microphone audio exactly like a hardware
ESP32-S3 (`listen: start` -> binary Opus frames -> `listen: stop`).

This module provides:
  - `text_to_mic_opus_frames()`: turns user text into 16kHz mono speech and encodes it
    into 60ms Opus packets (the emulated ES8311 dual-mic input).
  - `pcm16_to_opus_frames()`: encodes raw 16kHz PCM16 microphone audio.
  - `OpusStreamDecoder`: decodes Xiaozhi's 24kHz Opus TTS packets back into WAV so the
    voice configured on `xiaozhi.me/console/agents` is played unchanged.
"""

from __future__ import annotations

import io
import wave
from typing import List, Optional

import numpy as np

try:
    import av  # PyAV bundles libopus

    HAS_PYAV = True
except Exception:  # pragma: no cover
    av = None
    HAS_PYAV = False

MIC_SAMPLE_RATE = 16000
FRAME_DURATION_MS = 60


def pcm16_to_wav_bytes(pcm: np.ndarray, sample_rate: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm.astype(np.int16).tobytes())
    return buf.getvalue()


def decode_audio_file_to_pcm16(data: bytes, target_rate: int = MIC_SAMPLE_RATE) -> np.ndarray:
    """Decodes any compressed audio (mp3/wav/ogg) into mono PCM16 at `target_rate`."""
    if not HAS_PYAV or not data:
        return np.zeros(0, dtype=np.int16)
    chunks: List[np.ndarray] = []
    with av.open(io.BytesIO(data)) as container:
        stream = next(s for s in container.streams if s.type == "audio")
        resampler = av.AudioResampler(format="s16", layout="mono", rate=target_rate)
        for frame in container.decode(stream):
            for rf in resampler.resample(frame):
                chunks.append(rf.to_ndarray().reshape(-1))
        for rf in resampler.resample(None):
            chunks.append(rf.to_ndarray().reshape(-1))
    return np.concatenate(chunks).astype(np.int16) if chunks else np.zeros(0, dtype=np.int16)


def pcm16_to_opus_frames(pcm: np.ndarray, sample_rate: int = MIC_SAMPLE_RATE) -> List[bytes]:
    """Encodes mono PCM16 into 60ms Opus packets (ESP32-S3 `audio_params` compatible)."""
    if not HAS_PYAV or pcm.size == 0:
        return []
    enc = av.CodecContext.create("libopus", "w")
    enc.sample_rate = sample_rate
    enc.layout = "mono"
    enc.format = "s16"
    enc.bit_rate = 32000
    enc.options = {"frame_duration": str(FRAME_DURATION_MS), "application": "voip"}
    enc.open()

    frame_samples = sample_rate * FRAME_DURATION_MS // 1000
    pad = (-pcm.size) % frame_samples
    if pad:
        pcm = np.concatenate([pcm, np.zeros(pad, dtype=np.int16)])

    packets: List[bytes] = []
    pts = 0
    for i in range(0, pcm.size, frame_samples):
        chunk = np.ascontiguousarray(pcm[i : i + frame_samples].reshape(1, -1), dtype=np.int16)
        frame = av.AudioFrame.from_ndarray(chunk, format="s16", layout="mono")
        frame.sample_rate = sample_rate
        frame.pts = pts
        pts += frame_samples
        for pkt in enc.encode(frame):
            packets.append(bytes(pkt))
    for pkt in enc.encode(None):
        packets.append(bytes(pkt))
    return packets


async def text_to_mic_opus_frames(text: str, voice: str = "vi-VN-HoaiMyNeural") -> List[bytes]:
    """Speaks `text` into the emulated microphone and returns 60ms Opus packets."""
    import edge_tts

    mp3 = bytearray()
    communicate = edge_tts.Communicate(text, voice)
    async for chunk in communicate.stream():
        if chunk.get("type") == "audio":
            mp3.extend(chunk["data"])
    pcm = decode_audio_file_to_pcm16(bytes(mp3), MIC_SAMPLE_RATE)
    # Add ~300ms leading/trailing silence so server-side VAD frames the utterance cleanly
    silence = np.zeros(int(MIC_SAMPLE_RATE * 0.3), dtype=np.int16)
    return pcm16_to_opus_frames(np.concatenate([silence, pcm, silence]), MIC_SAMPLE_RATE)


class OpusStreamDecoder:
    """Stateful decoder for Xiaozhi server Opus TTS packets."""

    def __init__(self, sample_rate: int = 24000) -> None:
        self.sample_rate = sample_rate
        self._dec = None
        if HAS_PYAV:
            self._dec = av.CodecContext.create("libopus", "r")
            self._dec.sample_rate = sample_rate
            self._dec.layout = "mono"
            self._dec.open()

    def decode(self, packet: bytes) -> np.ndarray:
        if self._dec is None or not packet:
            return np.zeros(0, dtype=np.int16)
        out: List[np.ndarray] = []
        try:
            for frame in self._dec.decode(av.Packet(packet)):
                arr = frame.to_ndarray()
                if arr.ndim > 1:
                    arr = arr[0] if frame.format.is_planar else arr.reshape(-1)
                if arr.dtype.kind == "f":
                    arr = np.clip(arr * 32767.0, -32768, 32767)
                out.append(arr.astype(np.int16))
        except Exception:
            return np.zeros(0, dtype=np.int16)
        return np.concatenate(out) if out else np.zeros(0, dtype=np.int16)

    def decode_many_to_wav(self, packets: List[bytes]) -> Optional[bytes]:
        pcm_parts = [self.decode(p) for p in packets]
        pcm_parts = [p for p in pcm_parts if p.size]
        if not pcm_parts:
            return None
        return pcm16_to_wav_bytes(np.concatenate(pcm_parts), self.sample_rate)
