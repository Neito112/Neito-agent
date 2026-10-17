"""
Neito-Agent: Real Hardware BLE GATT Peripheral Server for Chronos App & Web-Serial Bridge
=========================================================================================
1. Broadcasts the genuine `ChronosESP32` Nordic UART BLE GATT Service on Windows Bluetooth:
   - Service UUID:        `6e400001-b5a3-f393-e0a9-e50e24dcca9e`
   - RX Characteristic:   `6e400002-b5a3-f393-e0a9-e50e24dcca9e` (Write / WriteWithoutResponse)
   - TX Characteristic:   `6e400003-b5a3-f393-e0a9-e50e24dcca9e` (Notify / Read)
2. Allows the official Chronos Smartphone App (`fbiego.chronos` on Android/iOS) to discover
   this PC as a real `ChronosESP32` smartwatch/ESP32 device (`HXG-Neito` / `THE MOCHI`) over
   Bluetooth Low Energy and stream live Phone Notifications, Banking Alerts, Google Maps
   Navigation, Battery, and Weather directly to the desktop Mascot's 128x64 OLED visor.
"""

from __future__ import annotations

import asyncio
import socket
import threading
import time
import uuid
from typing import Any, Callable, Coroutine, Dict, List, Optional

CHRONOS_SERVICE_UUID = uuid.UUID("6e400001-b5a3-f393-e0a9-e50e24dcca9e")
CHRONOS_RX_UUID = uuid.UUID("6e400002-b5a3-f393-e0a9-e50e24dcca9e")
CHRONOS_TX_UUID = uuid.UUID("6e400003-b5a3-f393-e0a9-e50e24dcca9e")

CHRONOS_APP_NAMES: Dict[int, str] = {
    0x01: "Cuộc gọi đến",
    0x02: "Cuộc gọi",
    0x03: "Tin nhắn SMS",
    0x04: "Mail",
    0x07: "Tencent",
    0x08: "Skype",
    0x09: "WeChat",
    0x0A: "WhatsApp",
    0x0B: "Gmail",
    0x0E: "Line",
    0x0F: "Twitter",
    0x10: "Facebook",
    0x11: "Messenger",
    0x12: "Instagram",
    0x13: "Weibo",
    0x14: "KakaoTalk",
    0x16: "Viber",
    0x17: "Vkontakte",
    0x18: "Telegram",
    0x1B: "DingTalk",
    0x20: "WhatsApp Business",
    0x22: "WearFit Pro",
    0xC0: "Chronos",
}


