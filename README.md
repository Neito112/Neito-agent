# ⚡ Neito-Agent — Realtime Multimodal AI Desktop Companion

**Nhanh • Mạnh • Văn phong tinh gọn • Tối ưu song song khi chơi Game (~45MB RAM)**

---

## 🏗️ Kiến trúc Hệ thống (Full-Stack)

1. **Mascot Overlay (`desktop/src/mascot.js` & `desktop/main.js`)**:
   - Quả bóng tròn phong cách **Xiaozhi** với đôi mắt to biểu cảm (liếc theo chuột, chớp mắt tự nhiên, 7 trạng thái cảm xúc: `IDLE`, `LISTENING`, `THINKING`, `SPEAKING`, `HAPPY`, `ALERT`, `SCANNING`) và miệng nhép môi theo biên độ sóng âm thời gian thực (`30Hz Lip-Sync Envelope`).
   - **Thao tác chuột giữa (Scroll Wheel Scale)**: Trỏ chuột vào Mascot và lăn chuột giữa để phóng to/thu nhỏ mượt mà (`50%` – `240%`). Giữ chuột trái để kéo thả tới mọi vị trí.
   - **Nút điều khiển dưới chân Mascot**:
     - `💬 Chat`: Mở/đóng ô nhập chat nhanh ngay dưới chân mascot.
     - `⚙️ Setting`: Nằm ngay cạnh nút Chat, mở bảng **Control Center & Reflex Protocol Studio**.
     - `🎙️ Mic`: Bật/tắt tai nghe **Xiaozhi VAD** (hỗ trợ ngắt lời **Barge-in** tức thì).
     - `👁️ Eye`: Kích hoạt mắt **YOLO11n** quét màn hình ngay lập tức.
   - **Hộp thoại phản hồi (Speech Bubble)**: Xuất hiện đồng thời với giọng nói ngay trên đầu Mascot kèm chỉ số độ trễ (`ms`) và tên bộ giao thức đang nạp.

2. **Bộ Não Phản Xạ Vĩnh Viễn (`backend/core/protocol_engine.py` & `backend/core/window_watcher.py`)**:
   - **Win32 Active Window Watcher (`<0.05% CPU`)**: Tự động nhận diện tiến trình đang mở trên máy tính (`eldenring.exe`, `nioh2.exe`, `valorant.exe`, `league of legends.exe`, `code.exe`...) để nạp đúng **Protocol Cartridge** tương ứng.
   - **Zero-Latency Reflex (`<15ms`)**: Phản xạ tức thì với các tình huống trên màn hình hoặc câu hỏi chiến thuật trong game mà không cần chờ LLM.
   - **Autonomous Protocol Synthesizer (`backend/brain/llm_router.py`)**: Kết hợp đa nhà cung cấp LLM (**Ollama Local, LM Studio/vLLM, OpenAI, Gemini, DeepSeek, Groq**) cùng công cụ thị giác để tự tạo và lưu vĩnh viễn các bộ giao thức mới tại `backend/protocols/*.json`.

3. **Hệ thống Thị giác Kép (`backend/vision/eye_engine.py`)**:
   - **Mắt thời gian thực (`YOLO11n` + Gaming Eco HUD Scanner)**: Quét vùng cửa sổ đang active ở chế độ tiết kiệm tài nguyên (`1 FPS Eco`, `4 FPS Balanced`, `10 FPS Combat`).
   - **Tự huấn luyện mắt (`YOLO-World`)**: Nhận danh sách vật thể mở (open-vocabulary prompts), tự động chụp & gán nhãn bounding box chuẩn YOLO vào `backend/datasets/<protocol_id>/` kèm lệnh distill sang `YOLO11n`.

4. **Giọng nói & Tai nghe (`backend/voice/omnivoice_tts.py` & `backend/voice/xiaozhi_ear.py`)**:
   - **OmniVoice Streaming TTS**: Hỗ trợ OmniVoice Server + tầng dự phòng Neural TTS (`vi-VN-HoaiMyNeural`) và WebSpeech Offline kèm bộ tạo biên độ nhép môi tự động.
   - **Xiaozhi Ear v2**: Giao thức WebSocket song công (`/ws/xiaozhi`) với cơ chế VAD và Barge-in ngắt lời.

---

---

## 📥 Tải Về Cài Đặt (Downloads & Releases)

Truy cập mục [Releases](https://github.com/Neito112/Neito-agent/releases) để tải về:
* **Bản Setup Installer (`Neito-Setup-windows-x64.exe`)**: Cài đặt vào hệ thống Windows, tự động tạo biểu tượng ngoài màn hình Desktop và Start Menu.
* **Bản Portable (`Neito-Portable-windows-x64.zip`)**: Giải nén và chạy ngay `Neito.exe` mà không cần cài đặt hay cấu hình môi trường.

---

## 🚀 Cách Khởi Chạy Nhanh Cho Lập Trình Viên

### Cách 1: Chạy trực tiếp từ mã nguồn Python
```powershell
# Cài đặt môi trường
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt

# Khởi chạy ứng dụng
python run_neito.py
```

### Cách 2: Tự đóng gói bản Portable & Setup Installer cục bộ
```powershell
# Đóng gói bản Portable
pyinstaller --noconfirm neito.spec

# Tạo bộ cài đặt Windows Setup (cần cài Inno Setup)
& "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer.iss
```
Bản dựng hoàn chỉnh sẽ nằm tại thư mục `dist/` và `dist-installer/`.

