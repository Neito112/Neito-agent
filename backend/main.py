import asyncio
import base64
import json
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import Body, FastAPI, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.brain.llm_router import brain_router
from backend.core.chronos_ble_server import chronos_ble_server
from backend.core.config import config_manager
from backend.core.esp32_hardware_emulator import esp32_emulator
from backend.core.mobile_companion_ui import MOBILE_COMPANION_HTML
from backend.core.mochi_core_brain import mochi_core_brain
from backend.core.protocol_engine import protocol_engine
from backend.core.virtual_com_bridge import cdp_serial_injector, virtual_com_bridge
from backend.core.window_watcher import window_watcher
from backend.vision.eye_engine import eye_engine
from backend.vision.mochi_esp32_client import ESP32_CACHE_DIR, PROJECT_ROOT
from backend.voice.omnivoice_tts import VOICE_CATALOG, omnivoice_engine
from backend.voice.xiaozhi_ear import XiaozhiEarSession
from backend.core.updater import update_engine, APP_VERSION

app = FastAPI(
    title="Neito-Agent Core Brain (ESP32-S3-N16R8-CAM-BOX3 Hardware Emulator + Xiaozhi v2 + The Mochi + Chronos)",
    version="4.3.2",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def allow_private_network_access(request: Request, call_next):
    """Allows https://themochi.huykhong.com/thietlap/ to connect to 127.0.0.1:8765 in Chrome/Edge (PNA)."""
    if request.method == "OPTIONS" and request.headers.get("access-control-request-private-network") == "true":
        resp = Response(status_code=204)
        resp.headers["Access-Control-Allow-Origin"] = request.headers.get("origin", "*")
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "*"
        resp.headers["Access-Control-Allow-Private-Network"] = "true"
        return resp
    response = await call_next(request)
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Private-Network"] = "true"
    return response


@app.on_event("startup")
async def on_startup_init_chronos_ble():
    """Starts the real Windows BLE GATT Peripheral Server (`6e400001-b5a3-f393-e0a9-e50e24dcca9e`) for the Chronos Phone App and syncs ESP32-S3 OTA."""
    loop = asyncio.get_running_loop()

    async def _on_ble_notification(app_name: str, title: str, message: str):
        pkt = mochi_core_brain.handle_chronos_notification(app_name, title, message)
        await mochi_core_brain.broadcast_event(pkt)

    async def _on_ble_navigation(direction: str, distance: str, street: str, eta: str):
        pkt = mochi_core_brain.handle_chronos_navigation(direction, distance, street, eta)
        await mochi_core_brain.broadcast_event(pkt)

    async def _on_ble_connection(connected: bool):
        mochi_core_brain.phone_connected = connected
        if connected:
            sfx = omnivoice_engine.get_mochi_sfx_audio("coin.wav", emotion="excited")
            pkt = {
                "type": "mochi_firmware_event",
                "event": "chronos_connected",
                "face": "star",
                "display_mode": "face",
                "emotion": "excited",
                "text": "",
                "audio": sfx,
            }
        else:
            pkt = {
                "type": "mochi_firmware_event",
                "event": "chronos_disconnected",
                "face": "sleepy",
                "display_mode": "face",
                "emotion": "neutral",
                "text": "",
            }
        await mochi_core_brain.broadcast_event(pkt)

    def _on_ble_battery(level: int, charging: bool):
        mochi_core_brain.phone_battery = level
        mochi_core_brain.phone_connected = True

    def _on_ble_weather(city: str):
        mochi_core_brain.phone_weather = city

    chronos_ble_server.set_callbacks(
        loop=loop,
        on_notification=_on_ble_notification,
        on_navigation=_on_ble_navigation,
        on_connection=_on_ble_connection,
        on_battery=_on_ble_battery,
        on_weather=_on_ble_weather,
    )
    await chronos_ble_server.start()
    virtual_com_bridge.start(loop)
    cdp_serial_injector.start(loop)
    asyncio.create_task(esp32_emulator.check_xiaozhi_ota())


async def stream_tts_and_bubble(
    ws: WebSocket,
    ear: XiaozhiEarSession,
    reply_payload: Dict[str, Any],
):
    """
    Streams response text + Mochi/OmniVoice audio + Lip-Sync amplitude curve
    following the upgraded Neito-Xiaozhi v2 + The Mochi Firmware protocol.
    Synchronizes speech bubble display with exact audio playback onset.
    """
    ear.reset_interrupt()
    ear.set_state("SPEAKING")

    full_text = reply_payload.get("text", "")
    emotion = reply_payload.get("emotion", "speaking")
    face_name = reply_payload.get("face", "")
    mode = reply_payload.get("mode", "reflex")
    latency_ms = reply_payload.get("latency_ms", 0.0)
    proto = reply_payload.get("protocol") or protocol_engine.get_active_protocol()

    await ws.send_json(
        {
            "type": "speech_start",
            "text": full_text,
            "full_text": full_text,
            "emotion": emotion,
            "face": face_name,
            "mode": mode,
            "latency_ms": latency_ms,
            "protocol": {
                "id": proto["id"],
                "name": proto["name"],
                "category": proto.get("category", "custom"),
                "yolo_classes": proto.get("yolo_classes", []),
            },
        }
    )

    cloud_audio = reply_payload.get("audio_base64")
    if cloud_audio:
        await ws.send_json(
            {
                "type": "tts_chunk",
                "sentence": full_text,
                "full_text": full_text,
                "audio_base64": cloud_audio,
                "format": "wav",
                "lip_sync": [],
                "engine": "xiaozhi_cloud_opus",
            }
        )
    else:
        sentences = omnivoice_engine.split_sentences(full_text)
        for sent in sentences:
            if ear.is_interrupted:
                break
            tts_pkg = await omnivoice_engine.synthesize(sent, emotion=emotion, face_name=face_name)
            if ear.is_interrupted:
                break
            await ws.send_json(
                {
                    "type": "tts_chunk",
                    "sentence": sent,
                    "full_text": full_text,
                    "audio_base64": tts_pkg["audio_base64"],
                    "format": tts_pkg["format"],
                    "lip_sync": tts_pkg["lip_sync"],
                    "engine": tts_pkg["engine"],
                }
            )

    if not ear.is_interrupted:
        ear.set_state("IDLE")
        await ws.send_json({"type": "speech_end", "emotion": "idle"})


def _build_bridged_thietlap_html() -> str:
    """
    Returns the genuine `https://themochi.huykhong.com/thietlap/` HTML page
    with `<base href="https://themochi.huykhong.com/thietlap/">` and the
    `navigator.serial` Virtual ESP32-C3 Bridge injected at `<head>`.
    """
    orig_path = ESP32_CACHE_DIR / "thietlap_original.html"
    bridge_js_path = PROJECT_ROOT / "assets" / "mochi_webserial_bridge" / "mochi_serial_bridge.js"
    bridge_js = bridge_js_path.read_text(encoding="utf-8") if bridge_js_path.exists() else ""

    if orig_path.exists():
        raw_html = orig_path.read_text(encoding="utf-8", errors="replace")
        inject_block = (
            '<head>\n'
            '<base href="https://themochi.huykhong.com/thietlap/">\n'
            f'<script>{bridge_js}</script>\n'
        )
        if "<head>" in raw_html:
            return raw_html.replace("<head>", inject_block, 1)
        return inject_block + raw_html
    return MOBILE_COMPANION_HTML


@app.get("/thietlap", response_class=HTMLResponse)
@app.get("/thietlap/", response_class=HTMLResponse)
@app.get("/mobile", response_class=HTMLResponse)
async def serve_thietlap_web_serial_bridge():
    """Serves the genuine `themochi.huykhong.com/thietlap/` interface with the ESP32-C3 Web-Serial Bridge active."""
    return HTMLResponse(content=_build_bridged_thietlap_html())


@app.get("/thietlap/license_check.php")
@app.get("/license_check.php")
async def serve_license_check(mac: str = ""):
    return JSONResponse({"key": "NEITO-MOCHI-SUPPORTER", "licOK": True, "mac": mac})


@app.get("/api/health")
async def health():
    win = window_watcher.get_active_window()
    proto = protocol_engine.get_active_protocol()
    return {
        "status": "ok",
        "agent": config_manager.config.agent_name,
        "firmware": "the-mochi-4.3.2",
        "active_window": win.to_dict(),
        "active_protocol": {"id": proto["id"], "name": proto["name"]},
        "telemetry": window_watcher.get_resource_telemetry(),
    }


@app.get("/api/config")
async def get_config():
    data = config_manager.config.model_dump()
    data["voice_catalog"] = [{"label": lbl, "id": vid} for lbl, vid in VOICE_CATALOG]
    data["mochi_status"] = mochi_core_brain.get_status_snapshot()
    return data


@app.post("/api/config")
async def update_config(patch: Dict[str, Any] = Body(...)):
    updated = config_manager.update_partial(patch)
    return updated.model_dump()


@app.post("/api/voice/preview")
async def api_voice_preview(payload: Dict[str, Any] = Body(...)):
    preset = payload.get("preset", "omnivoice:neito_vi_hoaimy")
    res = await omnivoice_engine.synthesize_preview(preset)
    return res


@app.get("/api/protocols")
async def list_protocols():
    return {
        "active_protocol_id": protocol_engine.active_protocol_id,
        "locked_protocol_id": protocol_engine.locked_protocol_id,
        "protocols": protocol_engine.list_protocols(),
    }


@app.post("/api/protocols/select")
async def select_protocol(payload: Dict[str, Any] = Body(...)):
    pid = payload.get("protocol_id", "auto")
    proto = protocol_engine.set_manual_protocol(pid)
    return {
        "active_protocol_id": protocol_engine.active_protocol_id,
        "locked_protocol_id": protocol_engine.locked_protocol_id,
        "protocol": proto,
    }


@app.post("/api/protocols/synthesize")
async def synthesize_protocol(payload: Dict[str, Any] = Body(...)):
    topic = payload.get("topic", "Custom Game")
    process_name = payload.get("process_name", "")
    classes = payload.get("yolo_classes")
    if isinstance(classes, str):
        classes = [c.strip() for c in classes.split(",") if c.strip()]
    result = await brain_router.synthesize_protocol_with_llm_and_tools(
        topic_or_app=topic,
        process_name=process_name,
        custom_classes=classes,
    )
    return result


@app.delete("/api/protocols/{protocol_id}")
async def delete_protocol(protocol_id: str):
    ok = protocol_engine.delete_protocol(protocol_id)
    return {"deleted": ok, "active_protocol_id": protocol_engine.active_protocol_id}


@app.post("/api/vision/scan")
async def api_vision_scan():
    proto = protocol_engine.get_active_protocol()
    scan = eye_engine.scan_screen_yolo11n(proto.get("yolo_classes"))
    thumb = eye_engine.capture_base64_thumbnail(max_dim=420)
    return {**scan, "thumbnail_base64": thumb}


@app.post("/api/vision/train-yoloworld")
async def api_train_yoloworld(payload: Dict[str, Any] = Body(...)):
    proto = protocol_engine.get_active_protocol()
    protocol_id = payload.get("protocol_id") or proto["id"]
    raw_classes = payload.get("classes", [])
    if isinstance(raw_classes, str):
        raw_classes = [c.strip() for c in raw_classes.split(",") if c.strip()]
    res = eye_engine.auto_train_yolo_world(protocol_id=protocol_id, open_vocab_classes=raw_classes)
    if protocol_id in protocol_engine.protocols:
        p = protocol_engine.protocols[protocol_id]
        p["yolo_classes"] = list(dict.fromkeys(p.get("yolo_classes", []) + res["classes"]))
        protocol_engine.save_protocol(p)
    return res


# ============================================================================
# THE MOCHI FIRMWARE CORE & CHRONOS PHONE BRIDGE ENDPOINTS
# ============================================================================

@app.get("/api/mochi/status")
async def api_mochi_status():
    snap = mochi_core_brain.get_status_snapshot()
    return {
        "emulator_mac": snap["mac"],
        "chip_family": snap["chip"],
        "firmware_version": snap["firmware_version"],
        "mobile_companion_url": snap["mobile_companion_url"],
        "phone_connected": snap["phone_connected"],
        "phone_battery": snap["phone_battery"],
        "nvs": snap["nvs"],
        "faces": snap["faces"],
        "sounds": snap["sounds"],
        "melodies": snap["melodies"],
    }


@app.post("/api/mochi/sync")
async def api_mochi_sync():
    from backend.vision.mochi_esp32_client import MochiESP32Client

    client = MochiESP32Client()
    manifest = await asyncio.to_thread(client.extract_all_faces, True, True)
    return {
        "ok": True,
        "total_animations": manifest["total_animations"],
        "total_frames": manifest["total_frames"],
        "total_sounds": manifest.get("total_sounds", 27),
    }


@app.post("/api/mochi/serial")
async def api_mochi_serial(payload: Dict[str, Any] = Body(...)):
    cmd = payload.get("command", "set:get")
    replies = mochi_core_brain.execute_serial_command(cmd)
    evt = mochi_core_brain.build_serial_side_effect_packet(cmd)
    if evt:
        await mochi_core_brain.broadcast_event(evt)
    return {"replies": replies, "nvs": mochi_core_brain.nvs}


@app.websocket("/ws/mochi-serial")
async def ws_mochi_serial_bridge(ws: WebSocket):
    """WebSocket stream emulating 115200-baud UART serial for https://themochi.huykhong.com/thietlap/."""
    await ws.accept()
    try:
        while True:
            raw = await ws.receive_text()
            for line in raw.splitlines():
                cmd = line.strip()
                if not cmd:
                    continue
                replies = mochi_core_brain.execute_serial_command(cmd)
                if replies:
                    await ws.send_text("\n".join(replies) + "\n")
                evt = mochi_core_brain.build_serial_side_effect_packet(cmd)
                if evt:
                    await mochi_core_brain.broadcast_event(evt)
    except WebSocketDisconnect:
        pass
    except Exception:
        pass


@app.post("/api/mochi/intro")
async def api_mochi_intro():
    pkt = mochi_core_brain.build_boot_intro_packet()
    await mochi_core_brain.broadcast_event(pkt)
    return pkt


@app.post("/api/mochi/touch")
async def api_mochi_touch(payload: Dict[str, Any] = Body(...)):
    kind = payload.get("kind", "single")
    pkt = mochi_core_brain.handle_touch_action(kind)
    await mochi_core_brain.broadcast_event(pkt)
    return pkt


@app.post("/api/mochi/face")
async def api_mochi_face(payload: Dict[str, Any] = Body(...)):
    face = payload.get("face", "UwU")
    sfx = omnivoice_engine.get_mochi_sfx_audio(face, emotion="happy")
    pkt = {
        "type": "mochi_firmware_event",
        "event": "set_face",
        "face": face,
        "display_mode": face if face in ("show_clock", "cpuz") else "face",
        "emotion": "happy",
        "audio": sfx,
    }
    await mochi_core_brain.broadcast_event(pkt)
    return pkt


@app.post("/api/mochi/sound")
async def api_mochi_sound(payload: Dict[str, Any] = Body(...)):
    sound = payload.get("sound", "moshi.wav")
    sfx = omnivoice_engine.get_mochi_sfx_audio(sound, emotion="happy")
    pkt = {
        "type": "mochi_firmware_event",
        "event": "play_sound",
        "sound": sound,
        "emotion": "happy",
        "audio": sfx,
    }
    await mochi_core_brain.broadcast_event(pkt)
    return pkt


@app.post("/api/mochi/chronos/notification")
async def api_chronos_notification(payload: Dict[str, Any] = Body(...)):
    app_name = payload.get("app", "Chronos")
    title = payload.get("title", "Thông báo")
    message = payload.get("message", "Moshi Moshi!")
    pkt = mochi_core_brain.handle_chronos_notification(app_name, title, message)
    await mochi_core_brain.broadcast_event(pkt)
    return pkt


@app.post("/api/mochi/chronos/navigation")
async def api_chronos_navigation(payload: Dict[str, Any] = Body(...)):
    direction = payload.get("direction", "STRAIGHT")
    distance = payload.get("distance", "150m")
    street = payload.get("street", "Google Maps")
    eta = payload.get("eta", "5 phút")
    pkt = mochi_core_brain.handle_chronos_navigation(direction, distance, street, eta)
    await mochi_core_brain.broadcast_event(pkt)
    return pkt


@app.get("/api/mochi/chronos/config")
@app.get("/api/mochi/chronos/status")
async def api_get_chronos_config():
    snap = mochi_core_brain.get_status_snapshot()
    ble_st = chronos_ble_server.get_status()
    vcom_st = virtual_com_bridge.get_status()
    return {
        "bluetoothName": mochi_core_brain.nvs.get("bluetoothName", "THE MOCHI"),
        "pc_ble_name": ble_st["pc_ble_name"],
        "service_uuid": ble_st["service_uuid"],
        "is_advertising": ble_st["is_advertising"],
        "ble_supported": ble_st["ble_supported"],
        "connected_clients": ble_st["connected_clients"],
        "notifDuration": mochi_core_brain.nvs.get("notifDuration", "5"),
        "bluetooth_auto_off": mochi_core_brain.nvs.get("bluetooth_auto_off", "0"),
        "phone_connected": ble_st["phone_connected"] or mochi_core_brain.phone_connected,
        "phone_battery": mochi_core_brain.phone_battery,
        "mobile_companion_url": snap["mobile_companion_url"],
        "virtual_com": vcom_st,
    }


@app.get("/api/mochi/system-ports")
async def api_get_system_ports():
    return virtual_com_bridge.get_status()


@app.post("/api/mochi/virtual-com/install")
async def api_install_virtual_com():
    res = await asyncio.to_thread(virtual_com_bridge.install_driver_elevated)
    return res


@app.get("/api/mochi/bridge-launch", response_class=HTMLResponse)
async def api_mochi_bridge_launch():
    """
    Pre-flight launch page for Chrome 155+: registers `Page.addScriptToEvaluateOnNewDocument`
    via CDP on the active tab BEFORE redirecting to `https://themochi.huykhong.com/thietlap/`,
    so `navigator.serial.requestPort()` displays `THE MOCHI - Neito Agent (COM9)` immediately.
    """
    await cdp_serial_injector.inject_all_now()
    html = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Đang kết nối cầu nối THE MOCHI ESP32-C3 (COM9)...</title>
<style>body{background:#0b101c;color:#00f5d4;font-family:'Segoe UI',sans-serif;display:flex;align-items:center;justify-content:center;height:100vh;margin:0;font-weight:700;}</style>
</head><body>
<div>⚡ Đang nạp tín hiệu cầu nối THE MOCHI - Neito Agent (COM9)...</div>
<script>
setTimeout(function() {
  window.location.replace("https://themochi.huykhong.com/thietlap/");
}, 250);
</script>
</body></html>"""
    return HTMLResponse(content=html)


@app.post("/api/mochi/chronos/config")
async def api_update_chronos_config(payload: Dict[str, Any] = Body(...)):
    cfg = mochi_core_brain.update_chronos_config(
        bluetooth_name=payload.get("bluetoothName"),
        notif_duration=str(payload.get("notifDuration", "")) if payload.get("notifDuration") is not None else None,
        bluetooth_auto_off=str(payload.get("bluetooth_auto_off", "")) if payload.get("bluetooth_auto_off") is not None else None,
    )
    snap = mochi_core_brain.get_status_snapshot()
    return {
        "ok": True,
        "config": cfg,
        "mobile_companion_url": snap["mobile_companion_url"],
    }


@app.post("/api/mochi/chronos/connect")
async def api_chronos_connect(payload: Dict[str, Any] = Body(default={})):
    action = payload.get("action", "restart")
    if action == "stop":
        st = await chronos_ble_server.stop()
        mochi_core_brain.phone_connected = False
    else:
        await chronos_ble_server.stop()
        st = await chronos_ble_server.start()
    return {
        "ok": True,
        **st,
        "phone_battery": mochi_core_brain.phone_battery,
        "bluetoothName": mochi_core_brain.nvs.get("bluetoothName", "THE MOCHI"),
    }


@app.post("/api/mochi/chat")
async def api_mochi_mobile_chat(payload: Dict[str, Any] = Body(...)):
    user_text = (payload.get("text") or "").strip()
    if not user_text:
        return {"ok": False}
    reply = await brain_router.generate_response(user_text)
    tts_pkg = await omnivoice_engine.synthesize(
        reply.get("text", ""), emotion=reply.get("emotion", "happy")
    )
    pkt = {
        "type": "mochi_firmware_event",
        "event": "mobile_chat_reply",
        "face": "smile",
        "display_mode": "face",
        "emotion": reply.get("emotion", "happy"),
        "text": reply.get("text", ""),
        "audio": tts_pkg,
    }
    await mochi_core_brain.broadcast_event(pkt)
    return {"ok": True, "reply": reply}


@app.get("/api/updater/check")
async def api_check_updater():
    loop = asyncio.get_event_loop()
    info = await loop.run_in_executor(None, update_engine.check_for_updates)
    return info


@app.get("/api/updater/progress")
async def api_get_updater_progress():
    return update_engine.download_progress


@app.post("/api/updater/download")
async def api_start_updater_download(payload: Dict[str, Any] = Body(...)):
    url = payload.get("url")
    if not url:
        return {"ok": False, "error": "Missing download URL"}
    update_engine.start_download_thread(url)
    return {"ok": True, "message": "Download started"}


@app.post("/api/updater/apply")
async def api_apply_updater(payload: Dict[str, Any] = Body(default={})):
    file_path = payload.get("file_path")
    res = update_engine.apply_update(Path(file_path) if file_path else None)
    return res


# ============================================================================
# ESP32-S3 ULTIMATE HARDWARE EMULATOR & XIAOZHI.ME CONSOLE / MCP ENDPOINTS
# ============================================================================

@app.get("/api/esp32/hardware")
async def api_get_esp32_hardware():
    """Returns the full ESP32-S3-N16R8-CAM-BOX3 Hardware Emulator manifest and built-in MCP tools."""
    return {
        "ok": True,
        "hardware": esp32_emulator.get_hardware_manifest(),
        "mcp_tools": esp32_emulator.get_mcp_tools_list(),
    }


@app.post("/api/esp32/xiaozhi-ota")
async def api_esp32_xiaozhi_ota(payload: Dict[str, Any] = Body(default={})):
    """
    Contacts `https://api.tenclass.net/xiaozhi/ota/` to register the ESP32-S3 hardware emulator
    and retrieve the 6-digit `activation_code` for `https://xiaozhi.me/console/agents`.
    """
    custom_url = payload.get("ota_url")
    res = await esp32_emulator.check_xiaozhi_ota(custom_ota_url=custom_url)
    return res


@app.post("/api/esp32/yolo-mode")
async def api_esp32_set_yolo_mode(payload: Dict[str, Any] = Body(...)):
    """Switches the built-in ESP32-S3 Hardware YOLO Co-Processor mode (`off`, `eco_1fps`, `balanced_4fps`, `combat_10fps`, `auto_reflex`)."""
    mode = payload.get("mode", "eco_1fps")
    res = await esp32_emulator.set_yolo_hardware_mode(mode)
    return res


@app.post("/api/esp32/mcp/call")
async def api_esp32_mcp_call(payload: Dict[str, Any] = Body(...)):
    """Directly invokes a built-in ESP32-S3 Hardware MCP tool."""
    tool_name = payload.get("name", "self.camera.take_photo")
    arguments = payload.get("arguments") or {}
    res = await esp32_emulator.execute_mcp_tool(tool_name, arguments)
    return {"ok": True, "tool": tool_name, "result": res}


@app.websocket("/ws/xiaozhi")
async def xiaozhi_websocket_endpoint(ws: WebSocket):
    await ws.accept()
    session_id = f"neito-{uuid.uuid4().hex[:8]}"
    ear = XiaozhiEarSession(session_id=session_id)
    stop_event = asyncio.Event()

    async def forward_mochi_event(pkt: Dict[str, Any]) -> None:
        await ws.send_json(pkt)

    mochi_core_brain.register_listener(forward_mochi_event)
    esp32_emulator.register_listener(forward_mochi_event)

    # 1. Send initial Xiaozhi v2 + Mochi Firmware + ESP32-S3 Hardware Handshake
    win = window_watcher.get_active_window()
    _, proto = protocol_engine.match_window_to_protocol(win.process_name, win.window_title)
    await ws.send_json(
        {
            "type": "hello",
            "session_id": session_id,
            "protocol_version": "neito-mochi-v4.3.2",
            "config": config_manager.config.model_dump(),
            "mochi_status": mochi_core_brain.get_status_snapshot(),
            "esp32_hardware": esp32_emulator.get_hardware_manifest(),
            "active_window": win.to_dict(),
            "active_protocol": proto,
            "telemetry": window_watcher.get_resource_telemetry(),
        }
    )

    # 2. Trigger Mochi Firmware Boot Intro (`gif_intro` + `moshi.wav`)
    await ws.send_json(mochi_core_brain.build_boot_intro_packet())

    async def _auto_synthesize_unknown_app(proc_name: str, win_title: str):
        try:
            topic_label = win_title.strip() or proc_name.replace(".exe", "")
            synth_res = await brain_router.synthesize_protocol_with_llm_and_tools(
                topic_or_app=topic_label,
                process_name=proc_name,
            )
            new_proto = synth_res.get("protocol")
            if new_proto and not stop_event.is_set():
                await ws.send_json(
                    {
                        "type": "protocol_switched",
                        "window": {"process_name": proc_name, "window_title": win_title},
                        "protocol": new_proto,
                        "auto_synthesized": True,
                    }
                )
        except Exception:
            pass

    async def autonomous_perception_loop():
        unknown_proc_streak: Dict[str, int] = {}
        tick_count = 0
        while not stop_event.is_set():
            try:
                await asyncio.sleep(1.0)
                tick_count += 1
                win_now = window_watcher.get_active_window()
                changed, current_proto = protocol_engine.match_window_to_protocol(
                    win_now.process_name, win_now.window_title
                )

                if changed:
                    await ws.send_json(
                        {
                            "type": "protocol_switched",
                            "window": win_now.to_dict(),
                            "protocol": current_proto,
                        }
                    )

                # Auto-create a new Protocol Cartridge if user is running an unrecognized app/game for >= 3s
                if protocol_engine.should_auto_synthesize_for_window(
                    win_now.process_name, win_now.window_title
                ):
                    p_key = win_now.process_name.lower().strip()
                    unknown_proc_streak[p_key] = unknown_proc_streak.get(p_key, 0) + 1
                    if unknown_proc_streak[p_key] >= 3:
                        protocol_engine.mark_process_synthesizing(p_key)
                        asyncio.create_task(
                            _auto_synthesize_unknown_app(win_now.process_name, win_now.window_title)
                        )

                # ESP32-S3 Built-in Hardware YOLO Co-processor periodic screen scan
                hw_mode = esp32_emulator.yolo_hardware_mode
                if hw_mode != "off":
                    interval = 5 if hw_mode == "eco_1fps" else (2 if hw_mode == "balanced_4fps" else 1)
                    if tick_count % interval == 0:
                        await asyncio.to_thread(
                            eye_engine.scan_screen_yolo11n,
                            current_proto.get("yolo_classes"),
                        )

                # Mochi Firmware `gifTask` autonomous expression cycling when idle
                if ear.state == "IDLE":
                    cycle_pkt = mochi_core_brain.pick_next_autonomous_face()
                    if cycle_pkt:
                        await ws.send_json(cycle_pkt)
            except Exception:
                if stop_event.is_set():
                    break

    perception_task = asyncio.create_task(autonomous_perception_loop())

    try:
        while True:
            raw_msg = await ws.receive_text()
            msg = json.loads(raw_msg)
            mtype = msg.get("type", "")

            if mtype == "barge_in":
                stop_pkt = ear.trigger_barge_in()
                await ws.send_json(stop_pkt)

            elif mtype == "mochi_touch":
                kind = msg.get("kind", "single")
                pkt = mochi_core_brain.handle_touch_action(kind)
                await ws.send_json(pkt)

            elif mtype == "listen_pcm":
                b64 = msg.get("pcm_base64", "")
                if b64:
                    vad_res = ear.process_pcm16_frame(base64.b64decode(b64))
                    if vad_res["should_barge_in"]:
                        await ws.send_json({"type": "tts", "state": "stop", "reason": "vad_barge_in"})

            elif mtype in ("chat", "voice_transcript"):
                user_text = msg.get("text", "").strip()
                if mtype == "voice_transcript":
                    filtered = ear.filter_wake_word(user_text)
                    if not filtered:
                        continue
                    user_text = filtered

                if not user_text:
                    continue

                if ear.state == "SPEAKING" and config_manager.config.voice.barge_in:
                    ear.trigger_barge_in()
                    await ws.send_json({"type": "tts", "state": "stop", "reason": "barge_in"})

                ear.set_state("THINKING")
                await ws.send_json({"type": "emotion", "emotion": "thinking"})

                reply = await brain_router.generate_response(user_text)
                await stream_tts_and_bubble(ws, ear, reply)

            elif mtype == "scan_now":
                proto = protocol_engine.get_active_protocol()
                await ws.send_json({"type": "emotion", "emotion": "scanning"})
                scan = eye_engine.scan_screen_yolo11n(proto.get("yolo_classes"))
                thumb = eye_engine.capture_base64_thumbnail(max_dim=420)
                await ws.send_json(
                    {
                        "type": "vision_snapshot",
                        "scan": scan,
                        "thumbnail_base64": thumb,
                    }
                )
                await stream_tts_and_bubble(
                    ws,
                    ear,
                    {
                        "text": scan["screen_summary"],
                        "emotion": "speaking",
                        "mode": "yolo11n_vision",
                        "latency_ms": scan["latency_ms"],
                        "protocol": proto,
                    },
                )

    except WebSocketDisconnect:
        pass
    finally:
        stop_event.set()
        mochi_core_brain.unregister_listener(forward_mochi_event)
        esp32_emulator.unregister_listener(forward_mochi_event)
        perception_task.cancel()


DESKTOP_SRC_DIR = Path(__file__).resolve().parent.parent / "desktop" / "src"
if DESKTOP_SRC_DIR.exists():
    app.mount("/", StaticFiles(directory=str(DESKTOP_SRC_DIR), html=True), name="desktop_ui")
