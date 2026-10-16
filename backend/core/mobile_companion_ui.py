"""
Neito-Agent: The Mochi Web Controller & Chronos Smartphone Companion (`/thietlap` & `/mobile`)
=============================================================================================
Ported directly from `https://themochi.huykhong.com/thietlap`:
Full Web Controller running against the virtual ESP32-C3 firmware core:
- Tab 1: Điều chỉnh GIF (Tốc độ GIF, Delay giữa các GIF, GIF âm bản, GIF mặc định, Intro, Touch)
- Tab 2: Điều chỉnh âm thanh (Âm lượng, Intro sound, Touch sound, Notification sound, 27 âm thanh gốc)
- Tab 3: Thiết lập Chronos (Tên Bluetooth, Thời gian thông báo, Tự tắt BLE, Hướng dẫn kết nối)
- Tab 4: Thao tác & Phần cứng (Reset Mochi, Lưu cài đặt firmware NVS)
"""

MOBILE_COMPANION_HTML = """<!DOCTYPE html>
<html lang="vi" data-bs-theme="dark">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>THE MOCHI WEB CONTROLLER • NEITO</title>
<link href="https://cdnjs.cloudflare.com/ajax/libs/bootstrap/5.3.2/css/bootstrap.min.css" rel="stylesheet">
<link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css" rel="stylesheet">
<style>
  :root {
    --bg-grad: linear-gradient(135deg, #0b101c 0%, #111a2e 50%, #080c16 100%);
    --card-bg: rgba(17, 26, 46, 0.88);
    --border-color: rgba(0, 245, 212, 0.28);
    --accent-cyan: #00e5ff;
    --accent-mint: #00f5d4;
    --accent-purple: #c084fc;
    --accent-pink: #ff4d6d;
    --text-main: #f1f5f9;
  }
  * { box-sizing: border-box; -webkit-tap-highlight-color: transparent; }
  body {
    background: var(--bg-grad);
    min-height: 100vh;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    color: var(--text-main);
    padding-bottom: 40px;
  }
  .navbar-mochi {
    background: rgba(9, 14, 26, 0.94);
    border-bottom: 1.5px solid var(--border-color);
    backdrop-filter: blur(12px);
    padding: 10px 16px;
  }
  .brand-title {
    font-size: 15px; font-weight: 800; color: var(--accent-mint); letter-spacing: 0.6px;
  }
  .status-dot {
    width: 9px; height: 9px; border-radius: 50%; display: inline-block;
    background: #10b981; box-shadow: 0 0 10px #10b981; margin-right: 6px;
  }
  .glass-card {
    background: var(--card-bg);
    border: 1px solid var(--border-color);
    border-radius: 14px;
    padding: 16px;
    margin-bottom: 14px;
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.35);
  }
  .nav-pills .nav-link {
    border-radius: 10px;
    margin: 2px 4px;
    color: #94a3b8;
    font-weight: 600;
    font-size: 12.5px;
    background: rgba(20, 31, 56, 0.6);
    border: 1px solid transparent;
  }
  .nav-pills .nav-link.active {
    background: linear-gradient(135deg, rgba(0, 245, 212, 0.22) 0%, rgba(0, 229, 255, 0.28) 100%);
    border-color: var(--accent-mint);
    color: var(--accent-mint);
  }
  .form-control, .form-select {
    background: rgba(13, 21, 38, 0.9);
    border: 1px solid rgba(0, 245, 212, 0.3);
    border-radius: 8px;
    color: #fff;
    font-size: 12.5px;
  }
  .form-control:focus, .form-select:focus {
    background: rgba(17, 27, 50, 0.95);
    border-color: var(--accent-mint);
    color: #fff;
    box-shadow: 0 0 0 0.2rem rgba(0, 245, 212, 0.2);
  }
  .form-range::-webkit-slider-thumb {
    background: var(--accent-mint);
  }
  .btn-elegant {
    background: linear-gradient(135deg, #00f5d4 0%, #00b4d8 100%);
    color: #070b14;
    font-weight: 700;
    border: none;
    border-radius: 10px;
    padding: 8px 16px;
    font-size: 12.5px;
    transition: transform 0.1s ease;
  }
  .btn-elegant:active { transform: scale(0.96); }
  .grid-faces {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(92px, 1fr));
    gap: 7px;
    max-height: 320px;
    overflow-y: auto;
    padding-right: 4px;
  }
  .btn-face {
    background: rgba(18, 28, 51, 0.85);
    color: #e2e8f0;
    border: 1px solid rgba(56, 189, 248, 0.25);
    border-radius: 8px;
    padding: 7px 4px;
    font-size: 11px;
    font-weight: 600;
    text-align: center;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .btn-face:active, .btn-face.active {
    background: rgba(0, 245, 212, 0.25);
    border-color: var(--accent-mint);
    color: var(--accent-mint);
  }
  .step-box {
    background: rgba(13, 21, 38, 0.7);
    border-left: 3px solid var(--accent-mint);
    border-radius: 8px;
    padding: 10px 12px;
    margin-bottom: 10px;
    font-size: 12px;
  }
</style>
</head>
<body>

<!-- Top Navigation Bar -->
<div class="navbar-mochi d-flex justify-content-between align-items-center">
  <div class="d-flex align-items-center">
    <span class="status-dot"></span>
    <span class="brand-title">THE MOCHI WEB CONTROLLER</span>
  </div>
  <div>
    <span class="badge bg-secondary me-1" id="macBadge">MAC: ECDA3B9F2A10</span>
    <span class="badge bg-success" id="fwBadge">v4.3.2</span>
  </div>
</div>

<div class="container mt-3">
  <!-- Main Tabs -->
  <ul class="nav nav-pills justify-content-center mb-3" id="controllerTabs">
    <li class="nav-item">
      <button class="nav-link active" data-bs-toggle="pill" data-bs-target="#tab-chronos">
        <i class="fas fa-mobile-alt me-1"></i>Chronos & ĐT
      </button>
    </li>
    <li class="nav-item">
      <button class="nav-link" data-bs-toggle="pill" data-bs-target="#tab-gif">
        <i class="fas fa-image me-1"></i>Điều chỉnh GIF
      </button>
    </li>
    <li class="nav-item">
      <button class="nav-link" data-bs-toggle="pill" data-bs-target="#tab-sound">
        <i class="fas fa-volume-up me-1"></i>Âm thanh
      </button>
    </li>
    <li class="nav-item">
      <button class="nav-link" data-bs-toggle="pill" data-bs-target="#tab-actions">
        <i class="fas fa-sliders-h me-1"></i>Lưu & Phần cứng
      </button>
    </li>
  </ul>

  <div class="tab-content">
    <!-- TAB 1: THIẾT LẬP CHRONOS & HƯỚNG DẪN GHÉP NỐI ĐIỆN THOẠI -->
    <div class="tab-pane fade show active" id="tab-chronos">
      <!-- 1. Phone Connect Action Bar -->
      <div class="glass-card text-center" style="border-color: var(--accent-mint); background: rgba(0, 245, 212, 0.08);">
        <h6 class="text-mint mb-2"><i class="fas fa-plug me-2"></i>Trạng Thái Ghép Nối Chronos (Điện Thoại)</h6>
        <div class="mb-3">
          <span class="badge bg-success p-2" id="webConnStatusBadge" style="font-size: 13px;">● Sẵn sàng kết nối qua Chronos App</span>
        </div>
        <div class="d-flex justify-content-center gap-2 mb-2">
          <button class="btn btn-elegant btn-lg" id="btnWebTogglePhoneConn" onclick="toggleWebPhoneConnect()">
            <i class="fas fa-bolt me-1"></i>KẾT NỐI ĐIỆN THOẠI (CHRONOS)
          </button>
        </div>
        <div class="d-flex justify-content-center gap-2">
          <button class="btn btn-sm btn-outline-info" onclick="sendTestNotif()">
            <i class="fas fa-bell me-1"></i>Thử Bắn Thông Báo Lên Mascot
          </button>
          <button class="btn btn-sm btn-outline-warning" onclick="sendTestNav()">
            <i class="fas fa-location-arrow me-1"></i>Thử Dẫn Đường Google Maps
          </button>
        </div>
      </div>

      <div class="glass-card">
        <h6 class="text-info mb-3"><i class="fas fa-bluetooth-b me-2"></i>Cấu Hình Bluetooth Chronos (ESP32)</h6>
        
        <div class="mb-3">
          <label class="form-label text-light">Tên Bluetooth thiết bị:</label>
          <input type="text" class="form-control" id="cfg_bluetoothName" value="THE MOCHI">
          <small class="text-secondary">Tên thiết bị phát ra để app Chronos trên điện thoại quét thấy.</small>
        </div>

        <div class="row">
          <div class="col-6 mb-3">
            <label class="form-label text-light">Hiện thông báo: <span id="lbl_notifDuration" class="text-info">5</span>s</label>
            <input type="range" class="form-range" id="cfg_notifDuration" min="1" max="10" value="5">
          </div>
          <div class="col-6 mb-3">
            <label class="form-label text-light">Tự tắt BLE: <span id="lbl_bluetoothAutoOff" class="text-info">0</span> phút</label>
            <input type="range" class="form-range" id="cfg_bluetooth_auto_off" min="0" max="10" value="0">
          </div>
        </div>

        <button class="btn btn-elegant w-100" id="btnSaveChronos" onclick="saveChronosConfig()">
          <i class="fas fa-save me-1"></i>Lưu Thiết Lập Chronos
        </button>
      </div>

      <!-- Chronos Connection Guide -->
      <div class="glass-card">
        <div class="d-flex justify-content-between align-items-center mb-2">
          <h6 class="text-light m-0"><i class="fas fa-book me-2"></i>Hướng Dẫn Kết Nối App Chronos (Android)</h6>
          <a class="btn btn-sm btn-outline-info" href="https://play.google.com/store/apps/details?id=fbiego.chronos" target="_blank">
            <i class="fas fa-download me-1"></i>Tải Chronos
          </a>
        </div>

        <div class="step-box">
          <strong>Bước 1:</strong> Tải và mở app <strong>Chronos</strong> (nhà phát hành <em>fbiego</em>) trên Google Play.
        </div>
        <div class="step-box">
          <strong>Bước 2:</strong> Ở màn hình <strong>Đồng hồ</strong>, nhấn <strong>Tìm kiếm</strong> -> Chọn thiết bị <strong>"THE MOCHI"</strong>.
        </div>
        <div class="step-box">
          <strong>Bước 3:</strong> Cấp quyền <strong>Truy cập thông báo</strong> để Mochi nhận tin nhắn, cuộc gọi, biến động số dư MoMo/Ngân hàng.
        </div>
        <div class="step-box">
          <strong>Bước 4:</strong> Cuộn xuống <strong>Trình quản lý ESP32</strong> -> Bật <strong>Điều hướng</strong> ON để nhận chỉ đường Google Maps!
        </div>
      </div>

      <!-- Quick Message to PC Mascot -->
      <div class="glass-card">
        <h6 class="text-light mb-2"><i class="fas fa-comment-dots me-2"></i>Nhắn Tin Cho Mascot PC</h6>
        <div class="d-flex gap-2">
          <input type="text" class="form-control" id="chatInput" placeholder="Nhập tin nhắn..." onkeydown="if(event.key==='Enter')sendChat()">
          <button class="btn btn-elegant" onclick="sendChat()">Gửi</button>
        </div>
      </div>
    </div>

    <!-- TAB 2: ĐIỀU CHỈNH GIF -->
    <div class="tab-pane fade" id="tab-gif">
      <div class="glass-card">
        <h6 class="text-light mb-3"><i class="fas fa-tachometer-alt me-2"></i>Tốc Độ & Thời Gian</h6>
        <div class="mb-3">
          <label class="form-label text-light">Tốc độ GIF: <span id="lbl_gifSpeed" class="text-info">42</span></label>
          <input type="range" class="form-range" id="cfg_gif_speed" min="20" max="150" value="42">
        </div>
        <div class="mb-3">
          <label class="form-label text-light">Delay giữa các GIF: <span id="lbl_gifDelay" class="text-info">10</span>s</label>
          <input type="range" class="form-range" id="cfg_gif_delay" min="3" max="60" value="10">
        </div>
        <div class="form-check form-switch mb-2">
          <input class="form-check-input" type="checkbox" id="cfg_isInverted">
          <label class="form-check-label text-light" for="cfg_isInverted">GIF Âm Bản</label>
        </div>
      </div>

      <div class="glass-card">
        <h6 class="text-light mb-3"><i class="fas fa-hand-pointer me-2"></i>Hành Vi Chạm (Touch Sensor)</h6>
        <div class="mb-2">
          <label class="form-label text-light">Chạm 1 lần:</label>
          <select class="form-select" id="cfg_gif_touch"></select>
        </div>
        <div class="mb-2">
          <label class="form-label text-light">Chạm đôi (Double Touch):</label>
          <select class="form-select" id="cfg_gif_double_touch"></select>
        </div>
        <div class="mb-2">
          <label class="form-label text-light">Giữ lâu (Long Touch):</label>
          <select class="form-select" id="cfg_gif_long_touch"></select>
        </div>
      </div>

      <div class="glass-card">
        <div class="d-flex justify-content-between align-items-center mb-2">
          <h6 class="text-light m-0"><i class="fas fa-th me-2"></i>71 Biểu Cảm OLED (Chạm Để Đổi Mặt)</h6>
        </div>
        <div class="grid-faces" id="facesList"></div>
      </div>
    </div>

    <!-- TAB 3: ĐIỀU CHỈNH ÂM THANH -->
    <div class="tab-pane fade" id="tab-sound">
      <div class="glass-card">
        <h6 class="text-light mb-3"><i class="fas fa-volume-up me-2"></i>Cấu Hình Âm Lượng & Âm Báo</h6>
        <div class="mb-3">
          <label class="form-label text-light">Âm lượng Mochi: <span id="lbl_volume" class="text-info">8</span></label>
          <input type="range" class="form-range" id="cfg_volume" min="1" max="10" value="8">
        </div>
        <div class="mb-3">
          <label class="form-label text-light">Âm Intro:</label>
          <select class="form-select" id="cfg_intro_sound"></select>
        </div>
        <div class="mb-3">
          <label class="form-label text-light">Âm Thông Báo:</label>
          <select class="form-select" id="cfg_notif_sound"></select>
        </div>
      </div>

      <div class="glass-card">
        <h6 class="text-light mb-2"><i class="fas fa-music me-2"></i>27 Âm Thanh Gốc Firmware (Bấm Nghe Thử)</h6>
        <div class="grid-faces" id="soundsList"></div>
      </div>
    </div>

    <!-- TAB 4: LƯU & PHẦN CỨNG -->
    <div class="tab-pane fade" id="tab-actions">
      <div class="glass-card">
        <h6 class="text-light mb-3"><i class="fas fa-microchip me-2"></i>Màn Hình & Phần Cứng</h6>
        <div class="mb-3">
          <label class="form-label text-light">Loại màn hình:</label>
          <select class="form-select" id="cfg_display_type">
            <option value="ssd1306">SSD1306 OLED (128x64)</option>
            <option value="sh1106">SH1106 OLED (128x64)</option>
          </select>
        </div>
        <div class="mb-3">
          <label class="form-label text-light">Lật ngược 180 độ:</label>
          <select class="form-select" id="cfg_is_flip_mode">
            <option value="0">Không lật</option>
            <option value="1">Lật 180 độ</option>
          </select>
        </div>
      </div>

      <div class="glass-card text-center">
        <h6 class="text-light mb-3">Thao Tác Hệ Thống</h6>
        <button class="btn btn-danger me-2" onclick="resetMochi()">
          <i class="fas fa-power-off me-1"></i>RESET MOCHI
        </button>
        <button class="btn btn-elegant" id="btnSaveAll" onclick="saveAllSettings()">
          <i class="fas fa-save me-1"></i>Lưu Cài Đặt (set:save)
        </button>
      </div>
    </div>
  </div>
</div>

<script src="https://cdnjs.cloudflare.com/ajax/libs/bootstrap/5.3.2/js/bootstrap.bundle.min.js"></script>
<script>
let currentConfig = {};
let allFaces = [];
let allSounds = [];

async function apiGet(path) {
  const r = await fetch(path);
  return r.json();
}

async function apiPost(path, body) {
  const r = await fetch(path, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body || {})
  });
  return r.json();
}

async function initController() {
  try {
    const data = await apiGet('/api/mochi/status');
    currentConfig = data.nvs || {};
    allFaces = data.faces || [];
    allSounds = data.sounds || [];

    document.getElementById('macBadge').textContent = `MAC: ${data.emulator_mac}`;
    document.getElementById('fwBadge').textContent = `FW v${data.firmware_version}`;

    // Chronos
    document.getElementById('cfg_bluetoothName').value = currentConfig.bluetoothName || 'THE MOCHI';
    document.getElementById('cfg_notifDuration').value = currentConfig.notifDuration || '5';
    document.getElementById('lbl_notifDuration').textContent = currentConfig.notifDuration || '5';
    document.getElementById('cfg_bluetooth_auto_off').value = currentConfig.bluetooth_auto_off || '0';
    document.getElementById('lbl_bluetoothAutoOff').textContent = currentConfig.bluetooth_auto_off || '0';

    // GIF
    document.getElementById('cfg_gif_speed').value = currentConfig.gif_speed || '42';
    document.getElementById('lbl_gifSpeed').textContent = currentConfig.gif_speed || '42';
    const delaySec = Math.round(parseInt(currentConfig.gif_delay || '10000') / 1000);
    document.getElementById('cfg_gif_delay').value = delaySec;
    document.getElementById('lbl_gifDelay').textContent = delaySec;
    document.getElementById('cfg_isInverted').checked = (currentConfig.gif_negative === 'true');

    // Populate Selects
    populateTouchSelect('cfg_gif_touch', currentConfig.gif_touch || 'next_gif');
    populateTouchSelect('cfg_gif_double_touch', currentConfig.gif_double_touch || 'UwU');
    populateTouchSelect('cfg_gif_long_touch', currentConfig.gif_long_touch || 'show_clock');

    // Sound Selects
    populateSoundSelect('cfg_intro_sound', currentConfig.intro_sound || 'moshi.mp3');
    populateSoundSelect('cfg_notif_sound', currentConfig.notification_sound || 'moshi.mp3');
    document.getElementById('cfg_volume').value = currentConfig.volume || '8';
    document.getElementById('lbl_volume').textContent = currentConfig.volume || '8';

    // Render 71 Faces
    renderFacesList();
    renderSoundsList();

    // Update phone connection UI
    const isConn = data.phone_connected;
    const btnConn = document.getElementById('btnWebTogglePhoneConn');
    const badgeConn = document.getElementById('webConnStatusBadge');
    if (btnConn && badgeConn) {
      if (isConn) {
        btnConn.innerHTML = '<i class="fas fa-check-circle me-1"></i>ĐÃ KẾT NỐI (Bấm Để Ngắt)';
        btnConn.className = 'btn btn-success btn-lg';
        badgeConn.textContent = '🟢 Đã kết nối với điện thoại (Chronos BLE Active)';
        badgeConn.className = 'badge bg-success p-2';
      } else {
        btnConn.innerHTML = '<i class="fas fa-bolt me-1"></i>KẾT NỐI ĐIỆN THOẠI (CHRONOS)';
        btnConn.className = 'btn btn-elegant btn-lg';
        badgeConn.textContent = `● Sẵn sàng kết nối: ${currentConfig.bluetoothName || 'THE MOCHI'}`;
        badgeConn.className = 'badge bg-info p-2';
      }
    }

    // Sliders event listeners
    bindSliders();
  } catch (e) {
    console.error('Init error:', e);
  }
}

function populateTouchSelect(elemId, activeVal) {
  const sel = document.getElementById(elemId);
  sel.innerHTML = `
    <option value="next_gif">Chuyển hoạt ảnh tiếp theo</option>
    <option value="show_clock">Ẩn/Hiện đồng hồ</option>
    <option value="cpuz">Màn hình CPU/RAM</option>
    <option value="bluetooth">Bật/tắt Bluetooth</option>
  `;
  allFaces.forEach(f => {
    const opt = document.createElement('option');
    opt.value = f.name;
    opt.textContent = f.label;
    if (f.name === activeVal) opt.selected = true;
    sel.appendChild(opt);
  });
  if (['next_gif', 'show_clock', 'cpuz', 'bluetooth'].includes(activeVal)) {
    sel.value = activeVal;
  }
}

function populateSoundSelect(elemId, activeVal) {
  const sel = document.getElementById(elemId);
  sel.innerHTML = '';
  allSounds.forEach(s => {
    const opt = document.createElement('option');
    opt.value = s;
    opt.textContent = s;
    if (s === activeVal) opt.selected = true;
    sel.appendChild(opt);
  });
}

function renderFacesList() {
  const container = document.getElementById('facesList');
  container.innerHTML = '';
  allFaces.forEach(f => {
    const btn = document.createElement('button');
    btn.className = 'btn-face';
    btn.textContent = f.label;
    btn.title = f.name;
    btn.onclick = () => apiPost('/api/mochi/face', {face: f.name});
    container.appendChild(btn);
  });
}

function renderSoundsList() {
  const container = document.getElementById('soundsList');
  container.innerHTML = '';
  allSounds.forEach(s => {
    const btn = document.createElement('button');
    btn.className = 'btn-face';
    btn.textContent = s.replace('.wav', '').replace('.mp3', '');
    btn.onclick = () => apiPost('/api/mochi/sound', {sound: s});
    container.appendChild(btn);
  });
}

function bindSliders() {
  document.getElementById('cfg_notifDuration').oninput = (e) => {
    document.getElementById('lbl_notifDuration').textContent = e.target.value;
  };
  document.getElementById('cfg_bluetooth_auto_off').oninput = (e) => {
    document.getElementById('lbl_bluetoothAutoOff').textContent = e.target.value;
  };
  document.getElementById('cfg_gif_speed').oninput = (e) => {
    document.getElementById('lbl_gifSpeed').textContent = e.target.value;
    apiPost('/api/mochi/serial', {command: `gif_speed:${e.target.value}`});
  };
  document.getElementById('cfg_gif_delay').oninput = (e) => {
    document.getElementById('lbl_gifDelay').textContent = e.target.value;
    apiPost('/api/mochi/serial', {command: `gif_delay:${e.target.value * 1000}`});
  };
  document.getElementById('cfg_volume').oninput = (e) => {
    document.getElementById('lbl_volume').textContent = e.target.value;
    apiPost('/api/mochi/serial', {command: `volume:${e.target.value}`});
  };
  document.getElementById('cfg_isInverted').onchange = (e) => {
    apiPost('/api/mochi/serial', {command: `isInverted:${e.target.checked}`});
  };
  document.getElementById('cfg_gif_touch').onchange = (e) => {
    apiPost('/api/mochi/serial', {command: `gif_touch:${e.target.value}`});
  };
  document.getElementById('cfg_gif_double_touch').onchange = (e) => {
    apiPost('/api/mochi/serial', {command: `gif_double_touch:${e.target.value}`});
  };
  document.getElementById('cfg_gif_long_touch').onchange = (e) => {
    apiPost('/api/mochi/serial', {command: `gif_long_touch:${e.target.value}`});
  };
}

async function saveChronosConfig() {
  const btn = document.getElementById('btnSaveChronos');
  const bName = document.getElementById('cfg_bluetoothName').value.trim() || 'THE MOCHI';
  const duration = document.getElementById('cfg_notifDuration').value;
  const autoOff = document.getElementById('cfg_bluetooth_auto_off').value;
  
  await apiPost('/api/mochi/chronos/config', {
    bluetoothName: bName,
    notifDuration: duration,
    bluetooth_auto_off: autoOff
  });

  const orig = btn.innerHTML;
  btn.innerHTML = '<i class="fas fa-check me-1"></i>Đã Lưu Chronos!';
  setTimeout(() => { btn.innerHTML = orig; }, 1800);
}

async function saveAllSettings() {
  const btn = document.getElementById('btnSaveAll');
  await apiPost('/api/mochi/serial', {command: 'set:save'});
  const orig = btn.innerHTML;
  btn.innerHTML = '<i class="fas fa-check me-1"></i>Đã Lưu NVS!';
  setTimeout(() => { btn.innerHTML = orig; }, 1800);
}

function resetMochi() {
  apiPost('/api/mochi/intro', {});
}

function sendChat() {
  const inp = document.getElementById('chatInput');
  const txt = inp.value.trim();
  if (!txt) return;
  apiPost('/api/mochi/chat', {text: txt});
  inp.value = '';
}

async function toggleWebPhoneConnect() {
  const btn = document.getElementById('btnWebTogglePhoneConn');
  const badge = document.getElementById('webConnStatusBadge');
  try {
    const res = await apiPost('/api/mochi/chronos/connect', {action: 'toggle'});
    if (res.phone_connected) {
      btn.innerHTML = '<i class="fas fa-check-circle me-1"></i>ĐÃ KẾT NỐI (Bấm Để Ngắt)';
      btn.className = 'btn btn-success btn-lg';
      badge.textContent = '🟢 Đã kết nối với điện thoại (Chronos BLE Active)';
      badge.className = 'badge bg-success p-2';
    } else {
      btn.innerHTML = '<i class="fas fa-bolt me-1"></i>KẾT NỐI ĐIỆN THOẠI (CHRONOS)';
      btn.className = 'btn btn-elegant btn-lg';
      badge.textContent = `● Sẵn sàng kết nối: ${res.bluetoothName || 'THE MOCHI'}`;
      badge.className = 'badge bg-info p-2';
    }
  } catch (e) {
    alert('Lỗi kết nối backend');
  }
}

function sendTestNotif() {
  apiPost('/api/mochi/chronos/notification', {
    app: 'MoMo Bank',
    title: 'Biến động số dư',
    message: 'Nhận +500.000đ từ HUY KHONG'
  });
}

function sendTestNav() {
  apiPost('/api/mochi/chronos/navigation', {
    direction: 'RIGHT',
    distance: '120m',
    street: 'Lê Lợi'
  });
}

initController();
</script>
</body>
</html>
"""
