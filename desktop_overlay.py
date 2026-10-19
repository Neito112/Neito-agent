import base64
import json
import math
import os
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Dict, Any, List, Optional

import httpx
import websockets
from PySide6.QtCore import (
    Qt,
    QTimer,
    QPoint,
    QPointF,
    QRectF,
    Signal,
    QObject,
    QUrl,
)
from PySide6.QtGui import (
    QPainter,
    QColor,
    QRadialGradient,
    QLinearGradient,
    QPen,
    QBrush,
    QPainterPath,
    QCursor,
    QImage,
    QIcon,
    QPixmap,
    QAction,
)
from PySide6.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLineEdit,
    QTextEdit,
    QLabel,
    QComboBox,
    QFrame,
    QSystemTrayIcon,
    QMenu,
    QSpinBox,
    QStackedWidget,
    QProgressBar,
)
import numpy as np
from backend.vision.mochi_esp32_client import MochiFacePlayer
from backend.core.updater import APP_VERSION

try:
    from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
    HAS_QT_AUDIO = True
except ImportError:
    HAS_QT_AUDIO = False


BACKEND_HTTP = "http://127.0.0.1:8765"
BACKEND_WS = "ws://127.0.0.1:8765/ws/xiaozhi"


def _resolve_app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


PROVIDER_CATALOG: Dict[str, Dict[str, Any]] = {
    "mochi_core": {
        "label": "Mochi Core (Firmware Gốc • Free)",
        "base_url": "local:mochi_firmware",
        "models": ["mochi-smart-v4 (Free)", "mochi-fast-v4 (Free)", "mochi-waifu-v4 (Free)"],
        "needs_key": False,
    },
    "xiaozhi_cloud": {
        "label": "Xiaozhi Console (xiaozhi.me/console/agents • MCP)",
        "base_url": "wss://api.tenclass.net/xiaozhi/v1/",
        "models": ["xiaozhi-console-agent", "xiaozhi-mcp-s3cam"],
        "needs_key": False,
    },
    "gemini": {
        "label": "Google Gemini (API Key • Khuyên dùng)",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "models": ["gemini-flash-lite-latest", "gemini-3.8-flash", "gemini-flash-latest"],
        "needs_key": True,
    },
    "groq": {
        "label": "Groq LPU (API Key • Siêu tốc)",
        "base_url": "https://api.groq.com/openai/v1",
        "models": ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "qwen-2.5-32b"],
        "needs_key": True,
    },
    "ollama": {
        "label": "Ollama (Local Offline • Miễn phí)",
        "base_url": "http://localhost:11434/v1",
        "models": ["qwen2.5:7b", "llama3.2:3b", "deepseek-r1:8b", "gemma2:9b"],
        "needs_key": False,
    },
    "openai": {
        "label": "OpenAI (ChatGPT API Key)",
        "base_url": "https://api.openai.com/v1",
        "models": ["gpt-4o-mini", "gpt-4o", "o3-mini"],
        "needs_key": True,
    },
    "deepseek": {
        "label": "DeepSeek (API Key)",
        "base_url": "https://api.deepseek.com/v1",
        "models": ["deepseek-chat", "deepseek-reasoner"],
        "needs_key": True,
    },
    "lmstudio": {
        "label": "LM Studio / vLLM (Local)",
        "base_url": "http://localhost:1234/v1",
        "models": ["local-model", "qwen2.5-7b-instruct", "llama-3.2-3b-instruct"],
        "needs_key": False,
    },
}

