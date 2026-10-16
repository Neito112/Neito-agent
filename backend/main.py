import asyncio
import base64
import json
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import Body, FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from backend.brain.llm_router import brain_router
from backend.core.config import config_manager
from backend.core.mobile_companion_ui import MOBILE_COMPANION_HTML
from backend.core.mochi_core_brain import mochi_core_brain
from backend.core.protocol_engine import protocol_engine
from backend.core.window_watcher import window_watcher
from backend.vision.eye_engine import eye_engine
from backend.voice.omnivoice_tts import VOICE_CATALOG, omnivoice_engine
from backend.voice.xiaozhi_ear import XiaozhiEarSession

app = FastAPI(
    title="Neito-Agent Core Brain (The Mochi Firmware v4.3.2 + Xiaozhi v2 + Chronos Phone Bridge)",
    version="4.3.2",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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


@app.get("/mobile", response_class=HTMLResponse)
@app.get("/thietlap", response_class=HTMLResponse)
async def serve_mobile_companion():
    """Serves the Smartphone Companion PWA (`http://<PC-LAN-IP>:8765/mobile`)."""
    return HTMLResponse(content=MOBILE_COMPANION_HTML)


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
    return {"replies": replies, "nvs": mochi_core_brain.nvs}


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
    return {
        "bluetoothName": mochi_core_brain.nvs.get("bluetoothName", "THE MOCHI"),
        "notifDuration": mochi_core_brain.nvs.get("notifDuration", "5"),
        "bluetooth_auto_off": mochi_core_brain.nvs.get("bluetooth_auto_off", "0"),
        "phone_connected": mochi_core_brain.phone_connected,
        "phone_battery": mochi_core_brain.phone_battery,
        "mobile_companion_url": snap["mobile_companion_url"],
    }


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
    action = payload.get("action", "toggle")
    if action == "disconnect" or (action == "toggle" and mochi_core_brain.phone_connected):
        mochi_core_brain.phone_connected = False
        pkt = {
            "type": "mochi_firmware_event",
            "event": "chronos_disconnected",
            "face": "sleepy",
            "display_mode": "face",
            "emotion": "neutral",
            "text": "📱 Đã ngắt kết nối Chronos Phone",
        }
    else:
        mochi_core_brain.phone_connected = True
        sfx = omnivoice_engine.get_mochi_sfx_audio("coin.wav", emotion="excited")
        pkt = {
            "type": "mochi_firmware_event",
            "event": "chronos_connected",
            "face": "star",
            "display_mode": "face",
            "emotion": "excited",
            "text": f"📱 Đã kết nối Chronos: {mochi_core_brain.nvs.get('bluetoothName', 'THE MOCHI')} (Pin: 100%)",
            "audio": sfx,
        }
    await mochi_core_brain.broadcast_event(pkt)
    return {
        "ok": True,
        "phone_connected": mochi_core_brain.phone_connected,
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


@app.websocket("/ws/xiaozhi")
async def xiaozhi_websocket_endpoint(ws: WebSocket):
    await ws.accept()
    session_id = f"neito-{uuid.uuid4().hex[:8]}"
    ear = XiaozhiEarSession(session_id=session_id)
    stop_event = asyncio.Event()

    async def forward_mochi_event(pkt: Dict[str, Any]) -> None:
        await ws.send_json(pkt)

    mochi_core_brain.register_listener(forward_mochi_event)

    # 1. Send initial Xiaozhi v2 + Mochi Firmware Handshake
    win = window_watcher.get_active_window()
    _, proto = protocol_engine.match_window_to_protocol(win.process_name, win.window_title)
    await ws.send_json(
        {
            "type": "hello",
            "session_id": session_id,
            "protocol_version": "neito-mochi-v4.3.2",
            "config": config_manager.config.model_dump(),
            "mochi_status": mochi_core_brain.get_status_snapshot(),
            "active_window": win.to_dict(),
            "active_protocol": proto,
            "telemetry": window_watcher.get_resource_telemetry(),
        }
    )

    # 2. Trigger Mochi Firmware Boot Intro (`gif_intro` + `moshi.wav`)
    await ws.send_json(mochi_core_brain.build_boot_intro_packet())

    async def autonomous_perception_loop():
        last_vision_ts = 0.0
        while not stop_event.is_set():
            try:
                await asyncio.sleep(0.8)
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
                    if current_proto.get("category") == "auto" and not current_proto.get("llm_enriched"):
                        current_proto["llm_enriched"] = True
                        asyncio.create_task(
                            brain_router.synthesize_protocol_with_llm_and_tools(
                                topic_or_app=current_proto["name"],
                                process_name=win_now.process_name,
                            )
                        )

                # Mochi Firmware `gifTask` autonomous expression cycling when idle
                if ear.state == "IDLE":
                    cycle_pkt = mochi_core_brain.pick_next_autonomous_face()
                    if cycle_pkt:
                        await ws.send_json(cycle_pkt)

                vcfg = config_manager.config.vision
                fps_intervals = {"eco": 2.0, "balanced": 0.8, "combat": 0.25}
                interval = fps_intervals.get(vcfg.fps_mode, 2.0)
                now = time.time()

                if vcfg.enabled and (now - last_vision_ts >= interval):
                    last_vision_ts = now
                    scan = eye_engine.scan_screen_yolo11n(current_proto.get("yolo_classes"))
                    await ws.send_json(
                        {
                            "type": "telemetry_tick",
                            "window": win_now.to_dict(),
                            "protocol_id": current_proto["id"],
                            "protocol_name": current_proto["name"],
                            "vision_latency_ms": scan["latency_ms"],
                            "detections": scan["detections"],
                            "neural": scan.get("neural", {}),
                            "resources": window_watcher.get_resource_telemetry(),
                        }
                    )

                    if vcfg.auto_reflex_on_detection and ear.state == "IDLE":
                        v_reflex = protocol_engine.evaluate_vision_reflex(scan["detections"])
                        if v_reflex:
                            await stream_tts_and_bubble(
                                ws,
                                ear,
                                {
                                    "text": v_reflex["response"],
                                    "emotion": v_reflex["emotion"],
                                    "mode": "vision_reflex",
                                    "latency_ms": scan["latency_ms"],
                                    "protocol": current_proto,
                                },
                            )
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
        perception_task.cancel()


DESKTOP_SRC_DIR = Path(__file__).resolve().parent.parent / "desktop" / "src"
if DESKTOP_SRC_DIR.exists():
    app.mount("/", StaticFiles(directory=str(DESKTOP_SRC_DIR), html=True), name="desktop_ui")
