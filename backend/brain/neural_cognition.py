import json
import math
import time
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
import numpy as np
from PIL import Image

import sys

def _resolve_synaptic_dir() -> Path:
    if getattr(sys, "frozen", False):
        exe_p = Path(sys.executable).resolve().parent / "backend" / "protocols" / "synapses"
        if exe_p.exists():
            return exe_p
        if hasattr(sys, "_MEIPASS"):
            bundle_p = Path(sys._MEIPASS) / "backend" / "protocols" / "synapses"
            if bundle_p.exists():
                return bundle_p
    return Path(__file__).resolve().parent.parent / "protocols" / "synapses"

SYNAPTIC_DIR = _resolve_synaptic_dir()
try:
    SYNAPTIC_DIR.mkdir(parents=True, exist_ok=True)
except Exception:
    pass


class VisualCognitiveNeuralNetwork:
    """
    Human-like Visual-Cognitive Neural Network (Predictive Coding + Hebbian Synaptic Graph):
    - Sensory Layer (V1/V4 Visual Cortex): Encodes screen frames + YOLO11n detections into a 32D
      spatio-temporal feature tensor (4x4 spatial attention grid + chromatic + motion delta + object channels).
    - Recurrent Associative Cortex (24D Liquid/Recurrent State): Maintains temporal working memory `h_t`
      across frames and computes Free-Energy Prediction Error (Visual Surprise `epsilon_t`).
    - Hebbian Synaptic Plasticity (Oja's Rule): Adapts synaptic matrices `W_vh`, `W_hh`, `W_pred`
      specific to each active application/game and saves them permanently to disk.
    - Affective & Executive Output: Produces continuous human-like affective states
      (Valence, Arousal, Focus, Curiosity, Surprise) and semantic visual intuition for the LLM/Reflex brain.
    """

    V_DIM = 32
    H_DIM = 24

    def __init__(self):
        self.rng = np.random.default_rng(42)
        self.active_app_key: str = "global"
        self.prev_v: np.ndarray = np.zeros(self.V_DIM, dtype=np.float32)
        self.h: np.ndarray = np.zeros(self.H_DIM, dtype=np.float32)

        # Synaptic weight matrices
        self.W_vh: np.ndarray = np.zeros((self.H_DIM, self.V_DIM), dtype=np.float32)
        self.W_hh: np.ndarray = np.zeros((self.H_DIM, self.H_DIM), dtype=np.float32)
        self.W_pred: np.ndarray = np.zeros((self.V_DIM, self.H_DIM), dtype=np.float32)
        self._init_or_load_synapses("global")

        # Continuous Human Affective Vector
        self.affect = {
            "valence": 0.65,    # 0 (negative/tense) -> 1 (positive/happy)
            "arousal": 0.35,    # 0 (calm/sleepy) -> 1 (intense/combat alert)
            "focus": 0.70,      # 0 (distracted) -> 1 (deep lock-in)
            "curiosity": 0.40,  # Driven by visual novelty / prediction error
            "surprise": 0.0,
        }
        self.visual_memory_trace: List[str] = []
        self._last_save_ts = time.time()

    def _init_or_load_synapses(self, app_key: str):
        clean_key = "".join(c if c.isalnum() else "_" for c in app_key.lower()).strip("_") or "global"
        self.active_app_key = clean_key
        weight_file = SYNAPTIC_DIR / f"{clean_key}.npz"

        if weight_file.exists():
            try:
                data = np.load(weight_file)
                self.W_vh = data["W_vh"].astype(np.float32)
                self.W_hh = data["W_hh"].astype(np.float32)
                self.W_pred = data["W_pred"].astype(np.float32)
                return
            except Exception:
                pass

        # Xavier/Glorot initialization for new app neural circuit
        self.W_vh = self.rng.normal(0, 1.0 / math.sqrt(self.V_DIM), (self.H_DIM, self.V_DIM)).astype(np.float32)
        self.W_hh = (np.eye(self.H_DIM, dtype=np.float32) * 0.6) + self.rng.normal(
            0, 0.08, (self.H_DIM, self.H_DIM)
        ).astype(np.float32)
        self.W_pred = self.rng.normal(0, 1.0 / math.sqrt(self.H_DIM), (self.V_DIM, self.H_DIM)).astype(np.float32)
        self._save_synapses()

    def _save_synapses(self):
        weight_file = SYNAPTIC_DIR / f"{self.active_app_key}.npz"
        try:
            np.savez_compressed(
                weight_file,
                W_vh=self.W_vh,
                W_hh=self.W_hh,
                W_pred=self.W_pred,
            )
            self._last_save_ts = time.time()
        except Exception:
            pass

    def switch_app_circuit(self, process_name: str):
        clean_key = "".join(c if c.isalnum() else "_" for c in process_name.lower()).strip("_") or "global"
        if clean_key != self.active_app_key:
            self._save_synapses()
            self._init_or_load_synapses(clean_key)
            self.h = np.zeros(self.H_DIM, dtype=np.float32)

    def encode_visual_cortex(self, img: Image.Image, detections: List[Dict[str, Any]]) -> Tuple[np.ndarray, Dict[str, float]]:
        """
        Extracts a 32D Visual Cortex sensory vector from the live screen frame:
        - [0..15]: 4x4 Spatial Luminance Attention Grid
        - [16..19]: 2x2 Spatial Edge/Contrast Energy (UI/Text vs Action density)
        - [20..22]: Normalized RGB Chromatic Balance
        - [23..26]: Corner HUD Activity (Top-Left, Top-Right, Bottom-Left, Bottom-Right)
        - [27..31]: YOLO11n Object Detection Semantic Channels (Alert, Boss/Enemy, UI, Person, Motion)
        """
        small = img.resize((64, 64), Image.Resampling.BILINEAR)
        arr = np.asarray(small, dtype=np.float32) / 255.0  # (64, 64, 3)
        gray = arr.mean(axis=2)

        v = np.zeros(self.V_DIM, dtype=np.float32)

        # 0..15: 4x4 spatial luminance grid
        grid_4x4 = gray.reshape(4, 16, 4, 16).mean(axis=(1, 3)).flatten()
        v[0:16] = grid_4x4

        # 16..19: 2x2 spatial gradient (edge energy)
        gx = np.abs(np.diff(gray, axis=1, prepend=gray[:, :1]))
        gy = np.abs(np.diff(gray, axis=0, prepend=gray[:1, :]))
        edges = np.clip((gx + gy) * 2.5, 0.0, 1.0)
        v[16:20] = edges.reshape(2, 32, 2, 32).mean(axis=(1, 3)).flatten()

        # 20..22: RGB mean
        v[20:23] = arr.mean(axis=(0, 1))

        # 23..26: Red/High-Alert intensity in 4 quadrants
        red_salience = np.clip((arr[:, :, 0] - arr[:, :, 1] * 0.6 - arr[:, :, 2] * 0.6) * 2.0, 0.0, 1.0)
        v[23:27] = red_salience.reshape(2, 32, 2, 32).mean(axis=(1, 3)).flatten()

        # 27..30: YOLO11n detection semantic channels
        for d in detections:
            cname = d.get("class_name", "").lower()
            conf = float(d.get("confidence", 0.5))
            if any(k in cname for k in ["low", "error", "alert", "died", "spike"]):
                v[27] = max(v[27], conf)
            elif any(k in cname for k in ["boss", "enemy", "jungler"]):
                v[28] = max(v[28], conf)
            elif any(k in cname for k in ["hud", "bar", "map", "dialog"]):
                v[29] = max(v[29], conf)
            else:
                v[30] = max(v[30], conf)

        # 31: Temporal motion delta against previous sensory state
        motion_delta = float(np.mean(np.abs(v[:20] - self.prev_v[:20]))) * 4.0
        v[31] = min(1.0, motion_delta)

        # Focus hotspot coordinates (where the visual attention is strongest on screen)
        att_map = edges + red_salience * 1.5
        max_idx = int(np.argmax(att_map))
        att_y, att_x = divmod(max_idx, 64)
        hotspot = {
            "norm_x": round((att_x / 64.0) * 2.0 - 1.0, 2),  # -1 (left) to +1 (right)
            "norm_y": round((att_y / 64.0) * 2.0 - 1.0, 2),  # -1 (top) to +1 (bottom)
            "motion": round(float(v[31]), 3),
            "edge_density": round(float(edges.mean()), 3),
        }
        return v, hotspot

    def forward_and_learn(
        self,
        img: Image.Image,
        detections: List[Dict[str, Any]],
        window_title: str,
    ) -> Dict[str, Any]:
        """
        Runs 1 step of Predictive Coding + Recurrent Working Memory + Hebbian Plasticity.
        Returns cognitive telemetry, affective vector, gaze target, and intuitive summary.
        """
        v_t, hotspot = self.encode_visual_cortex(img, detections)

        # 1. Top-down sensory prediction from working memory `h_{t-1}`
        v_pred = np.tanh(self.W_pred @ self.h)
        pred_error_vec = v_t - v_pred
        surprise = float(np.linalg.norm(pred_error_vec) / math.sqrt(self.V_DIM))
        surprise = min(1.0, surprise)

        # 2. Recurrent Working Memory Update (Leaky integration + synaptic drive)
        pre_act = (self.W_vh @ v_t) + (self.W_hh @ self.h)
        h_new = 0.35 * self.h + 0.65 * np.tanh(pre_act)

        # 3. Online Hebbian Learning with Oja's normalization (plasticity rate scaled by surprise)
        lr = 0.015 * (0.2 + surprise)
        self.W_vh += lr * (np.outer(h_new, v_t) - (h_new[:, None] ** 2) * self.W_vh)
        self.W_pred += lr * np.outer(pred_error_vec, self.h)

        self.h = h_new
        self.prev_v = v_t

        # Periodically persist learned synapses
        if time.time() - self._last_save_ts > 30.0:
            self._save_synapses()

        # 4. Update Continuous Human Affective State
        alert_energy = float(v_t[27] * 0.6 + v_t[28] * 0.4 + np.mean(v_t[23:27]))
        motion = hotspot["motion"]

        self.affect["surprise"] = round(surprise, 3)
        self.affect["curiosity"] = round(0.7 * self.affect["curiosity"] + 0.3 * min(1.0, surprise * 1.6), 3)
        self.affect["arousal"] = round(
            0.75 * self.affect["arousal"] + 0.25 * min(1.0, motion * 0.7 + alert_energy * 0.8 + 0.2), 3
        )
        self.affect["focus"] = round(
            0.8 * self.affect["focus"] + 0.2 * min(1.0, hotspot["edge_density"] * 2.2 + 0.3), 3
        )
        self.affect["valence"] = round(
            max(0.15, min(0.95, 0.75 - alert_energy * 0.45 + (0.1 if motion < 0.3 else 0.0))), 3
        )

        # Derive natural mascot emotion from continuous neural affect
        if alert_energy > 0.42:
            derived_emotion = "alert"
        elif surprise > 0.52:
            derived_emotion = "scanning"
        elif self.affect["valence"] > 0.72 and motion < 0.25:
            derived_emotion = "happy"
        else:
            derived_emotion = "idle"

        # Build concise human-like visual intuition trace
        scene_tempo = "nhịp độ cao" if motion > 0.28 else ("đang thao tác" if motion > 0.08 else "tĩnh/tập trung")
        trace_line = (
            f"[{window_title[:35]}] Nhịp thị giác: {scene_tempo} | "
            f"Độ bất ngờ (Surprise): {surprise:.2f} | Tập trung: {self.affect['focus']:.2f}"
        )
        if not self.visual_memory_trace or self.visual_memory_trace[-1] != trace_line:
            self.visual_memory_trace.append(trace_line)
            if len(self.visual_memory_trace) > 6:
                self.visual_memory_trace = self.visual_memory_trace[-6:]

        return {
            "affect": dict(self.affect),
            "emotion": derived_emotion,
            "hotspot": hotspot,
            "surprise": round(surprise, 3),
            "working_memory_norm": round(float(np.linalg.norm(self.h)), 3),
            "visual_intuition": trace_line,
            "recent_memory": list(self.visual_memory_trace[-3:]),
        }


neural_cognition = VisualCognitiveNeuralNetwork()