class ChronosBLEGattServer:
    """
    Windows Runtime (WinRT) BLE GATT Peripheral Server implementing `fbiego/ChronosESP32` v1.8.0.
    """

    def __init__(self) -> None:
        self.service_provider: Any = None
        self.rx_char: Any = None
        self.tx_char: Any = None
        self.is_advertising: bool = False
        self.ble_supported: bool = False
        self.ble_error: str = ""
        self.pc_ble_name: str = socket.gethostname()
        self.connected_clients_count: int = 0
        self.last_rx_timestamp: float = 0.0
        self.app_version: str = ""

        # Packet reassembly buffer matching ChronosESP32::_incomingData
        self._incoming_buf = bytearray(1024)
        self._incoming_expected_len: int = 0
        self._chunked_transfer: bool = True

        self._event_loop: Optional[asyncio.AbstractEventLoop] = None
        self._on_notification_cb: Optional[Callable[[str, str, str], Coroutine[Any, Any, None]]] = None
        self._on_navigation_cb: Optional[Callable[[str, str, str, str], Coroutine[Any, Any, None]]] = None
        self._on_connection_cb: Optional[Callable[[bool], Coroutine[Any, Any, None]]] = None
        self._on_battery_cb: Optional[Callable[[int, bool], None]] = None
        self._on_weather_cb: Optional[Callable[[str], None]] = None

    def set_callbacks(
        self,
        loop: asyncio.AbstractEventLoop,
        on_notification: Callable[[str, str, str], Coroutine[Any, Any, None]],
        on_navigation: Callable[[str, str, str, str], Coroutine[Any, Any, None]],
        on_connection: Callable[[bool], Coroutine[Any, Any, None]],
        on_battery: Callable[[int, bool], None],
        on_weather: Callable[[str], None],
    ) -> None:
        self._event_loop = loop
        self._on_notification_cb = on_notification
        self._on_navigation_cb = on_navigation
        self._on_connection_cb = on_connection
        self._on_battery_cb = on_battery
        self._on_weather_cb = on_weather

    async def start(self) -> Dict[str, Any]:
        """Initializes and starts the Windows BLE GATT Peripheral advertising for Chronos."""
        if self.is_advertising and self.service_provider is not None:
            return self.get_status()

        try:
            from winrt.windows.devices.bluetooth.genericattributeprofile import (
                GattCharacteristicProperties,
                GattLocalCharacteristicParameters,
                GattProtectionLevel,
                GattServiceProvider,
                GattServiceProviderAdvertisingParameters,
            )

            res = await GattServiceProvider.create_async(CHRONOS_SERVICE_UUID)
            if res.error != 0 or res.service_provider is None:
                self.ble_supported = False
                self.ble_error = f"Bluetooth GATT Error Code: {res.error}"
                return self.get_status()

            sp = res.service_provider
            self.service_provider = sp

            # RX Characteristic (Phone writes commands/notifications to ESP32)
            rx_params = GattLocalCharacteristicParameters()
            rx_params.characteristic_properties = (
                GattCharacteristicProperties.WRITE
                | GattCharacteristicProperties.WRITE_WITHOUT_RESPONSE
            )
            rx_params.write_protection_level = GattProtectionLevel.PLAIN
            rx_res = await sp.service.create_characteristic_async(CHRONOS_RX_UUID, rx_params)
            self.rx_char = rx_res.characteristic
            self.rx_char.add_write_requested(self._on_rx_write_requested)

            # TX Characteristic (ESP32 notifies Phone)
            tx_params = GattLocalCharacteristicParameters()
            tx_params.characteristic_properties = (
                GattCharacteristicProperties.NOTIFY | GattCharacteristicProperties.READ
            )
            tx_params.read_protection_level = GattProtectionLevel.PLAIN
            tx_res = await sp.service.create_characteristic_async(CHRONOS_TX_UUID, tx_params)
            self.tx_char = tx_res.characteristic
            self.tx_char.add_subscribed_clients_changed(self._on_tx_subscribed_changed)
            self.tx_char.add_read_requested(self._on_tx_read_requested)

            adv = GattServiceProviderAdvertisingParameters()
            adv.is_connectable = True
            adv.is_discoverable = True
            sp.start_advertising_with_parameters(adv)

            self.ble_supported = True
            self.is_advertising = True
            self.ble_error = ""
        except Exception as exc:
            self.ble_supported = False
            self.is_advertising = False
            self.ble_error = str(exc)

        return self.get_status()

    async def stop(self) -> Dict[str, Any]:
        if self.service_provider is not None:
            try:
                self.service_provider.stop_advertising()
            except Exception:
                pass
            self.service_provider = None
        self.is_advertising = False
        self.connected_clients_count = 0
        return self.get_status()

    def get_status(self) -> Dict[str, Any]:
        return {
            "ble_supported": self.ble_supported,
            "is_advertising": self.is_advertising,
            "pc_ble_name": self.pc_ble_name,
            "service_uuid": str(CHRONOS_SERVICE_UUID),
            "connected_clients": self.connected_clients_count,
            "phone_connected": self.connected_clients_count > 0,
            "app_version": self.app_version,
            "error": self.ble_error,
        }

    def _on_tx_read_requested(self, sender: Any, args: Any) -> None:
        try:
            from winrt.windows.storage.streams import DataWriter

            deferral = args.get_deferral()
            req = args.get_request_async().get()
            dw = DataWriter()
            dw.write_bytes(bytes([0xAB, 0x00, 0x05, 0xFF, 0x91, 0x80, 0x01, 100]))
            req.respond_with_value(dw.detach_buffer())
            deferral.complete()
        except Exception:
            pass

    def _on_tx_subscribed_changed(self, sender: Any, args: Any) -> None:
        try:
            clients = sender.subscribed_clients
            count = len(clients) if clients is not None else 0
            was_connected = self.connected_clients_count > 0
            self.connected_clients_count = count
            is_connected = count > 0

            if self._event_loop and self._on_connection_cb and was_connected != is_connected:
                asyncio.run_coroutine_threadsafe(
                    self._on_connection_cb(is_connected), self._event_loop
                )

            if is_connected:
                threading.Thread(target=self._send_initial_handshake, daemon=True).start()
        except Exception:
            pass

    def _send_initial_handshake(self) -> None:
        """Sends ChronosESP32 `sendInfo()`, `sendBattery()`, and `setNotifyBattery(true)` after subscribe."""
        time.sleep(0.4)
        # 1. sendInfo() (CHRONOSESP_VERSION 1.8.0)
        info_cmd = bytes(
            [
                0xAB, 0x00, 0x11, 0xFF, 0x92, 0xC0,
                1, 80, 0x00, 0xFB, 0x1E, 0x40, 0xC0, 0x0E, 0x32, 0x28, 0x00, 0xE2, 0x03, 0x80,
            ]
        )
        self.send_command(info_cmd)
        time.sleep(0.2)
        # 2. sendBattery() (100%, charging)
        bat_cmd = bytes([0xAB, 0x00, 0x05, 0xFF, 0x91, 0x80, 0x01, 100])
        self.send_command(bat_cmd)
        time.sleep(0.2)
        # 3. setNotifyBattery(true)
        bat_req = bytes([0xAB, 0x00, 0x04, 0xFE, 0x91, 0x80, 0x01])
        self.send_command(bat_req)

    def send_esp_info(self) -> None:
        """Sends `ChronosESP32::sendESP()` hardware summary to the Chronos App's ESP32 tab."""
        esp_info = (
            "ChronosESP32 v1.8.0\n"
            "ESP32-C3 @160Mhz Cores:1 rev3\n"
            "RAM: 320kB + PSRAM: 0MB\n"
            "Flash: 4MB @80Mhz DIO\n"
            "SDK: v4.4.7-dirty\n"
            "Sketch: 1312kB (The Mochi v4.3.2)"
        ).encode("utf-8")
        length = len(esp_info)
        total_len = length + 3
        header = bytes([0xAB, (total_len >> 8) & 0xFF, total_len & 0xFF, 0xFE, 0x92, 0x80])
        self.send_command(header + esp_info, force_chunked=True)

    def send_command(self, data: bytes, force_chunked: bool = False) -> None:
        if self.tx_char is None:
            return
        try:
            from winrt.windows.storage.streams import DataWriter

            if len(data) <= 20 and not force_chunked:
                dw = DataWriter()
                dw.write_bytes(data)
                self.tx_char.notify_value_async(dw.detach_buffer())
            else:
                dw0 = DataWriter()
                dw0.write_bytes(data[:20])
                self.tx_char.notify_value_async(dw0.detach_buffer())
                time.sleep(0.08)

                offset = 20
                seq = 0
                while offset < len(data):
                    chunk_payload = data[offset : offset + 19]
                    chunk = bytes([seq & 0xFF]) + chunk_payload
                    dw = DataWriter()
                    dw.write_bytes(chunk)
                    self.tx_char.notify_value_async(dw.detach_buffer())
                    time.sleep(0.08)
                    offset += len(chunk_payload)
                    seq += 1
        except Exception:
            pass

    def _on_rx_write_requested(self, sender: Any, args: Any) -> None:
        """Handles incoming BLE GATT writes from the Chronos Smartphone App on `6e400002-...`."""
        try:
            from winrt.windows.devices.bluetooth.genericattributeprofile import GattWriteOption
            from winrt.windows.storage.streams import DataReader

            deferral = args.get_deferral()

            async def _process_write() -> None:
                try:
                    req = await args.get_request_async()
                    if req is not None and req.value is not None:
                        dr = DataReader.from_buffer(req.value)
                        raw = bytearray(req.value.length)
                        dr.read_bytes(raw)
                        if req.option == GattWriteOption.WRITE_WITH_RESPONSE:
                            req.respond()
                        self._handle_raw_ble_bytes(bytes(raw))
                finally:
                    deferral.complete()

            if self._event_loop:
                asyncio.run_coroutine_threadsafe(_process_write(), self._event_loop)
            else:
                deferral.complete()
        except Exception:
            pass

    def _handle_raw_ble_bytes(self, p_data: bytes) -> None:
        """Exact byte-level packet assembler ported from `ChronosESP32::onWrite`."""
        length = len(p_data)
        if length == 0:
            return

        self.last_rx_timestamp = time.time()
        if self.connected_clients_count == 0:
            self.connected_clients_count = 1
            if self._event_loop and self._on_connection_cb:
                asyncio.run_coroutine_threadsafe(
                    self._on_connection_cb(True), self._event_loop
                )

        if length >= 4 and (p_data[0] in (0xAB, 0xEA)) and (p_data[3] in (0xFE, 0xFF)):
            expected = (p_data[1] * 256) + p_data[2] + 3
            self._incoming_expected_len = min(expected, 1020)
            self._incoming_buf[:length] = p_data
            if self._incoming_expected_len <= length:
                self._dispatch_assembled_packet(bytes(self._incoming_buf[: self._incoming_expected_len]))
        else:
            seq = p_data[0]
            j = 20 + (seq * 19)
            payload = p_data[1:]
            end_pos = min(1024, j + len(payload))
            self._incoming_buf[j:end_pos] = payload[: end_pos - j]
            if self._incoming_expected_len > 0 and self._incoming_expected_len <= end_pos:
                self._dispatch_assembled_packet(bytes(self._incoming_buf[: self._incoming_expected_len]))

    def _dispatch_assembled_packet(self, pkt: bytes) -> None:
        """Exact command dispatcher ported from `ChronosESP32::dataReceived`."""
        length = len(pkt)
        if length < 5:
            return

        if pkt[0] == 0xAB:
            cmd = pkt[4]

            # 0x72: Notification / Incoming Call Alert
            if cmd == 0x72 and length >= 8:
                icon = pkt[6]
                state = pkt[7]
                raw_msg = pkt[8:length].decode("utf-8", errors="replace").strip("\x00").strip()

                if icon == 0x01:
                    # Incoming phone call ringer
                    if self._event_loop and self._on_notification_cb:
                        asyncio.run_coroutine_threadsafe(
                            self._on_notification_cb("Cuộc gọi đến", "Đang đổ chuông", raw_msg or "Điện thoại"),
                            self._event_loop,
                        )
                    return

                if state == 0x02 and raw_msg:
                    app_name = CHRONOS_APP_NAMES.get(icon, "Chronos")
                    title, message = self._split_title(raw_msg, app_name)
                    if self._event_loop and self._on_notification_cb:
                        asyncio.run_coroutine_threadsafe(
                            self._on_notification_cb(app_name, title, message),
                            self._event_loop,
                        )

            # 0x91: Phone Battery Level
            elif cmd == 0x91 and pkt[3] == 0xFE and length >= 8:
                charging = pkt[6] == 1
                bat_level = int(pkt[7])
                if self._on_battery_cb:
                    self._on_battery_cb(bat_level, charging)

            # 0xCA: Chronos App Version Handshake -> Reply with sendESP()
            elif cmd == 0xCA and pkt[3] == 0xFE and length >= 8:
                self.app_version = pkt[8:length].decode("utf-8", errors="ignore").strip("\x00")
                threading.Thread(target=self.send_esp_info, daemon=True).start()

            # 0xCC: Chunked Transfer Toggle
            elif cmd == 0xCC and pkt[3] == 0xFE and length >= 6:
                self._chunked_transfer = pkt[5] != 0x00

            # 0xEF: Google Maps Turn-by-Turn Navigation Data
            elif cmd == 0xEF and pkt[3] == 0xFE and length >= 6:
                mode = pkt[5]
                if mode == 0x80 and length >= 13:
                    # Extract null-terminated strings: title, duration, distance, eta, directions
                    parts = pkt[12:length].split(b"\x00")
                    strs = [p.decode("utf-8", errors="replace").strip() for p in parts]
                    title = strs[0] if len(strs) > 0 else "Google Maps"
                    duration = strs[1] if len(strs) > 1 else ""
                    distance = strs[2] if len(strs) > 2 else ""
                    eta = strs[3] if len(strs) > 3 else duration
                    directions = strs[4] if len(strs) > 4 else title

                    dir_code = "STRAIGHT"
                    combined_nav = f"{title} {directions}".lower()
                    if any(w in combined_nav for w in ("trái", "left")):
                        dir_code = "LEFT"
                    elif any(w in combined_nav for w in ("phải", "right")):
                        dir_code = "RIGHT"

                    street = directions or title or "Google Maps"
                    if self._event_loop and self._on_navigation_cb:
                        asyncio.run_coroutine_threadsafe(
                            self._on_navigation_cb(dir_code, distance or "100m", street, eta or "5p"),
                            self._event_loop,
                        )

        elif pkt[0] == 0xEA and length >= 7 and pkt[4] == 0x7E:
            sub = pkt[5]
            if sub == 0x01:
                city = pkt[7:length].decode("utf-8", errors="replace").strip("\x00")
                if city and self._on_weather_cb:
                    self._on_weather_cb(city)

    @staticmethod
    def _split_title(raw_text: str, default_app: str) -> tuple[str, str]:
        idx = raw_text.find(":")
        nl_idx = raw_text.find("\n")
        if 0 < idx < 30 and (nl_idx == -1 or nl_idx > idx):
            return raw_text[:idx].strip(), raw_text[idx + 1 :].strip()
        return default_app, raw_text.strip()


chronos_ble_server = ChronosBLEGattServer()