VOICE_PRESETS: List[tuple] = [
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


def create_mochi_tray_icon() -> QIcon:
    """Generates a sharp vector porcelain Mochi icon with OLED cyan eyes for Windows system tray."""
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.transparent)
    p = QPainter(pixmap)
    p.setRenderHint(QPainter.Antialiasing, True)

    # Outer glow / halo
    glow_grad = QRadialGradient(32, 32, 30)
    glow_grad.setColorAt(0.0, QColor(0, 229, 255, 60))
    glow_grad.setColorAt(1.0, QColor(0, 229, 255, 0))
    p.setBrush(QBrush(glow_grad))
    p.setPen(Qt.NoPen)
    p.drawEllipse(2, 2, 60, 60)

    # Porcelain spherical head body
    head_grad = QLinearGradient(12, 10, 52, 54)
    head_grad.setColorAt(0.0, QColor("#ffffff"))
    head_grad.setColorAt(0.85, QColor("#e2e8f0"))
    head_grad.setColorAt(1.0, QColor("#94a3b8"))
    p.setBrush(QBrush(head_grad))
    p.setPen(QPen(QColor(148, 163, 184, 180), 1.5))
    p.drawEllipse(6, 6, 52, 52)

    # Deep OLED Visor
    p.setBrush(QBrush(QColor("#040810")))
    p.setPen(QPen(QColor(0, 229, 255, 180), 1.2))
    p.drawRoundedRect(14, 18, 36, 26, 8, 8)

    # Glowing Cyan OLED Eyes
    p.setBrush(QBrush(QColor("#00f5d4")))
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(19, 24, 7, 10, 3, 3)
    p.drawRoundedRect(38, 24, 7, 10, 3, 3)

    # Adorable curved OLED smile
    p.setPen(QPen(QColor("#00f5d4"), 1.8, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    path = QPainterPath()
    path.moveTo(27, 36)
    path.quadTo(32, 40, 37, 36)
    p.drawPath(path)

    p.end()
    return QIcon(pixmap)


class BridgeSignals(QObject):
    ws_message = Signal(dict)
    connection_changed = Signal(bool)


class MascotCanvasWidget(QWidget):
    """
    60FPS Living Mascot Widget:
    - Approved Porcelain-White Sphere Head + Floating Side Pods + Deep OLED Visor.
    - Powered by the ESP32-C3 "The Mochi" 128x64 OLED Face Asset Pack (71 animations,
      2,447 frames + 27 SPIFFS WAV sounds extracted from https://themochi.huykhong.com/).
    - Supports Mochi Firmware 3-Tier Touch Sensor (Single-Tap, Double-Tap, Long-Touch)
      and Chronos Phone HUD modes (`show_clock`, `cpuz`, `notification`, `navigation`).
    """

    scale_changed = Signal(float)
    drag_moved = Signal(QPoint)
    poked = Signal()
    touch_triggered = Signal(str)

    POKE_FACES = [
        "UwU",
        "smile",
        "love",
        "happy_2",
        "hehe",
        "star",
        "gundam",
        "sakura",
        "keep_it_up",
        "demon_slayer",
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.base_size = 210
        self.scale_factor = 1.0
        self.setFixedSize(self.base_size, self.base_size)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setCursor(Qt.OpenHandCursor)

        self.mochi_player = MochiFacePlayer()
        self._poke_idx = 0
        self._last_tick_ts = time.perf_counter()
        self._current_oled_frame: np.ndarray = self.mochi_player.step(0.016)
        self._rgba_buf = np.zeros((64, 128, 4), dtype=np.uint8)

        self.emotion = "idle"
        self.mouth_open = 0.0
        self.arousal = 0.35
        self.valence = 0.75
        self.curiosity = 0.40
        self.surprise = 0.0
        self.neural_gaze_x = 0.0
        self.neural_gaze_y = 0.0

        self.look_x = 0.0
        self.look_y = 0.0
        self.blink = 0.0
        self.next_blink_ts = time.perf_counter() + 2.6

        self.bounce_y = 0.0
        self.bounce_vel = 0.0
        self.head_tilt = 0.0
        self.target_tilt = 0.0

        self._dragging = False
        self._drag_moved = False
        self._long_press_fired = False
        self._drag_start_global = QPoint()

        self._long_touch_timer = QTimer(self)
        self._long_touch_timer.setSingleShot(True)
        self._long_touch_timer.timeout.connect(self._on_long_touch)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(16)

    def set_scale(self, s: float):
        self.scale_factor = max(0.55, min(2.3, float(s)))
        sz = int(self.base_size * self.scale_factor)
        self.setFixedSize(sz, sz)
        self.scale_changed.emit(self.scale_factor)
        self.update()

    def set_emotion(self, emo: str):
        emo_l = (emo or "idle").lower()
        if emo_l != self.emotion:
            self.emotion = emo_l
            self.bounce_vel = -4.5
            self.target_tilt = 0.08 if emo_l in ("happy", "curious") else 0.0

    def set_mochi_face(self, face_name: str, loop: bool = False):
        self.mochi_player.set_face(face_name, loop=loop)
        self.bounce_vel = -5.2

    def update_neural_state(self, neural: Dict[str, Any], resources: Optional[Dict[str, Any]] = None):
        if resources:
            self.mochi_player.cpu_pct = int(resources.get("cpu_percent", 12))
            self.mochi_player.ram_gb = round(float(resources.get("memory_mb", 65.0)) / 1024.0, 2)
        if not neural:
            return
        affect = neural.get("affect", {})
        self.arousal = float(affect.get("arousal", 0.35))
        self.valence = float(affect.get("valence", 0.75))
        self.curiosity = float(affect.get("curiosity", 0.40))
        self.surprise = float(affect.get("surprise", 0.0))
        hotspot = neural.get("hotspot", {})
        self.neural_gaze_x = float(hotspot.get("norm_x", 0.0)) * 8.5
        self.neural_gaze_y = float(hotspot.get("norm_y", 0.0)) * 6.0
        if self.emotion in ("idle", "scanning", "alert", "happy") and self.mouth_open < 0.05:
            self.emotion = neural.get("emotion", "idle")

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        step = 0.08 if delta > 0 else -0.08
        p = self.parent()
        if p and hasattr(p, "_on_mascot_wheel_scale"):
            p._on_mascot_wheel_scale(self.scale_factor + step)
        else:
            self.set_scale(self.scale_factor + step)
        event.accept()

    def _on_long_touch(self):
        if self._dragging and not self._drag_moved:
            self._long_press_fired = True
            self.bounce_vel = -6.0
            self.touch_triggered.emit("long")

    def mousePressEvent(self, event):
        if event.button() == Qt.RightButton:
            self._show_context_menu(event.globalPosition().toPoint())
            event.accept()
            return
        if event.button() == Qt.LeftButton:
            self._dragging = True
            self._drag_moved = False
            self._long_press_fired = False
            self._drag_start_global = event.globalPosition().toPoint()
            self.setCursor(Qt.ClosedHandCursor)
            self._long_touch_timer.start(550)
            event.accept()

    def _show_context_menu(self, pos: QPoint):
        menu = QMenu(self)
        menu.setStyleSheet(
            """
            QMenu {
                background-color: #0d1527;
                color: #f1f5f9;
                border: 1px solid #00e5ff;
                border-radius: 8px;
                padding: 6px;
                font-size: 13px;
                font-weight: 500;
            }
            QMenu::item {
                padding: 6px 20px 6px 14px;
                border-radius: 4px;
            }
            QMenu::item:selected {
                background-color: rgba(0, 229, 255, 40);
                color: #00f5d4;
            }
            QMenu::separator {
                height: 1px;
                background: rgba(0, 229, 255, 40);
                margin: 4px 6px;
            }
            """
        )
        parent = self.parent()

        act_chat = menu.addAction("💬 Mở ô chat")
        act_settings = menu.addAction("⚙️ Cài đặt")
        menu.addSeparator()
        act_hide = menu.addAction("👁️ Ẩn vào Khay Hệ Thống")
        menu.addSeparator()
        act_quit = menu.addAction("🛑 Thoát Hoàn Toàn (Quit)")

        chosen = menu.exec(pos)
        if chosen == act_chat and parent and hasattr(parent, "_toggle_chat_input"):
            parent._toggle_chat_input()
        elif chosen == act_settings and parent and hasattr(parent, "_toggle_settings"):
            parent._toggle_settings()
        elif chosen == act_hide and parent:
            parent.hide()
            if hasattr(parent, "settings_popover"):
                parent.settings_popover.hide()
        elif chosen == act_quit and parent and hasattr(parent, "quit_application"):
            parent.quit_application()

    def mouseMoveEvent(self, event):
        if self._dragging:
            curr = event.globalPosition().toPoint()
            diff = curr - self._drag_start_global
            if diff.manhattanLength() > 4:
                self._drag_moved = True
                self._long_touch_timer.stop()
                self._drag_start_global = curr
                self.drag_moved.emit(diff)
            event.accept()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._long_touch_timer.stop()
            self._long_press_fired = True
            self.bounce_vel = -7.5
            self.target_tilt = 0.14
            self.touch_triggered.emit("double")
            event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._long_touch_timer.stop()
            self.setCursor(Qt.OpenHandCursor)
            if self._dragging and not self._drag_moved and not self._long_press_fired:
                self.bounce_vel = -6.8
                self.target_tilt = -0.11 if self.head_tilt >= 0 else 0.11
                self.poked.emit()
                self.touch_triggered.emit("single")
            self._dragging = False
            event.accept()

    def _tick(self):
        now = time.perf_counter()
        dt_sec = max(0.005, min(0.1, now - self._last_tick_ts))
        self._last_tick_ts = now

        cursor_pos = QCursor.pos()
        my_center = self.mapToGlobal(QPoint(self.width() // 2, self.height() // 2))
        dx = cursor_pos.x() - my_center.x()
        dy = cursor_pos.y() - my_center.y()
        dist = math.hypot(dx, dy)

        if dist < 420:
            tx = max(-1.0, min(1.0, dx / 220.0)) * 9.5
            ty = max(-1.0, min(1.0, dy / 220.0)) * 6.5
        else:
            tx = self.neural_gaze_x
            ty = self.neural_gaze_y

        self.look_x += (tx - self.look_x) * 0.16
        self.look_y += (ty - self.look_y) * 0.16

        self.bounce_vel += (0.0 - self.bounce_y) * 0.20
        self.bounce_vel *= 0.80
        self.bounce_y += self.bounce_vel
        self.head_tilt += (self.target_tilt - self.head_tilt) * 0.12

        state_str = "speaking" if self.mouth_open > 0.06 else (
            self.emotion if self.emotion in ("listening", "thinking") else "idle"
        )
        emo_str = "neutral" if self.emotion in ("idle", "scanning", "speaking", "listening") else self.emotion
        self._current_oled_frame = self.mochi_player.step(
            dt_sec=dt_sec,
            state=state_str,
            emotion=emo_str,
            gaze_x=self.look_x / 9.5,
            gaze_y=self.look_y / 6.5,
            lip_energy=self.mouth_open,
        )

        self.update()

    def _palette(self):
        if self.emotion == "alert":
            return QColor("#ff4d6d"), QColor("#fff0f3"), QColor(255, 77, 109, 105)
        if self.emotion == "listening":
            return QColor("#00f5d4"), QColor("#f0fffd"), QColor(0, 245, 212, 95)
        if self.emotion == "thinking":
            return QColor("#c084fc"), QColor("#faf5ff"), QColor(192, 132, 252, 95)
        if self.emotion == "happy":
            return QColor("#00f5d4"), QColor("#ffffff"), QColor(255, 117, 143, 135)
        return QColor("#00e5ff"), QColor("#ffffff"), QColor(255, 122, 162, 110)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.SmoothPixmapTransform, False)

        w = self.width()
        h = self.height()
        p.translate(w / 2.0, h / 2.0)
        p.scale(self.scale_factor, self.scale_factor)

        now = time.perf_counter()
        breath = math.sin(now * 3.1) * 3.8 + self.bounce_y - self.mouth_open * 3.0
        p.translate(0.0, breath)
        p.rotate(math.degrees(self.head_tilt))

        glow_col, highlight_col, blush_col = self._palette()

        stretch_y = 1.0 + self.mouth_open * 0.045 - self.bounce_vel * 0.006
        stretch_x = 1.0 / math.sqrt(max(0.85, stretch_y))
        p.scale(stretch_x, stretch_y)

        # 1. Floating Magnetic Ear Pods (Approved Head Design)
        pod_bob = math.sin(now * 4.2) * 2.5
        for sign in (-1, 1):
            p.save()
            p.translate(sign * 76.0, -4.0 + pod_bob)
            p.rotate(sign * (8.0 + self.mouth_open * 12.0))
            pod_grad = QLinearGradient(0, -18, 0, 18)
            pod_grad.setColorAt(0.0, QColor("#f8fafc"))
            pod_grad.setColorAt(1.0, QColor("#cbd5e1"))
            p.setBrush(QBrush(pod_grad))
            p.setPen(QPen(glow_col, 1.8))
            p.drawRoundedRect(QRectF(-7, -18, 14, 36), 7, 7)
            p.restore()

        # 2. Outer Soft Aura Glow when speaking/listening
        if self.mouth_open > 0.04 or self.emotion in ("listening", "alert"):
            aura_r = 74.0 + self.mouth_open * 10.0 + math.sin(now * 8.0) * 2.5
            aura_col = QColor(glow_col)
            aura_col.setAlpha(75)
            p.setPen(QPen(aura_col, 3.0))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(QPointF(0, 0), aura_r, aura_r)

        # 3. Main Spherical Porcelain-Gloss Head Shell (Approved Head Design)
        r = 68.0
        shell_grad = QRadialGradient(QPointF(-22, -26), r * 1.35)
        shell_grad.setColorAt(0.0, QColor("#ffffff"))
        shell_grad.setColorAt(0.55, QColor("#e2e8f0"))
        shell_grad.setColorAt(0.88, QColor("#94a3b8"))
        shell_grad.setColorAt(1.0, QColor("#475569"))

        p.setPen(QPen(QColor(255, 255, 255, 190), 2.0))
        p.setBrush(QBrush(shell_grad))
        p.drawEllipse(QPointF(0, 0), r, r)

        # 4. Deep Glossy Black OLED Face Visor
        visor_rect = QRectF(-56, -42, 112, 86)
        visor_grad = QLinearGradient(0, -42, 0, 44)
        visor_grad.setColorAt(0.0, QColor("#060911"))
        visor_grad.setColorAt(0.5, QColor("#03050a"))
        visor_grad.setColorAt(1.0, QColor("#080d1a"))

        p.setPen(QPen(glow_col, 2.2))
        p.setBrush(QBrush(visor_grad))
        p.drawRoundedRect(visor_rect, 38, 38)

        # Clip inside Visor for OLED Face & Kawaii Cheeks
        p.save()
        visor_clip = QPainterPath()
        visor_clip.addRoundedRect(visor_rect.adjusted(3, 3, -3, -3), 35, 35)
        p.setClipPath(visor_clip)

        gx = self.look_x * 0.48
        gy = self.look_y * 0.48

        # 5. Soft Pink Kawaii Cheeks (shown when face doesn't already draw pixel cheeks)
        if self.mochi_player.current_face in ("mac_dinh", "smile", "happy_2", "nhin_ben_trai", "nhin_ben_phai", "nhin_xuong", "nheo_mat"):
            p.setPen(Qt.NoPen)
            p.setBrush(blush_col)
            p.drawEllipse(QPointF(-35 + gx, 19 + gy), 8.0, 4.2)
            p.drawEllipse(QPointF(35 + gx, 19 + gy), 8.0, 4.2)

        # 6. Authentic ESP32 "The Mochi" 128x64 OLED Face Bitmap
        self._draw_mochi_oled_frame(p, gx, gy, glow_col, highlight_col)
        p.restore()

        # Subtle top glass reflection arc on visor
        glass_path = QPainterPath()
        glass_path.addRoundedRect(QRectF(-44, -36, 88, 16), 8, 8)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 16))
        p.drawPath(glass_path)

        p.end()

    def _draw_mochi_oled_frame(
        self,
        p: QPainter,
        gx: float,
        gy: float,
        glow_col: QColor,
        highlight_col: QColor,
    ):
        """
        Renders the active 128x64 1-bit OLED frame from `MochiFacePlayer`
        with a soft cyan/theme phosphor bloom + crisp white OLED pixels.
        """
        bits = self._current_oled_frame
        if bits is None or bits.shape != (64, 128):
            return

        # 1. Build 1-pixel dilated bloom mask for authentic OLED glow
        bloom_mask = bits.astype(bool)
        dilated = bloom_mask.copy()
        dilated[:, 1:] |= bloom_mask[:, :-1]
        dilated[:, :-1] |= bloom_mask[:, 1:]
        dilated[1:, :] |= bloom_mask[:-1, :]
        dilated[:-1, :] |= bloom_mask[1:, :]
        halo_mask = dilated & (~bloom_mask)

        # Format_ARGB32 on little-endian x86 is BGRA in memory
        buf = self._rgba_buf
        buf.fill(0)

        # Outer 1px OLED phosphor halo
        buf[halo_mask, 0] = glow_col.blue()
        buf[halo_mask, 1] = glow_col.green()
        buf[halo_mask, 2] = glow_col.red()
        buf[halo_mask, 3] = 115

        # Crisp lit OLED pixel core (Pure White / Highlight)
        buf[bloom_mask, 0] = highlight_col.blue()
        buf[bloom_mask, 1] = highlight_col.green()
        buf[bloom_mask, 2] = highlight_col.red()
        buf[bloom_mask, 3] = 255

        qimg = QImage(buf.data, 128, 64, 128 * 4, QImage.Format_ARGB32)
        # Only shift with cursor gaze on default/idle eye expressions so full-screen FX stay centered
        if self.mochi_player.current_face in ("mac_dinh", "smile", "UwU", "happy_2", "nheo_mat", "sleepy"):
            target_rect = QRectF(-53.0 + gx, -27.0 + gy, 106.0, 53.0)
        else:
            target_rect = QRectF(-53.0, -27.0, 106.0, 53.0)
        p.drawImage(target_rect, qimg)


def open_native_url(url: str):
    """Reliably opens a URL in Windows using native ShellExecute with fallback."""
    import os
    import webbrowser
    try:
        os.startfile(url)
    except Exception:
        webbrowser.open(url)


class DraggableFramelessWidget(QWidget):
    """Base class for all frameless secondary windows so they can be freely dragged anywhere on screen."""

    def __init__(self, parent=None, flags=Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint):
        super().__init__(parent, flags)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self._drag_pos: Optional[QPoint] = None
        self._user_moved: bool = False

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.LeftButton and self._drag_pos is not None:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            self._user_moved = True
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_pos = None
        event.accept()


class SoulProfileDialog(DraggableFramelessWidget):
    """
    Compact 'Soul' Profile Popup for customizing Agent Name & Personality.
    Opened by clicking the [✨ Soul] button inside Settings.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(260)

        frame = QFrame(self)
        frame.setObjectName("soulFrame")
        frame.setStyleSheet(
            """
            QFrame#soulFrame {
                background-color: rgba(11, 16, 28, 246);
                border: 1.5px solid #c084fc;
                border-radius: 14px;
            }
            QLabel {
                color: #f3e8ff;
                font-size: 12px;
                font-weight: 700;
            }
            QLineEdit, QTextEdit {
                background-color: rgba(20, 27, 45, 235);
                border: 1px solid rgba(192, 132, 252, 90);
                border-radius: 8px;
                color: #f8fafc;
                padding: 5px 8px;
                font-size: 12px;
            }
            QPushButton#saveSoulBtn {
                background-color: #c084fc;
                color: #090d16;
                border: none;
                border-radius: 8px;
                padding: 6px 10px;
                font-weight: 800;
                font-size: 12px;
            }
            QPushButton#saveSoulBtn:hover {
                background-color: #d8b4fe;
            }
            QPushButton#closeSoulBtn {
                background: transparent;
                color: #94a3b8;
                border: none;
                font-size: 13px;
                font-weight: bold;
            }
            """
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(frame)

        lay = QVBoxLayout(frame)
        lay.setContentsMargins(12, 10, 12, 12)
        lay.setSpacing(7)

        hdr = QHBoxLayout()
        lbl = QLabel("✨ Soul Profile (Kéo di chuyển)")
        lbl.setCursor(Qt.SizeAllCursor)
        btn_x = QPushButton("✕")
        btn_x.setObjectName("closeSoulBtn")
        btn_x.setFixedSize(20, 20)
        btn_x.clicked.connect(self.hide)
        hdr.addWidget(lbl)
        hdr.addStretch()
        hdr.addWidget(btn_x)
        lay.addLayout(hdr)

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("Tên Agent (VD: Neito)")
        lay.addWidget(self.name_input)

        self.persona_input = QTextEdit()
        self.persona_input.setPlaceholderText("Tính cách & Phong cách xưng hô...")
        self.persona_input.setFixedHeight(78)
        lay.addWidget(self.persona_input)

        self.btn_save = QPushButton("Lưu Soul")
        self.btn_save.setObjectName("saveSoulBtn")
        self.btn_save.clicked.connect(self._save_soul)
        lay.addWidget(self.btn_save)

    def load_soul(self):
        try:
            r = httpx.get(f"{BACKEND_HTTP}/api/config", timeout=1.5)
            if r.status_code == 200:
                cfg = r.json()
                self.name_input.setText(cfg.get("agent_name", "Neito"))
                self.persona_input.setPlainText(cfg.get("system_persona", ""))
        except Exception:
            pass

    def _save_soul(self):
        patch = {
            "agent_name": self.name_input.text().strip() or "Neito",
            "system_persona": self.persona_input.toPlainText().strip(),
        }
        try:
            httpx.post(f"{BACKEND_HTTP}/api/config", json=patch, timeout=2.0)
            self.btn_save.setText("✓ Đã lưu")
            QTimer.singleShot(700, lambda: (self.btn_save.setText("Lưu Soul"), self.hide()))
        except Exception:
            self.btn_save.setText("Lỗi")


def launch_thietlap_with_webserial_bridge(fallback_url: str = "http://127.0.0.1:8765/thietlap/"):
    """
    Launches `https://themochi.huykhong.com/thietlap/` in Chrome/Edge with CDP
    (`--remote-debugging-port=19225`) via `http://127.0.0.1:8765/api/mochi/bridge-launch`
    so `navigator.serial.requestPort()` displays `THE MOCHI - Neito Agent (COM9)`
    at the top of the scan list on Chrome 137..155+.
    """
    import shutil
    import subprocess

    profile_dir = Path(os.environ.get("LOCALAPPDATA", str(_resolve_app_dir()))) / "NeitoMochiBridgeProfile"
    profile_dir.mkdir(parents=True, exist_ok=True)

    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        shutil.which("chrome"),
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        shutil.which("msedge"),
    ]
    browser_exe = next((c for c in candidates if c and Path(c).exists()), None)

    if browser_exe:
        try:
            subprocess.Popen(
                [
                    str(browser_exe),
                    f"--user-data-dir={profile_dir}",
                    "--remote-debugging-port=19225",
                    "--disable-features=LocalNetworkAccessChecks,BlockInsecurePrivateNetworkRequests,PrivateNetworkAccessRespectPreflightResults",
                    "--no-first-run",
                    "--no-default-browser-check",
                    "http://127.0.0.1:8765/api/mochi/bridge-launch",
                ],
                close_fds=True,
            )
            return True
        except Exception:
            pass

    open_native_url(fallback_url)
    return False


class MobileBridgeDialog(DraggableFramelessWidget):
    """
    ESP32-S3 Ultimate Hardware Emulator Control Center:
      - Tab 0: `ESP32-S3 & Xiaozhi` (`https://xiaozhi.me/console/agents` 6-digit binding + Screen-Camera + Built-in Hardware YOLO MCP)
      - Tab 1: `Chronos BLE` (Real Windows BLE GATT Server for Chronos Phone App)
      - Tab 2: `Web (/thietlap)` (Web-Serial Bridge for `https://themochi.huykhong.com/thietlap/`)
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(345)
        self.mobile_url = f"{BACKEND_HTTP}/thietlap/"
        self.activation_code = ""

        frame = QFrame(self)
        frame.setObjectName("mobileFrame")
        frame.setStyleSheet(
            """
            QFrame#mobileFrame {
                background-color: rgba(11, 16, 28, 250);
                border: 1.5px solid #00f5d4;
                border-radius: 14px;
            }
            QLabel {
                color: #e0f2fe;
                font-size: 11px;
                font-weight: 600;
            }
            QLineEdit, QSpinBox, QComboBox {
                background-color: rgba(20, 29, 49, 235);
                border: 1px solid rgba(0, 245, 212, 95);
                border-radius: 6px;
                color: #00f5d4;
                padding: 4px 6px;
                font-size: 11px;
                font-weight: 700;
            }
            QPushButton {
                background-color: rgba(25, 38, 64, 230);
                color: #f1f5f9;
                border: 1px solid rgba(0, 229, 255, 85);
                border-radius: 6px;
                padding: 5px 8px;
                font-size: 11px;
                font-weight: 700;
            }
            QPushButton:hover {
                background-color: rgba(0, 229, 255, 65);
            }
            QPushButton#tabBtnActive {
                background-color: rgba(0, 245, 212, 45);
                border-color: #00f5d4;
                color: #00f5d4;
            }
            """
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(frame)

        lay = QVBoxLayout(frame)
        lay.setContentsMargins(10, 8, 10, 10)
        lay.setSpacing(6)

        hdr = QHBoxLayout()
        lbl = QLabel("🔌 Giả Lập Phần Cứng ESP32-S3 • Xiaozhi • Chronos")
        lbl.setCursor(Qt.SizeAllCursor)
        lbl.setStyleSheet("font-size: 11.5px; font-weight: 800; color: #00f5d4;")
        btn_x = QPushButton("✕")
        btn_x.setFixedSize(20, 20)
        btn_x.setStyleSheet("padding: 0; font-size: 11px;")
        btn_x.clicked.connect(self.hide)
        hdr.addWidget(lbl)
        hdr.addStretch()
        hdr.addWidget(btn_x)
        lay.addLayout(hdr)

        tabs_bar = QHBoxLayout()
        tabs_bar.setSpacing(3)
        self.btn_tab_esp32 = QPushButton("🤖 ESP32-S3 & Xiaozhi")
        self.btn_tab_esp32.setObjectName("tabBtnActive")
        self.btn_tab_ble = QPushButton("📱 Chronos BLE")
        self.btn_tab_web = QPushButton("🌐 Web (/thietlap)")
        self.btn_tab_esp32.clicked.connect(lambda: self._switch_tab(0))
        self.btn_tab_ble.clicked.connect(lambda: self._switch_tab(1))
        self.btn_tab_web.clicked.connect(lambda: self._switch_tab(2))
        tabs_bar.addWidget(self.btn_tab_esp32)
        tabs_bar.addWidget(self.btn_tab_ble)
        tabs_bar.addWidget(self.btn_tab_web)
        lay.addLayout(tabs_bar)

        self.stack = QStackedWidget()
        lay.addWidget(self.stack)

        # --- TAB 0: ESP32-S3 ULTIMATE HARDWARE EMULATOR & XIAOZHI.ME CONSOLE / YOLO MCP ---
        page_esp = QWidget()
        p0_lay = QVBoxLayout(page_esp)
        p0_lay.setContentsMargins(0, 4, 0, 0)
        p0_lay.setSpacing(5)

        self.lbl_hw_spec = QLabel(
            "🖥️ Board: ESP32-S3-N16R8-CAM-BOX3 (Dual-Core 240MHz • 16MB Flash • 8MB PSRAM)\n"
            "📷 Cam Ảo: Nhìn Màn Hình PC (OV2640-ScreenCam) + Chip NPU YOLO11n MCP"
        )
        self.lbl_hw_spec.setStyleSheet(
            "background: rgba(15,23,42,190); border: 1px solid rgba(56,189,248,0.35); "
            "border-radius: 6px; padding: 5px; color: #38bdf8; font-size: 9.8px; font-weight: 700;"
        )
        p0_lay.addWidget(self.lbl_hw_spec)

        code_box = QFrame()
        code_box.setStyleSheet(
            "background: rgba(16, 185, 129, 0.12); border: 1px solid #00f5d4; border-radius: 7px;"
        )
        cb_lay = QVBoxLayout(code_box)
        cb_lay.setContentsMargins(6, 5, 6, 5)
        cb_lay.setSpacing(3)

        self.lbl_xiaozhi_code = QLabel("🔑 Mã kết nối xiaozhi.me: Đang lấy mã OTA...")
        self.lbl_xiaozhi_code.setStyleSheet("color: #00f5d4; font-size: 12px; font-weight: 800;")
        cb_lay.addWidget(self.lbl_xiaozhi_code)

        self.lbl_xiaozhi_mac = QLabel("MAC: ec:da:3b:--:--:-- | Server: wss://api.tenclass.net/xiaozhi/v1/")
        self.lbl_xiaozhi_mac.setStyleSheet("color: #94a3b8; font-size: 9.5px; font-weight: 600;")
        cb_lay.addWidget(self.lbl_xiaozhi_mac)

        code_btns = QHBoxLayout()
        code_btns.setSpacing(4)
        self.btn_open_xiaozhi = QPushButton("🌐 Mở xiaozhi.me/console/agents")
        self.btn_open_xiaozhi.setStyleSheet(
            "background: linear-gradient(135deg, #00f5d4 0%, #0284c7 100%); "
            "color: #050811; font-weight: 800; font-size: 10.5px; padding: 5px; border: none; border-radius: 6px;"
        )
        self.btn_open_xiaozhi.clicked.connect(lambda: open_native_url("https://xiaozhi.me/console/agents"))

        self.btn_copy_code = QPushButton("📋 Copy Mã")
        self.btn_copy_code.clicked.connect(self._copy_xiaozhi_code)

        self.btn_refresh_ota = QPushButton("🔄 Lấy Mã")
        self.btn_refresh_ota.clicked.connect(self._refresh_xiaozhi_ota)

        code_btns.addWidget(self.btn_open_xiaozhi, 1)
        code_btns.addWidget(self.btn_copy_code)
        code_btns.addWidget(self.btn_refresh_ota)
        cb_lay.addLayout(code_btns)
        p0_lay.addWidget(code_box)

        # Hardware Screen-YOLO MCP Mode Selector
        yolo_row = QHBoxLayout()
        lbl_ym = QLabel("👁️ Phần cứng NPU YOLO:")
        lbl_ym.setStyleSheet("color: #e0f2fe; font-size: 10.5px; font-weight: 700;")
        self.combo_yolo_hw = QComboBox()
        self.combo_yolo_hw.addItem("⚡ Eco 1 FPS (Nhìn màn hình tiết kiệm)", "eco_1fps")
        self.combo_yolo_hw.addItem("⚖️ Balanced 4 FPS (Cân bằng đa nhiệm)", "balanced_4fps")
        self.combo_yolo_hw.addItem("🔥 Combat 10 FPS (Chơi game tốc độ cao)", "combat_10fps")
        self.combo_yolo_hw.addItem("🧠 Auto-Reflex (Tự động phản xạ HUD)", "auto_reflex")
        self.combo_yolo_hw.addItem("⏸️ Off (Tắt chip NPU YOLO)", "off")
        self.combo_yolo_hw.currentIndexChanged.connect(self._on_yolo_hw_mode_changed)
        yolo_row.addWidget(lbl_ym)
        yolo_row.addWidget(self.combo_yolo_hw, 1)
        p0_lay.addLayout(yolo_row)

        self.lbl_mcp_list = QLabel(
            "🧩 9 MCP Phần Cứng Tích Hợp Sẵn (Nạp tự động vào Xiaozhi & LLM Key):\n"
            "• self.camera.take_photo (Chụp màn hình PC + gửi Vision & YOLO)\n"
            "• self.yolo.scan_screen | self.yolo.set_mode | self.yolo.train_open_vocab\n"
            "• self.protocol.create_or_update | self.screen.set_expression | self.audio.set_volume"
        )
        self.lbl_mcp_list.setStyleSheet(
            "background: rgba(15,23,42,160); border-radius: 6px; padding: 5px; color: #cbd5e1; font-size: 9.3px;"
        )
        p0_lay.addWidget(self.lbl_mcp_list)

        self.stack.addWidget(page_esp)

        # --- TAB 1: REAL WINDOWS BLE GATT SERVER FOR CHRONOS PHONE APP ---
        page_ble = QWidget()
        p1_lay = QVBoxLayout(page_ble)
        p1_lay.setContentsMargins(0, 4, 0, 0)
        p1_lay.setSpacing(5)

        self.btn_connect_phone = QPushButton("📡 PHÁT TÍN HIỆU BLE CHO APP CHRONOS")
        self.btn_connect_phone.setStyleSheet(
            "background: linear-gradient(135deg, #00f5d4 0%, #0284c7 100%); "
            "color: #050811; font-weight: 800; font-size: 11px; padding: 7px; border: none; border-radius: 7px;"
        )
        self.btn_connect_phone.clicked.connect(self._restart_ble_advertising)
        p1_lay.addWidget(self.btn_connect_phone)

        self.lbl_ble_status = QLabel("● Đang phát sóng BLE GATT (ChronosESP32)")
        self.lbl_ble_status.setStyleSheet("color: #10b981; font-weight: 700; font-size: 10.5px;")
        p1_lay.addWidget(self.lbl_ble_status)

        self.lbl_pc_ble_info = QLabel("Thiết bị BLE trên PC: HXG-Neito (UUID: 6e400001...)")
        self.lbl_pc_ble_info.setStyleSheet("color: #38bdf8; font-weight: 700; font-size: 10px;")
        p1_lay.addWidget(self.lbl_pc_ble_info)

        row_name = QHBoxLayout()
        lbl_n = QLabel("Tên định danh:")
        lbl_n.setFixedWidth(85)
        self.input_ble_name = QLineEdit("THE MOCHI")
        row_name.addWidget(lbl_n)
        row_name.addWidget(self.input_ble_name)
        p1_lay.addLayout(row_name)

        row_dur = QHBoxLayout()
        lbl_d = QLabel("Hiện thông báo:")
        lbl_d.setFixedWidth(85)
        self.spin_duration = QSpinBox()
        self.spin_duration.setRange(1, 15)
        self.spin_duration.setValue(5)
        self.spin_duration.setSuffix(" giây")
        row_dur.addWidget(lbl_d)
        row_dur.addWidget(self.spin_duration)
        p1_lay.addLayout(row_dur)

        row_off = QHBoxLayout()
        lbl_o = QLabel("Tự tắt BLE:")
        lbl_o.setFixedWidth(85)
        self.spin_auto_off = QSpinBox()
        self.spin_auto_off.setRange(0, 60)
        self.spin_auto_off.setValue(0)
        self.spin_auto_off.setSpecialValueText("0 (Luôn bật)")
        self.spin_auto_off.setSuffix(" phút")
        row_off.addWidget(lbl_o)
        row_off.addWidget(self.spin_auto_off)
        p1_lay.addLayout(row_off)

        self.btn_save_chronos = QPushButton("💾 Lưu Thiết Lập Chronos")
        self.btn_save_chronos.clicked.connect(self._save_chronos_settings)
        p1_lay.addWidget(self.btn_save_chronos)

        lbl_g = QLabel("Cách kết nối từ App Chronos trên Điện Thoại:")
        lbl_g.setStyleSheet("color: #94a3b8; font-weight: 700; font-size: 10px; margin-top: 2px;")
        p1_lay.addWidget(lbl_g)

        self.guide_text = QLabel(
            "1. Mở app Chronos trên điện thoại (bật Bluetooth PC & ĐT)\n"
            "2. Vào tab Đồng hồ -> Bấm Tìm kiếm thiết bị (Scan)\n"
            "3. Chọn thiết bị Bluetooth của PC: \"HXG-Neito\"\n"
            "4. Cấp quyền Thông báo & Google Maps trong app Chronos"
        )
        self.guide_text.setStyleSheet(
            "background: rgba(15,23,42,160); border-radius: 6px; padding: 5px; color: #cbd5e1; font-size: 9.5px; line-height: 125%;"
        )
        p1_lay.addWidget(self.guide_text)

        self.stack.addWidget(page_ble)

        # --- TAB 2: WEB SERIAL BRIDGE FOR https://themochi.huykhong.com/thietlap/ ---
        page_web = QWidget()
        p2_lay = QVBoxLayout(page_web)
        p2_lay.setContentsMargins(0, 4, 0, 0)
        p2_lay.setSpacing(5)

        self.btn_connect_web = QPushButton("⚡ MỞ THEMOCHI.HUYKHONG.COM/THIETLAP (HIỆN CỔNG COM9)")
        self.btn_connect_web.setStyleSheet(
            "background: linear-gradient(135deg, #00f5d4 0%, #0284c7 100%); "
            "color: #050811; font-weight: 800; font-size: 10.5px; padding: 7px; border: none; border-radius: 7px;"
        )
        self.btn_connect_web.clicked.connect(self._connect_web_controller)
        p2_lay.addWidget(self.btn_connect_web)

        self.btn_install_vcom = QPushButton("🔌 Cài Driver Cổng COM9 Ảo Vào Windows (Mọi Trình Duyệt)")
        self.btn_install_vcom.setToolTip(
            "Tạo cặp cổng nối tiếp ảo COM9 <-> COM10 cấp hệ điều hành để mọi trình duyệt tự thấy THE MOCHI - Neito Agent (COM9)"
        )
        self.btn_install_vcom.clicked.connect(self._install_virtual_com_driver)
        p2_lay.addWidget(self.btn_install_vcom)

        self.btn_open_local_thietlap = QPushButton("🌐 Mở Bản Cầu Nối Trực Tiếp (127.0.0.1:8765/thietlap)")
        self.btn_open_local_thietlap.clicked.connect(lambda: open_native_url("http://127.0.0.1:8765/thietlap/"))
        p2_lay.addWidget(self.btn_open_local_thietlap)

        self.lbl_web_status = QLabel("● Đã tạo tín hiệu cổng COM9 (THE MOCHI - Neito Agent)")
        self.lbl_web_status.setStyleSheet("color: #10b981; font-size: 10px; font-weight: 700;")
        p2_lay.addWidget(self.lbl_web_status)

        lbl_qr_title = QLabel("Hoặc quét QR để mở trang /thietlap trên ĐT:")
        lbl_qr_title.setStyleSheet("color: #94a3b8; font-size: 10px; font-weight: 700;")
        p2_lay.addWidget(lbl_qr_title)

        self.lbl_qr_img = QLabel()
        self.lbl_qr_img.setAlignment(Qt.AlignCenter)
        self.lbl_qr_img.setFixedHeight(95)
        p2_lay.addWidget(self.lbl_qr_img)

        self.url_box = QLineEdit(self.mobile_url)
        self.url_box.setReadOnly(True)
        p2_lay.addWidget(self.url_box)

        row_web_btns = QHBoxLayout()
        row_web_btns.setSpacing(4)
        self.btn_copy_link = QPushButton("📋 Copy Link")
        self.btn_copy_link.clicked.connect(self._copy_web_url)
        self.btn_copy_ext = QPushButton("🧩 Copy Path Extension")
        self.btn_copy_ext.setToolTip("Copy đường dẫn thư mục Extension cầu nối để nạp vào chrome://extensions hoặc edge://extensions")
        self.btn_copy_ext.clicked.connect(self._copy_extension_path)
        row_web_btns.addWidget(self.btn_copy_link)
        row_web_btns.addWidget(self.btn_copy_ext)
        p2_lay.addLayout(row_web_btns)

        self.stack.addWidget(page_web)

    def _switch_tab(self, idx: int):
        self.stack.setCurrentIndex(idx)
        for i, btn in enumerate((self.btn_tab_esp32, self.btn_tab_ble, self.btn_tab_web)):
            btn.setObjectName("tabBtnActive" if i == idx else "")
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def _copy_xiaozhi_code(self):
        if self.activation_code:
            QApplication.clipboard().setText(self.activation_code)
            self.btn_copy_code.setText("✓ Đã Copy")
            QTimer.singleShot(1500, lambda: self.btn_copy_code.setText("📋 Copy Mã"))

    def _refresh_xiaozhi_ota(self):
        self.btn_refresh_ota.setText("⏳...")
        QApplication.processEvents()
        try:
            r = httpx.post(f"{BACKEND_HTTP}/api/esp32/xiaozhi-ota", json={}, timeout=6.0)
            if r.status_code == 200:
                d = r.json()
                code = d.get("activation_code", "")
                mac = d.get("mac_address", "")
                self.activation_code = code
                if code:
                    self.lbl_xiaozhi_code.setText(f"🔑 Mã xác thực 6 số (xiaozhi.me): {code}")
                else:
                    self.lbl_xiaozhi_code.setText("🟢 Đã liên kết thành công trên xiaozhi.me/console/agents!")
                if mac:
                    self.lbl_xiaozhi_mac.setText(f"MAC: {mac} | Server: {d.get('ws_url', '')}")
        except Exception:
            pass
        finally:
            self.btn_refresh_ota.setText("🔄 Lấy Mã")

    def _on_yolo_hw_mode_changed(self):
        mode = self.combo_yolo_hw.currentData() or "eco_1fps"
        try:
            httpx.post(f"{BACKEND_HTTP}/api/esp32/yolo-mode", json={"mode": mode}, timeout=2.0)
        except Exception:
            pass

    def refresh_status(self):
        try:
            r_hw = httpx.get(f"{BACKEND_HTTP}/api/esp32/hardware", timeout=2.0)
            if r_hw.status_code == 200:
                hw = r_hw.json().get("hardware") or {}
                conn = (hw.get("peripherals") or {}).get("connectivity") or {}
                npu = (hw.get("peripherals") or {}).get("npu_coprocessor") or {}
                code = conn.get("activation_code", "")
                mac = hw.get("mac_address", "")
                self.activation_code = code
                if code:
                    self.lbl_xiaozhi_code.setText(f"🔑 Mã xác thực 6 số (xiaozhi.me): {code}")
                else:
                    self._refresh_xiaozhi_ota()
                if mac:
                    self.lbl_xiaozhi_mac.setText(f"MAC: {mac} | Server: {conn.get('xiaozhi_ws_url', '')}")
                ymode = npu.get("mode", "eco_1fps")
                y_idx = self.combo_yolo_hw.findData(ymode)
                if y_idx >= 0:
                    self.combo_yolo_hw.blockSignals(True)
                    self.combo_yolo_hw.setCurrentIndex(y_idx)
                    self.combo_yolo_hw.blockSignals(False)
        except Exception:
            pass

        try:
            r = httpx.get(f"{BACKEND_HTTP}/api/mochi/chronos/config", timeout=1.5)
            if r.status_code == 200:
                data = r.json()
                ble_name = data.get("bluetoothName", "THE MOCHI")
                pc_name = data.get("pc_ble_name", "PC")
                self.input_ble_name.setText(ble_name)
                self.spin_duration.setValue(int(data.get("notifDuration", 5)))
                self.spin_auto_off.setValue(int(data.get("bluetooth_auto_off", 0)))
                self.mobile_url = data.get("mobile_companion_url", f"{BACKEND_HTTP}/thietlap/")
                self.url_box.setText(self.mobile_url)
                self.lbl_pc_ble_info.setText(f"Tên BLE trên App Chronos: {pc_name} ({ble_name})")

                vcom = data.get("virtual_com") or {}
                if vcom.get("driver_installed"):
                    bport = vcom.get("browser_port", "COM9")
                    self.btn_install_vcom.setText(f"🟢 Cổng Ảo Windows {bport} Đã Cài & Sẵn Sàng")
                    self.lbl_web_status.setText(f"🟢 Khi quét trên web, chọn: THE MOCHI - Neito Agent ({bport})")
                else:
                    self.btn_install_vcom.setText("🔌 Cài Driver Cổng COM9 Ảo Vào Windows (Mọi Trình Duyệt)")

                if data.get("phone_connected"):
                    bat = data.get("phone_battery", 100)
                    self.btn_connect_phone.setText(f"🟢 ĐÃ GHÉP NỐI APP CHRONOS (Pin ĐT: {bat}%)")
                    self.btn_connect_phone.setStyleSheet(
                        "background: rgba(16, 185, 129, 210); color: #fff; font-weight: 800; font-size: 11px; padding: 7px; border: 1px solid #10b981; border-radius: 7px;"
                    )
                    self.lbl_ble_status.setText("🟢 Điện thoại đã kết nối qua BLE GATT (ChronosESP32)")
                    self.lbl_ble_status.setStyleSheet("color: #00f5d4; font-weight: 700; font-size: 10.5px;")
                elif data.get("is_advertising"):
                    self.btn_connect_phone.setText("📡 ĐANG PHÁT SÓNG BLE (Bấm Để Phát Lại)")
                    self.btn_connect_phone.setStyleSheet(
                        "background: linear-gradient(135deg, #00f5d4 0%, #0284c7 100%); color: #050811; font-weight: 800; font-size: 11px; padding: 7px; border: none; border-radius: 7px;"
                    )
                    self.lbl_ble_status.setText(f"● Đang phát tín hiệu BLE: Chọn \"{pc_name}\" trên App Chronos")
                    self.lbl_ble_status.setStyleSheet("color: #10b981; font-weight: 700; font-size: 10px;")
                else:
                    self.btn_connect_phone.setText("⚡ BẬT PHÁT SÓNG BLE CHO CHRONOS")
                    self.lbl_ble_status.setText("⚠️ Hãy bật Bluetooth trên Windows rồi bấm nút trên")
                    self.lbl_ble_status.setStyleSheet("color: #f59e0b; font-weight: 700; font-size: 10px;")
                self._update_qr_image()
        except Exception:
            pass

    def _restart_ble_advertising(self):
        try:
            r = httpx.post(f"{BACKEND_HTTP}/api/mochi/chronos/connect", json={"action": "restart"}, timeout=3.0)
            if r.status_code == 200:
                self.refresh_status()
        except Exception:
            self.lbl_ble_status.setText("Lỗi kết nối backend")

    def _connect_web_controller(self):
        launched_ext = launch_thietlap_with_webserial_bridge(self.mobile_url)
        self.btn_connect_web.setText("🟢 ĐÃ MỞ TRANG THIẾT LẬP VỚI CẦU NỐI COM9")
        self.btn_connect_web.setStyleSheet(
            "background: rgba(16, 185, 129, 210); color: #fff; font-weight: 800; font-size: 10.5px; padding: 7px; border: 1px solid #10b981; border-radius: 7px;"
        )
        if launched_ext:
            self.lbl_web_status.setText("🟢 Bấm 'Kết nối' trên web -> Chọn THE MOCHI - Neito Agent (COM9)")
        else:
            self.lbl_web_status.setText("🟢 Đã mở cầu nối trực tiếp /thietlap kèm tín hiệu COM9!")
        self.lbl_web_status.setStyleSheet("color: #00f5d4; font-size: 10px; font-weight: 700;")
        QTimer.singleShot(3500, lambda: (
            self.btn_connect_web.setText("⚡ MỞ THEMOCHI.HUYKHONG.COM/THIETLAP (HIỆN CỔNG COM9)"),
            self.btn_connect_web.setStyleSheet("background: linear-gradient(135deg, #00f5d4 0%, #0284c7 100%); color: #050811; font-weight: 800; font-size: 10.5px; padding: 7px; border: none; border-radius: 7px;")
        ))

    def _install_virtual_com_driver(self):
        self.btn_install_vcom.setText("⏳ Đang cài đặt cổng COM9 <-> COM10 (Chọn Yes ở UAC)...")
        QApplication.processEvents()
        try:
            r = httpx.post(f"{BACKEND_HTTP}/api/mochi/virtual-com/install", timeout=65.0)
            if r.status_code == 200 and r.json().get("driver_installed"):
                self.btn_install_vcom.setText("🟢 Cổng Ảo Windows COM9 Đã Cài & Sẵn Sàng")
                self.lbl_web_status.setText("🟢 Mọi trình duyệt giờ đã thấy THE MOCHI - Neito Agent (COM9)!")
            else:
                self.btn_install_vcom.setText("🔌 Cài Driver Cổng COM9 Ảo Vào Windows (Mọi Trình Duyệt)")
        except Exception:
            self.btn_install_vcom.setText("🔌 Cài Driver Cổng COM9 Ảo Vào Windows (Mọi Trình Duyệt)")
        self.refresh_status()

    def _update_qr_image(self):
        try:
            import io
            import qrcode
            qr = qrcode.QRCode(box_size=3, border=1)
            qr.add_data(self.mobile_url)
            qr.make(fit=True)
            pil_img = qr.make_image(fill_color="#00f5d4", back_color="#0b101c")
            buf = io.BytesIO()
            pil_img.save(buf, format="PNG")
            pix = QPixmap()
            pix.loadFromData(buf.getvalue())
            self.lbl_qr_img.setPixmap(pix.scaled(90, 90, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        except Exception:
            self.lbl_qr_img.setText("QR: " + self.mobile_url)

    def _save_chronos_settings(self):
        name = self.input_ble_name.text().strip() or "THE MOCHI"
        duration = self.spin_duration.value()
        auto_off = self.spin_auto_off.value()
        try:
            httpx.post(
                f"{BACKEND_HTTP}/api/mochi/chronos/config",
                json={
                    "bluetoothName": name,
                    "notifDuration": duration,
                    "bluetooth_auto_off": auto_off,
                },
                timeout=2.0,
            )
            self.btn_save_chronos.setText("✓ Đã Lưu Cấu Hình!")
            QTimer.singleShot(1800, lambda: self.btn_save_chronos.setText("💾 Lưu Thiết Lập Chronos"))
        except Exception:
            self.btn_save_chronos.setText("Lỗi Lưu")
            QTimer.singleShot(1800, lambda: self.btn_save_chronos.setText("💾 Lưu Thiết Lập Chronos"))

    def _copy_web_url(self):
        QApplication.clipboard().setText(self.mobile_url)
        self.btn_copy_link.setText("✓ Đã Copy!")
        QTimer.singleShot(1800, lambda: self.btn_copy_link.setText("📋 Copy Link"))

    def _copy_extension_path(self):
        ext_dir = str((_resolve_app_dir() / "assets" / "mochi_webserial_bridge").resolve())
        QApplication.clipboard().setText(ext_dir)
        self.btn_copy_ext.setText("✓ Đã Copy Path!")
        QTimer.singleShot(1800, lambda: self.btn_copy_ext.setText("🧩 Copy Path Extension"))


class MinimalSettingsPopover(DraggableFramelessWidget):
    """
    Streamlined Settings Popover (Freely Draggable).
    """

    settings_saved = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(298)

        self.soul_dialog = SoulProfileDialog()
        self.mobile_dialog = MobileBridgeDialog()
        self._provider_saved_models: Dict[str, str] = {}

        container = QFrame(self)
        container.setObjectName("settingsFrame")
        container.setStyleSheet(
            """
            QFrame#settingsFrame {
                background-color: rgba(11, 16, 28, 245);
                border: 1.5px solid rgba(0, 229, 255, 115);
                border-radius: 14px;
            }
            QComboBox, QLineEdit {
                background-color: rgba(20, 29, 49, 235);
                border: 1px solid rgba(255, 255, 255, 42);
                border-radius: 8px;
                color: #f8fafc;
                padding: 5px 8px;
                font-size: 12px;
            }
            QComboBox:focus, QLineEdit:focus {
                border: 1px solid #00e5ff;
            }
            QPushButton.togglePill {
                background-color: rgba(25, 35, 58, 220);
                color: #94a3b8;
                border: 1px solid rgba(255, 255, 255, 35);
                border-radius: 8px;
                padding: 5px 5px;
                font-size: 11px;
                font-weight: 700;
            }
            QPushButton.togglePill:checked {
                background-color: rgba(0, 229, 255, 48);
                color: #00e5ff;
                border: 1px solid #00e5ff;
            }
            QPushButton#soulBtn {
                background-color: rgba(192, 132, 252, 42);
                color: #e9d5ff;
                border: 1px solid #c084fc;
                border-radius: 8px;
                padding: 5px 6px;
                font-size: 11px;
                font-weight: 800;
            }
            QPushButton#soulBtn:hover {
                background-color: rgba(192, 132, 252, 85);
            }
            QPushButton#mobileBtn {
                background-color: rgba(0, 245, 212, 38);
                color: #99f6e4;
                border: 1px solid #00f5d4;
                border-radius: 8px;
                padding: 5px 6px;
                font-size: 11px;
                font-weight: 800;
            }
            QPushButton#mobileBtn:hover {
                background-color: rgba(0, 245, 212, 80);
            }
            QPushButton#saveBtn {
                background-color: #00e5ff;
                color: #04101e;
                border: none;
                border-radius: 8px;
                padding: 6px 12px;
                font-weight: 800;
                font-size: 12px;
            }
            QPushButton#saveBtn:hover {
                background-color: #38bdf8;
            }
            QPushButton#closeBtn {
                background: transparent;
                color: #94a3b8;
                border: none;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton#closeBtn:hover {
                color: #ff4d6d;
            }
            """
        )

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.addWidget(container)

        layout = QVBoxLayout(container)
        layout.setContentsMargins(12, 10, 12, 12)
        layout.setSpacing(7)

        # Header
        top_row = QHBoxLayout()
        title = QLabel("⚙️ Cài Đặt (Kéo di chuyển)")
        title.setCursor(Qt.SizeAllCursor)
        title.setStyleSheet("color: #00e5ff; font-size: 13px; font-weight: 800;")
        close_btn = QPushButton("✕")
        close_btn.setObjectName("closeBtn")
        close_btn.setFixedSize(22, 22)
        close_btn.clicked.connect(self.hide)
        top_row.addWidget(title)
        top_row.addStretch()
        top_row.addWidget(close_btn)
        layout.addLayout(top_row)

        # 1. Provider Selector
        self.prov_combo = QComboBox()
        for key, info in PROVIDER_CATALOG.items():
            self.prov_combo.addItem(info["label"], key)
        self.prov_combo.currentIndexChanged.connect(self._on_provider_changed)
        layout.addWidget(self.prov_combo)

        # 2. Model Selector (Editable, updates automatically when Provider changes)
        self.model_combo = QComboBox()
        self.model_combo.setEditable(True)
        layout.addWidget(self.model_combo)

        # 3. Voice Selector Row with Preview Button (27 Voices!)
        voice_row = QHBoxLayout()
        voice_row.setSpacing(4)
        self.voice_combo = QComboBox()
        for v_label, v_id in VOICE_PRESETS:
            self.voice_combo.addItem(f"🔊 {v_label}", v_id)
        self.btn_preview_voice = QPushButton("▶")
        self.btn_preview_voice.setFixedWidth(38)
        self.btn_preview_voice.setToolTip("Nghe thử giọng này")
        self.btn_preview_voice.setStyleSheet(
            "QPushButton { background-color: rgba(0, 229, 255, 45); color: #00e5ff; border: 1px solid #00e5ff; border-radius: 8px; font-weight: bold; } "
            "QPushButton:hover { background-color: rgba(0, 229, 255, 95); color: #ffffff; }"
        )
        self.btn_preview_voice.clicked.connect(self._preview_selected_voice)
        voice_row.addWidget(self.voice_combo, 1)
        voice_row.addWidget(self.btn_preview_voice)
        layout.addLayout(voice_row)

        # 4. API Key Input (Updates placeholder/visibility per provider)
        self.key_input = QLineEdit()
        self.key_input.setEchoMode(QLineEdit.Password)
        self.key_input.setPlaceholderText("API Key")
        layout.addWidget(self.key_input)

        # 5. Toggle Row: [👁️ Mắt] + [🎙️ Mic] + [🔊 Loa] + [✨ Soul] + [📱 ĐT]
        toggles_row = QHBoxLayout()
        toggles_row.setSpacing(4)

        self.btn_eye = QPushButton("👁️ Mắt")
        self.btn_eye.setProperty("class", "togglePill")
        self.btn_eye.setCheckable(True)
        self.btn_eye.setChecked(True)

        self.btn_mic = QPushButton("🎙️ Mic")
        self.btn_mic.setProperty("class", "togglePill")
        self.btn_mic.setCheckable(True)
        self.btn_mic.setChecked(False)

        self.btn_spk = QPushButton("🔊 Loa")
        self.btn_spk.setProperty("class", "togglePill")
        self.btn_spk.setCheckable(True)
        self.btn_spk.setChecked(True)

        self.btn_soul = QPushButton("✨ Soul")
        self.btn_soul.setObjectName("soulBtn")
        self.btn_soul.clicked.connect(self._open_soul_dialog)

        self.btn_mobile = QPushButton("🔌 ESP32")
        self.btn_mobile.setObjectName("mobileBtn")
        self.btn_mobile.setToolTip("Giả lập Phần Cứng ESP32-S3 • xiaozhi.me/console/agents • Chronos BLE • Web /thietlap")
        self.btn_mobile.clicked.connect(self._open_mobile_dialog)

        toggles_row.addWidget(self.btn_eye)
        toggles_row.addWidget(self.btn_mic)
        toggles_row.addWidget(self.btn_spk)
        toggles_row.addWidget(self.btn_soul)
        toggles_row.addWidget(self.btn_mobile)
        layout.addLayout(toggles_row)

        # 6. Action Row: [🛑 Thoát] + [Lưu]
        action_row = QHBoxLayout()
        action_row.setSpacing(6)

        self.quit_btn = QPushButton("🛑 Thoát")
        self.quit_btn.setStyleSheet(
            "QPushButton { background-color: rgba(239, 68, 68, 0.22); color: #f87171; border: 1px solid #ef4444; border-radius: 8px; padding: 6px 10px; font-weight: 700; font-size: 11px; } "
            "QPushButton:hover { background-color: rgba(239, 68, 68, 0.5); color: #ffffff; }"
        )
        self.quit_btn.setToolTip("Đóng ứng dụng hoàn toàn (Kill process)")
        self.quit_btn.clicked.connect(self._quit_app)

        self.save_btn = QPushButton("Lưu")
        self.save_btn.setObjectName("saveBtn")
        self.save_btn.clicked.connect(self._save)

        action_row.addWidget(self.quit_btn)
        action_row.addWidget(self.save_btn, 1)
        layout.addLayout(action_row)

        # 7. Auto-Update Row & Progress Box
        update_frame = QFrame()
        update_frame.setStyleSheet(
            "background-color: rgba(15, 23, 42, 160); border: 1px solid rgba(56, 189, 248, 0.28); border-radius: 9px; padding: 2px;"
        )
        update_vlay = QVBoxLayout(update_frame)
        update_vlay.setContentsMargins(6, 4, 6, 4)
        update_vlay.setSpacing(4)

        up_row = QHBoxLayout()
        self.lbl_app_ver = QLabel(f"📦 Neito v{APP_VERSION}")
        self.lbl_app_ver.setStyleSheet("color: #94a3b8; font-size: 10.5px; font-weight: 700;")

        self.btn_check_update = QPushButton("🔄 Kiểm tra")
        self.btn_check_update.setStyleSheet(
            "QPushButton { background-color: rgba(56, 189, 248, 0.16); color: #38bdf8; border: 1px solid rgba(56, 189, 248, 0.45); border-radius: 6px; padding: 2px 7px; font-size: 10px; font-weight: 700; } "
            "QPushButton:hover { background-color: #38bdf8; color: #020617; }"
        )
        self.btn_check_update.clicked.connect(lambda: self._check_for_updates(silent=False))
        up_row.addWidget(self.lbl_app_ver)
        up_row.addStretch()
        up_row.addWidget(self.btn_check_update)
        update_vlay.addLayout(up_row)

        self.update_info_box = QFrame()
        self.update_info_box.setStyleSheet("background-color: rgba(30, 41, 59, 180); border-radius: 6px;")
        info_lay = QVBoxLayout(self.update_info_box)
        info_lay.setContentsMargins(4, 4, 4, 4)
        info_lay.setSpacing(4)

        self.lbl_update_status = QLabel("")
        self.lbl_update_status.setWordWrap(True)
        self.lbl_update_status.setStyleSheet("color: #38bdf8; font-size: 10.5px; font-weight: 600;")

        self.update_progress_bar = QProgressBar()
        self.update_progress_bar.setFixedHeight(6)
        self.update_progress_bar.setStyleSheet(
            "QProgressBar { background-color: rgba(15, 23, 42, 220); border-radius: 3px; border: none; } "
            "QProgressBar::chunk { background-color: #00f5d4; border-radius: 3px; }"
        )
        self.update_progress_bar.hide()

        self.btn_do_update = QPushButton("⚡ Cập Nhật Ngay")
        self.btn_do_update.setStyleSheet(
            "QPushButton { background: linear-gradient(135deg, #00f5d4 0%, #0284c7 100%); color: #020617; border: none; border-radius: 6px; padding: 5px 8px; font-size: 10.5px; font-weight: 800; } "
            "QPushButton:hover { background: #00f5d4; }"
        )
        self.btn_do_update.clicked.connect(self._apply_current_update)
        self.btn_do_update.hide()

        info_lay.addWidget(self.lbl_update_status)
        info_lay.addWidget(self.update_progress_bar)
        info_lay.addWidget(self.btn_do_update)
        self.update_info_box.hide()
        update_vlay.addWidget(self.update_info_box)

        layout.addWidget(update_frame)

        # Initialize default provider model list
        self._on_provider_changed()

    def _current_provider_key(self) -> str:
        return self.prov_combo.currentData() or "ollama"

    def _on_provider_changed(self):
        prov_key = self._current_provider_key()
        info = PROVIDER_CATALOG.get(prov_key, PROVIDER_CATALOG["ollama"])

        self.model_combo.blockSignals(True)
        self.model_combo.clear()
        for m in info["models"]:
            self.model_combo.addItem(m)
        saved_m = self._provider_saved_models.get(prov_key)
        if saved_m:
            self.model_combo.setCurrentText(saved_m)
        elif info["models"]:
            self.model_combo.setCurrentText(info["models"][0])
        self.model_combo.blockSignals(False)

        if info["needs_key"]:
            self.key_input.setPlaceholderText(f"{info['label']} API Key...")
            self.key_input.show()
        else:
            self.key_input.setPlaceholderText("Local (Không cần API Key)")
            self.key_input.hide()
        self.adjustSize()

    def _open_soul_dialog(self):
        self.mobile_dialog.hide()
        self.soul_dialog.load_soul()
        if not getattr(self.soul_dialog, "_user_moved", False):
            geo = self.geometry()
            sx = max(10, geo.left() - self.soul_dialog.width() - 8)
            sy = max(10, geo.top())
            self.soul_dialog.move(sx, sy)
        self.soul_dialog.show()

    def _open_mobile_dialog(self):
        self.soul_dialog.hide()
        self.mobile_dialog.refresh_status()
        if not getattr(self.mobile_dialog, "_user_moved", False):
            geo = self.geometry()
            mx = max(10, geo.left() - self.mobile_dialog.width() - 8)
            my = max(10, geo.top())
            self.mobile_dialog.move(mx, my)
        self.mobile_dialog.show()

    def load_from_backend(self):
        try:
            r = httpx.get(f"{BACKEND_HTTP}/api/config", timeout=1.5)
            if r.status_code == 200:
                cfg = r.json()
                prov = cfg["llm"].get("active_provider", "mochi_core")
                model_name = cfg["llm"].get("model_name", "")
                self._provider_saved_models[prov] = model_name

                idx = self.prov_combo.findData(prov)
                if idx >= 0:
                    self.prov_combo.setCurrentIndex(idx)
                self._on_provider_changed()
                if model_name:
                    self.model_combo.setCurrentText(model_name)

                self.key_input.setText(cfg["llm"].get("api_key", ""))

                preset = cfg["voice"].get("voice_preset", "edge_tts:vi-VN-HoaiMyNeural")
                v_idx = self.voice_combo.findData(preset)
                if v_idx >= 0:
                    self.voice_combo.setCurrentIndex(v_idx)

                self.btn_eye.setChecked(bool(cfg["vision"].get("enabled", True)))
                self.btn_mic.setChecked(bool(cfg["voice"].get("mic_enabled", True)))
                self.btn_spk.setChecked(bool(cfg["voice"].get("speaker_enabled", True)))
        except Exception:
            pass

    def _preview_selected_voice(self):
        preset = self.voice_combo.currentData() or "edge_tts:vi-VN-HoaiMyNeural"
        self.btn_preview_voice.setText("...")

        def fetch():
            try:
                r = httpx.post(
                    f"{BACKEND_HTTP}/api/voice/preview", json={"preset": preset}, timeout=4.0
                )
                if r.status_code == 200:
                    data = r.json()
                    if data.get("audio_base64"):
                        QTimer.singleShot(0, lambda: self._play_preview_audio(data))
            except Exception:
                pass
            finally:
                QTimer.singleShot(0, lambda: self.btn_preview_voice.setText("▶"))

        threading.Thread(target=fetch, daemon=True).start()

    def _play_preview_audio(self, audio_data: dict):
        p = self.parent()
        if p and hasattr(p, "_on_ws_message"):
            lbl = self.voice_combo.currentText().replace("🔊", "").strip()
            p._on_ws_message(
                {
                    "type": "tts_chunk",
                    "sentence": f"Giọng {lbl}",
                    "audio_base64": audio_data.get("audio_base64"),
                    "format": audio_data.get("format", "mp3"),
                    "lip_sync": audio_data.get("lip_sync"),
                }
            )

    def _save(self):
        prov = self._current_provider_key()
        info = PROVIDER_CATALOG.get(prov, PROVIDER_CATALOG["mochi_core"])
        chosen_model = self.model_combo.currentText().strip() or info["models"][0]
        self._provider_saved_models[prov] = chosen_model

        voice_preset = self.voice_combo.currentData() or "edge_tts:vi-VN-HoaiMyNeural"
        v_engine = "edge_tts"

        patch = {
            "llm": {
                "active_provider": prov,
                "base_url": info["base_url"],
                "model_name": chosen_model,
                "api_key": self.key_input.text().strip(),
            },
            "voice": {
                "engine": v_engine,
                "voice_preset": voice_preset,
                "mic_enabled": self.btn_mic.isChecked(),
                "speaker_enabled": self.btn_spk.isChecked(),
            },
            "vision": {
                "enabled": self.btn_eye.isChecked(),
            },
        }
        try:
            httpx.post(f"{BACKEND_HTTP}/api/config", json=patch, timeout=2.0)
            self.settings_saved.emit(patch)
            self.save_btn.setText("✓ Đã lưu")
            # Immediately speak sample of the newly saved voice for audible feedback
            self._preview_selected_voice()
            QTimer.singleShot(900, lambda: (self.save_btn.setText("Lưu"), self.hide()))
        except Exception:
            self.save_btn.setText("Lỗi")

    def _check_for_updates(self, silent: bool = False):
        self.btn_check_update.setEnabled(False)
        self.btn_check_update.setText("⏳ Đang kiểm...")
        def worker():
            try:
                r = httpx.get(f"{BACKEND_HTTP}/api/updater/check", timeout=6.0)
                if r.status_code == 200:
                    data = r.json()
                else:
                    data = {"ok": False, "error": f"HTTP {r.status_code}"}
            except Exception as e:
                data = {"ok": False, "error": str(e)}
            QTimer.singleShot(0, lambda: self._handle_update_ui(data, silent))
        threading.Thread(target=worker, daemon=True).start()

    def _handle_update_ui(self, data: dict, silent: bool = False):
        self.btn_check_update.setEnabled(True)
        self.btn_check_update.setText("🔄 Kiểm tra")
        if data.get("has_update"):
            latest_v = data.get("latest_version", "")
            self.lbl_app_ver.setText(f"📦 v{APP_VERSION} ➔ 🎉 v{latest_v}")
            self.lbl_app_ver.setStyleSheet("color: #00f5d4; font-size: 10.5px; font-weight: 800;")
            self.lbl_update_status.setText(f"Có bản v{latest_v} mới! ({data.get('download_kind', 'bản mới')})")
            self.btn_do_update.setText(f"⚡ Cập Nhật v{latest_v}")
            self.btn_do_update.show()
            self._target_download_url = data.get("download_url")
            self.update_info_box.show()
            self.adjustSize()
            p = self.parent()
            if silent and p and hasattr(p, "_show_speech_bubble"):
                p._show_speech_bubble(f"Đã có bản Neito v{latest_v} mới, bấm Cài đặt để cập nhật nhé!")
        else:
            if not silent:
                if data.get("ok"):
                    self.lbl_update_status.setText("✅ Bạn đang dùng phiên bản mới nhất!")
                else:
                    self.lbl_update_status.setText(f"⚠️ {data.get('error', 'Không thể kết nối máy chủ cập nhật.')}")
                self.btn_do_update.hide()
                self.update_info_box.show()
                self.adjustSize()

    def _apply_current_update(self):
        url = getattr(self, "_target_download_url", None)
        if not url:
            return
        self.btn_do_update.setEnabled(False)
        self.btn_do_update.setText("⏳ Đang tải...")
        self.update_progress_bar.setValue(5)
        self.update_progress_bar.show()

        try:
            httpx.post(f"{BACKEND_HTTP}/api/updater/download", json={"url": url}, timeout=3.0)
        except Exception:
            pass

        self._update_poll_timer = QTimer(self)
        def poll():
            try:
                r = httpx.get(f"{BACKEND_HTTP}/api/updater/progress", timeout=1.5)
                if r.status_code == 200:
                    st = r.json()
                    status = st.get("status")
                    pct = st.get("percent", 0)
                    self.update_progress_bar.setValue(pct)
                    self.lbl_update_status.setText(f"Đang tải bản cập nhật: {pct}%...")
                    if status == "completed":
                        self._update_poll_timer.stop()
                        self.lbl_update_status.setText("✅ Tải xong! Đang áp dụng...")
                        self.btn_do_update.setText("Khởi động lại...")
                        QTimer.singleShot(600, self._trigger_apply)
                    elif status == "error":
                        self._update_poll_timer.stop()
                        self.lbl_update_status.setText(f"❌ Lỗi: {st.get('error')}")
                        self.btn_do_update.setEnabled(True)
                        self.btn_do_update.setText("Thử lại")
            except Exception:
                pass

        self._update_poll_timer.timeout.connect(poll)
        self._update_poll_timer.start(500)

    def _trigger_apply(self):
        try:
            httpx.post(f"{BACKEND_HTTP}/api/updater/apply", json={}, timeout=2.0)
        except Exception:
            pass

    def _quit_app(self):
        p = self.parent()
        if p and hasattr(p, "quit_application"):
            p.quit_application()
        else:
            QApplication.quit()
            os._exit(0)


class NeitoDesktopOverlay(QWidget):
    """
    True Transparent Frameless Desktop Overlay Window on PC.
    """

    def __init__(self):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setWindowTitle("Neito-Agent Overlay")

        self.signals = BridgeSignals()
        self.signals.ws_message.connect(self._on_ws_message)

        self.ws_loop: Optional[Any] = None
        self.ws_conn = None
        self._is_shutting_down = False
        self.speaker_enabled = True
        self.mic_listener_enabled = False

        self.audio_queue: List[Dict[str, Any]] = []
        self.is_playing_audio = False
        self.lip_curve: List[float] = []
        self.lip_idx = 0
        self._temp_audio_files: List[str] = []

        if HAS_QT_AUDIO:
            self.media_player = QMediaPlayer(self)
            self.audio_output = QAudioOutput(self)
            self.media_player.setAudioOutput(self.audio_output)
            self.media_player.mediaStatusChanged.connect(self._on_media_status)
        else:
            self.media_player = None

        self.lip_timer = QTimer(self)
        self.lip_timer.timeout.connect(self._tick_lipsync)

        self.bubble_hide_timer = QTimer(self)
        self.bubble_hide_timer.setSingleShot(True)
        self.bubble_hide_timer.timeout.connect(self._hide_speech_bubble)

        self.settings_popover = MinimalSettingsPopover()
        self.settings_popover.settings_saved.connect(self._on_settings_saved)

        self._build_ui()
        self._position_bottom_right()
        self.tray_icon: Optional[QSystemTrayIcon] = None
        self._setup_system_tray()
        self._start_ws_thread()
        self._start_mic_listener_thread()
        QTimer.singleShot(5000, lambda: self.settings_popover._check_for_updates(silent=True))

    def _on_settings_saved(self, patch: Dict[str, Any]):
        v = patch.get("voice", {})
        self.speaker_enabled = bool(v.get("speaker_enabled", True))
        self.mic_listener_enabled = bool(v.get("mic_enabled", True))
        if not self.speaker_enabled:
            self._stop_audio()

    def _start_mic_listener_thread(self):
        """Continuously listens to microphone and sends voice transcripts to Neito."""
        def listen_worker():
            try:
                import speech_recognition as sr
                r = sr.Recognizer()
                r.energy_threshold = 280
                r.dynamic_energy_threshold = True
                r.pause_threshold = 0.8
                while not getattr(self, "_is_shutting_down", False):
                    if not self.mic_listener_enabled or self.is_playing_audio:
                        time.sleep(0.5)
                        continue
                    try:
                        with sr.Microphone() as source:
                            audio = r.listen(source, timeout=2.0, phrase_time_limit=8.0)
                            if not self.mic_listener_enabled or self.is_playing_audio or getattr(self, "_is_shutting_down", False):
                                continue
                            text = r.recognize_google(audio, language="vi-VN")
                            if text and text.strip():
                                self._send_ws_json({"type": "voice_transcript", "text": text.strip()})
                    except sr.WaitTimeoutError:
                        pass
                    except sr.UnknownValueError:
                        pass
                    except Exception:
                        time.sleep(0.8)
            except Exception:
                pass

        t = threading.Thread(target=listen_worker, daemon=True)
        t.start()

    def _build_ui(self):
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(8, 8, 8, 8)
        self.main_layout.setSpacing(4)
        self.main_layout.setAlignment(Qt.AlignHCenter | Qt.AlignBottom)

        # 1. Minimal Speech Bubble
        self.speech_bubble = QLabel("")
        self.speech_bubble.setWordWrap(True)
        self.speech_bubble.setMaximumWidth(250)
        self.speech_bubble.setAlignment(Qt.AlignCenter)
        self.speech_bubble.setStyleSheet(
            """
            QLabel {
                background-color: rgba(11, 17, 30, 232);
                color: #f8fafc;
                border: 1.5px solid #00e5ff;
                border-radius: 13px;
                padding: 8px 12px;
                font-size: 13px;
                font-weight: 600;
            }
            """
        )
        self.speech_bubble.hide()
        self.main_layout.addWidget(self.speech_bubble, 0, Qt.AlignHCenter)

        # 2. Living Mascot Widget (Powered by Mochi Firmware Core)
        self.mascot = MascotCanvasWidget(self)
        self.mascot.drag_moved.connect(self._on_mascot_dragged)
        self.mascot.scale_changed.connect(self._on_mascot_scaled)
        self.mascot.touch_triggered.connect(self._on_mascot_touch)
        self.main_layout.addWidget(self.mascot, 0, Qt.AlignHCenter)

        # 3. Foot Controls: [💬] Chat & [⚙️] Setting right next to it
        self.foot_bar = QFrame(self)
        self.foot_bar.setStyleSheet(
            """
            QFrame {
                background-color: rgba(11, 17, 30, 215);
                border: 1px solid rgba(0, 229, 255, 95);
                border-radius: 15px;
            }
            QPushButton {
                background-color: transparent;
                color: #f1f5f9;
                border: none;
                border-radius: 12px;
                padding: 4px 10px;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: rgba(0, 229, 255, 55);
            }
            """
        )
        foot_layout = QHBoxLayout(self.foot_bar)
        foot_layout.setContentsMargins(6, 3, 6, 3)
        foot_layout.setSpacing(4)

        self.btn_chat = QPushButton("💬")
        self.btn_chat.setToolTip("Chat")
        self.btn_chat.clicked.connect(self._toggle_chat_input)

        self.btn_settings = QPushButton("⚙️")
        self.btn_settings.setToolTip("Cài đặt")
        self.btn_settings.clicked.connect(self._toggle_settings)

        self.btn_quit = QPushButton("✕")
        self.btn_quit.setToolTip("Đóng / Thoát hoàn toàn (Quit)")
        self.btn_quit.setStyleSheet(
            "QPushButton { color: #94a3b8; font-size: 13px; font-weight: bold; padding: 4px 8px; } "
            "QPushButton:hover { color: #ff4d6d; background-color: rgba(255, 77, 109, 0.25); border-radius: 10px; }"
        )
        self.btn_quit.clicked.connect(self.quit_application)

        foot_layout.addWidget(self.btn_chat)
        foot_layout.addWidget(self.btn_settings)
        foot_layout.addWidget(self.btn_quit)
        self.main_layout.addWidget(self.foot_bar, 0, Qt.AlignHCenter)

        # 4. Sleek Single-Line Chat Input Box under feet
        self.chat_row_frame = QFrame(self)
        self.chat_row_frame.setStyleSheet(
            """
            QFrame {
                background-color: rgba(11, 17, 30, 235);
                border: 1px solid #00e5ff;
                border-radius: 11px;
            }
            QLineEdit {
                background: transparent;
                border: none;
                color: #ffffff;
                padding: 5px 8px;
                font-size: 12.5px;
            }
            QPushButton {
                background-color: #00e5ff;
                color: #04101e;
                border: none;
                border-radius: 8px;
                padding: 4px 9px;
                font-weight: 800;
            }
            """
        )
        chat_layout = QHBoxLayout(self.chat_row_frame)
        chat_layout.setContentsMargins(6, 4, 6, 4)
        chat_layout.setSpacing(4)

        self.chat_input = QLineEdit()
        self.chat_input.setFixedWidth(185)
        self.chat_input.setPlaceholderText("Nói với Neito...")
        self.chat_input.returnPressed.connect(self._send_chat)

        self.btn_send = QPushButton("➤")
        self.btn_send.clicked.connect(self._send_chat)

        chat_layout.addWidget(self.chat_input)
        chat_layout.addWidget(self.btn_send)
        self.chat_row_frame.hide()
        self.main_layout.addWidget(self.chat_row_frame, 0, Qt.AlignHCenter)

    def _on_mascot_touch(self, kind: str):
        """Routes 1-Tap, Double-Tap, and Long-Touch to MochiFirmwareCoreBrain."""
        self._send_ws_json({"type": "mochi_touch", "kind": kind})

    def _position_bottom_right(self):
        screen = QApplication.primaryScreen().availableGeometry()
        self.adjustSize()
        x = screen.right() - self.width() - 40
        y = screen.bottom() - self.height() - 40
        self.move(max(20, x), max(20, y))

    def _on_mascot_dragged(self, diff: QPoint):
        self.move(self.pos() + diff)
        if self.settings_popover.isVisible():
            self._reposition_settings_popover()

    def _reanchor_around_mascot(self, func=None):
        """
        Executes layout modification `func` while ensuring the Mascot's global center
        remains 100% stationary on the desktop screen down to the exact pixel.
        """
        center_before = self.mascot.mapToGlobal(QPoint(self.mascot.width() // 2, self.mascot.height() // 2))
        if func:
            func()
        self.adjustSize()
        center_after = self.mascot.mapToGlobal(QPoint(self.mascot.width() // 2, self.mascot.height() // 2))
        diff = center_before - center_after
        self.move(self.pos() + diff)
        if hasattr(self, "settings_popover") and self.settings_popover.isVisible():
            self._reposition_settings_popover()

    def _on_mascot_wheel_scale(self, new_scale: float):
        self._reanchor_around_mascot(lambda: self.mascot.set_scale(new_scale))

    def _on_mascot_scaled(self, _new_scale: float):
        pass

    def _show_speech_bubble(self, text: str):
        import re
        clean = re.sub(r"<think>.*?</think>", "", str(text or ""), flags=re.DOTALL | re.IGNORECASE)
        clean = re.sub(r"\[[^\]]*\]", "", clean)
        clean = re.sub(r"\(\s*(?:UwU|OwO|>\.<|\^_\^|T_T|-_-)\s*\)", "", clean, flags=re.IGNORECASE)
        clean = re.sub(r"[\U00010000-\U0010ffff\u2600-\u27bf\ufe0f\u200d]+", "", clean)
        clean = re.sub(r"[*_~`#>|]+", "", clean).strip()
        if not clean:
            return
        def _show():
            self.speech_bubble.setText(clean)
            self.speech_bubble.show()
        self._reanchor_around_mascot(_show)

    def _hide_speech_bubble(self):
        self._reanchor_around_mascot(lambda: self.speech_bubble.hide())

    def _toggle_chat_input(self):
        def _toggle():
            if self.chat_row_frame.isVisible():
                self.chat_row_frame.hide()
            else:
                self.chat_row_frame.show()
                self.chat_input.setFocus()
        self._reanchor_around_mascot(_toggle)

    def _toggle_settings(self):
        if self.settings_popover.isVisible():
            self.settings_popover.hide()
            self.settings_popover.soul_dialog.hide()
            self.settings_popover.mobile_dialog.hide()
        else:
            self.settings_popover.load_from_backend()
            self._reposition_settings_popover()
            self.settings_popover.show()

    def _reposition_settings_popover(self):
        if not getattr(self.settings_popover, "_user_moved", False):
            geo = self.geometry()
            px = max(10, geo.left() - self.settings_popover.width() - 10)
            py = max(10, geo.bottom() - self.settings_popover.height())
            self.settings_popover.move(px, py)

    def _send_chat(self):
        text = self.chat_input.text().strip()
        if not text:
            return
        self.chat_input.clear()
        self._send_ws_json({"type": "chat", "text": text})

    def _start_ws_thread(self):
        def runner():
            import asyncio
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self.ws_loop = loop
            loop.run_until_complete(self._ws_client_loop())

        t = threading.Thread(target=runner, daemon=True)
        t.start()

    async def _ws_client_loop(self):
        import asyncio
        while True:
            try:
                async with websockets.connect(BACKEND_WS) as ws:
                    self.ws_conn = ws
                    self.signals.connection_changed.emit(True)
                    async for raw in ws:
                        data = json.loads(raw)
                        self.signals.ws_message.emit(data)
            except Exception:
                self.ws_conn = None
                self.signals.connection_changed.emit(False)
                await asyncio.sleep(1.5)

    def _send_ws_json(self, payload: Dict[str, Any]):
        if self.ws_conn and self.ws_loop:
            import asyncio
            asyncio.run_coroutine_threadsafe(
                self.ws_conn.send(json.dumps(payload)),
                self.ws_loop,
            )

    def _on_ws_message(self, msg: Dict[str, Any]):
        mtype = msg.get("type", "")

        if mtype == "hello":
            cfg = msg.get("config", {})
            scale = cfg.get("mascot", {}).get("scale", 1.0)
            self.speaker_enabled = bool(cfg.get("voice", {}).get("speaker_enabled", True))
            self.mascot.set_scale(scale)
            mochi_info = msg.get("mochi", {})
            nvs = mochi_info.get("nvs", {})
            if isinstance(nvs, dict) and nvs:
                self._apply_mochi_nvs(nvs)

        elif mtype == "emotion":
            self.mascot.set_emotion(msg.get("emotion", "idle"))

        elif mtype == "telemetry_tick":
            self.mascot.update_neural_state(msg.get("neural", {}), msg.get("resources"))

        elif mtype == "protocol_switched":
            self.mascot.set_emotion("happy")
            QTimer.singleShot(1200, lambda: self.mascot.set_emotion("idle"))

        elif mtype == "mochi_firmware_event":
            ev = msg.get("event", "")
            face = msg.get("face", "")
            dmode = msg.get("display_mode", "face")
            emo = msg.get("emotion", "happy")
            text = (msg.get("text") or "").strip()
            nvs = msg.get("nvs")
            if isinstance(nvs, dict) and nvs:
                self._apply_mochi_nvs(nvs)

            if ev == "chronos_notification":
                self.mascot.mochi_player.show_phone_notification(
                    msg.get("app", "Phone"),
                    msg.get("title", ""),
                    msg.get("message", ""),
                    float(msg.get("duration_sec", 5.0)),
                )
            elif ev == "chronos_navigation":
                self.mascot.mochi_player.show_navigation_hud(
                    msg.get("direction", "STRAIGHT"),
                    msg.get("distance", "150m"),
                    msg.get("street", "Google Maps"),
                    float(msg.get("duration_sec", 8.0)),
                )
            elif dmode == "show_clock" or face == "show_clock":
                self.mascot.mochi_player.toggle_clock_mode(8.0)
            elif dmode == "cpuz" or face == "cpuz":
                self.mascot.mochi_player.set_face("cpuz", loop=False)
            elif face:
                self.mascot.set_mochi_face(face, loop=(ev in ("serial_default_changed", "serial_reset")))

            self.mascot.set_emotion(emo)
            if text:
                self._show_speech_bubble(text)
                self.bubble_hide_timer.start(5500)

            audio_pkg = msg.get("audio")
            if audio_pkg and audio_pkg.get("audio_base64"):
                self.audio_queue.append(audio_pkg)
                if not self.is_playing_audio:
                    self._play_next_chunk()

        elif mtype == "speech_start":
            self._stop_audio()
            face = msg.get("face", "")
            if face:
                self.mascot.set_mochi_face(face, loop=False)
            self.mascot.set_emotion(msg.get("emotion", "speaking"))

        elif mtype == "tts_chunk":
            self.audio_queue.append(msg)
            if not self.is_playing_audio:
                self._play_next_chunk()

        elif mtype == "tts" and msg.get("state") == "stop":
            self._stop_audio()

    def _apply_mochi_nvs(self, nvs: Dict[str, Any]):
        player = getattr(self.mascot, "mochi_player", None)
        if not player:
            return
        if "gif_default" in nvs and nvs["gif_default"]:
            player.set_default_face(str(nvs["gif_default"]))
        if "gif_speed" in nvs:
            try:
                player.set_speed_pct(int(nvs["gif_speed"]))
            except Exception:
                pass
        if "gif_negative" in nvs:
            val = str(nvs["gif_negative"]).lower()
            player.set_inverted(val in ("true", "1", "yes"))
        self.mascot.update()

    def _stop_audio(self):
        self.audio_queue.clear()
        self.is_playing_audio = False
        self.lip_timer.stop()
        self.mascot.mouth_open = 0.0
        if self.media_player:
            self.media_player.stop()
        if os.name == "nt":
            try:
                import ctypes
                import winsound
                winsound.PlaySound(None, winsound.SND_PURGE)
                ctypes.windll.winmm.mciSendStringW("close neito_audio", None, 0, 0)
            except Exception:
                pass

    def _play_next_chunk(self):
        if not self.audio_queue:
            self.is_playing_audio = False
            self.lip_timer.stop()
            self.mascot.mouth_open = 0.0
            self.mascot.set_emotion("idle")
            self.bubble_hide_timer.start(4000)
            return

        self.is_playing_audio = True
        pkg = self.audio_queue.pop(0)

        # Synchronize speech bubble: display the sentence at the EXACT moment audio plays
        sent_txt = (pkg.get("sentence") or pkg.get("text") or "").strip()
        if sent_txt:
            self._show_speech_bubble(sent_txt)
            self.bubble_hide_timer.stop()

        self.lip_curve = pkg.get("lip_sync") or [0.4, 0.8, 0.3, 0.0]
        self.lip_idx = 0
        self.lip_timer.start(33)

        b64 = pkg.get("audio_base64")
        fmt = pkg.get("format", "mp3")

        # Accurately estimate duration from audio bytes or lip-sync frames
        if b64:
            raw_len = len(b64) * 3 // 4
            if fmt == "wav":
                est_ms = max(750, int((raw_len / 16000.0) * 1000.0))
            else:
                est_ms = max(800, int((raw_len / 6000.0) * 1000.0))
            duration_ms = max(est_ms, len(self.lip_curve) * 33)
        else:
            duration_ms = max(850, len(self.lip_curve) * 35)

        if b64 and self.speaker_enabled:
            try:
                raw_audio = base64.b64decode(b64)
                is_wav = fmt == "wav" or raw_audio[:4] == b"RIFF"
                ext = ".wav" if is_wav else ".mp3"
                fd, tmp_path = tempfile.mkstemp(suffix=ext, prefix="neito_tts_")
                os.close(fd)
                Path(tmp_path).write_bytes(raw_audio)
                self._temp_audio_files.append(tmp_path)

                if is_wav and os.name == "nt":
                    import winsound
                    winsound.PlaySound(tmp_path, winsound.SND_FILENAME | winsound.SND_ASYNC)
                    QTimer.singleShot(duration_ms, self._play_next_chunk)
                    return
                elif self.media_player:
                    self.media_player.setSource(QUrl.fromLocalFile(tmp_path))
                    self.media_player.play()
                    return
                elif os.name == "nt":
                    import ctypes
                    winmm = ctypes.windll.winmm
                    winmm.mciSendStringW("close neito_audio", None, 0, 0)
                    winmm.mciSendStringW(f'open "{tmp_path}" type mpegvideo alias neito_audio', None, 0, 0)
                    winmm.mciSendStringW("play neito_audio", None, 0, 0)
            except Exception:
                pass

        QTimer.singleShot(duration_ms, self._play_next_chunk)

    def _on_media_status(self, status):
        if HAS_QT_AUDIO and status in (
            QMediaPlayer.MediaStatus.EndOfMedia,
            QMediaPlayer.MediaStatus.InvalidMedia,
        ):
            self._play_next_chunk()

    def _tick_lipsync(self):
        if self.lip_idx < len(self.lip_curve):
            self.mascot.mouth_open = float(self.lip_curve[self.lip_idx])
            self.lip_idx += 1
    def _setup_system_tray(self):
        """Initializes system tray icon with rich controls and full application termination."""
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return

        tray_icon = create_mochi_tray_icon()
        self.tray_icon = QSystemTrayIcon(tray_icon, self)
        self.tray_icon.setToolTip("Neito Agent • Mochi AI")

        tray_menu = QMenu()
        tray_menu.setStyleSheet(
            """
            QMenu {
                background-color: #0d1527;
                color: #f1f5f9;
                border: 1px solid #00e5ff;
                border-radius: 8px;
                padding: 6px;
                font-size: 13px;
                font-weight: 500;
            }
            QMenu::item {
                padding: 6px 20px 6px 14px;
                border-radius: 4px;
            }
            QMenu::item:selected {
                background-color: rgba(0, 229, 255, 40);
                color: #00f5d4;
            }
            QMenu::separator {
                height: 1px;
                background: rgba(0, 229, 255, 40);
                margin: 4px 6px;
            }
            """
        )

        act_toggle = tray_menu.addAction("👁️ Ẩn / Hiện Mascot")
        act_toggle.triggered.connect(self._toggle_overlay_visibility)

        act_chat = tray_menu.addAction("💬 Mở ô chat")
        act_chat.triggered.connect(self._show_and_focus_chat)

        act_settings = tray_menu.addAction("⚙️ Cài đặt")
        act_settings.triggered.connect(self._toggle_settings)

        act_phone = tray_menu.addAction("📱 App Điện Thoại (QR)")
        act_phone.triggered.connect(self._open_mobile_companion)

        tray_menu.addSeparator()

        mic_label = "🎙️ Micro: Bật" if self.mic_listener_enabled else "🎙️ Micro: Tắt"
        self.tray_act_mic = QAction(mic_label, self)
        self.tray_act_mic.setCheckable(True)
        self.tray_act_mic.setChecked(self.mic_listener_enabled)
        self.tray_act_mic.triggered.connect(self._toggle_mic_from_tray)
        tray_menu.addAction(self.tray_act_mic)

        self.tray_act_spk = QAction("🔊 Loa: Bật", self)
        self.tray_act_spk.setCheckable(True)
        self.tray_act_spk.setChecked(self.speaker_enabled)
        self.tray_act_spk.triggered.connect(self._toggle_spk_from_tray)
        tray_menu.addAction(self.tray_act_spk)

        tray_menu.addSeparator()

        act_quit = tray_menu.addAction("🛑 Thoát Hoàn Toàn (Quit)")
        act_quit.triggered.connect(self.quit_application)

        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self._on_tray_activated)
        self.tray_icon.show()

        # Display brief notification bubble on startup
        QTimer.singleShot(
            1500,
            lambda: self.tray_icon.showMessage(
                "Neito Agent",
                "Mascot đang chạy. Chuột phải vào Mascot hoặc Tray Icon để Thoát hoàn toàn.",
                QSystemTrayIcon.Information,
                2500,
            ) if self.tray_icon else None,
        )

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason):
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self._toggle_overlay_visibility()

    def _toggle_overlay_visibility(self):
        if self.isVisible():
            self.hide()
            self.settings_popover.hide()
        else:
            self.show()
            self.raise_()
            self.activateWindow()

    def _show_and_focus_chat(self):
        if not self.isVisible():
            self.show()
        self.raise_()
        self.activateWindow()
        self.chat_row_frame.show()
        self.chat_input.setFocus()
        self.adjustSize()

    def _open_mobile_companion(self):
        self.settings_popover.mobile_dialog.show()
        self.settings_popover.mobile_dialog.raise_()
        self.settings_popover.mobile_dialog.activateWindow()

    def _toggle_mic_from_tray(self):
        self.mic_listener_enabled = self.tray_act_mic.isChecked()
        self.tray_act_mic.setText("🎙️ Micro: Bật" if self.mic_listener_enabled else "🎙️ Micro: Tắt")
        self.settings_popover.btn_mic.setChecked(self.mic_listener_enabled)

    def _toggle_spk_from_tray(self):
        self.speaker_enabled = self.tray_act_spk.isChecked()
        self.tray_act_spk.setText("🔊 Loa: Bật" if self.speaker_enabled else "🔊 Loa: Tắt")
        self.settings_popover.btn_spk.setChecked(self.speaker_enabled)
        if not self.speaker_enabled:
            self._stop_audio()

    def quit_application(self):
        """Completely terminates audio, mic listener, tray icon, and exits all processes immediately."""
        self._is_shutting_down = True
        self.mic_listener_enabled = False
        try:
            self._stop_audio()
        except Exception:
            pass
        if self.tray_icon:
            self.tray_icon.hide()
        for p in self._temp_audio_files:
            try:
                if os.path.exists(p):
                    os.remove(p)
            except Exception:
                pass
        QApplication.quit()
        os._exit(0)

    def closeEvent(self, event):
        self.quit_application()
        event.accept()


def run_native_overlay():
    app = QApplication.instance() or QApplication(sys.argv)
    overlay = NeitoDesktopOverlay()
    overlay.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    run_native_overlay()
