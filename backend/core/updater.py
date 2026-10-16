"""
Neito Agent - Auto-Update Engine
================================
Handles checking GitHub Releases for newer builds, downloading either the
Setup Installer (.exe) or Portable Package (.zip), and performing in-place
atomic application updates on Windows 10/11.
"""

from __future__ import annotations

import os
import sys
import json
import shutil
import tempfile
import zipfile
import subprocess
import threading
from pathlib import Path
from typing import Dict, Any, Optional, Tuple, Callable

import httpx

APP_VERSION = "1.0.0"
GITHUB_REPO = "Neito112/Neito-agent"
GITHUB_LATEST_RELEASE_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"


def parse_semver(v: str) -> Tuple[int, ...]:
    """Converts 'v1.0.2' or '1.2.0-beta' into a comparable tuple of ints."""
    clean = (v or "").strip().lstrip("vV")
    clean = clean.split("-")[0]
    parts = []
    for p in clean.split("."):
        try:
            parts.append(int(p))
        except ValueError:
            parts.append(0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


def is_running_as_frozen() -> bool:
    """Checks if running as a compiled PyInstaller executable."""
    return getattr(sys, "frozen", False)


def is_installed_setup() -> bool:
    """Detects if installed via Inno Setup (in Program Files or has unins000.exe)."""
    if not is_running_as_frozen():
        return False
    app_dir = Path(sys.executable).resolve().parent
    return (app_dir / "unins000.exe").exists() or "programs" in str(app_dir).lower()


class UpdateEngine:
    def __init__(self):
        self.current_version = APP_VERSION
        self.latest_release_cache: Optional[Dict[str, Any]] = None
        self._download_lock = threading.Lock()
        self.download_progress = {"status": "idle", "percent": 0, "bytes": 0, "total": 0, "error": None}

    def check_for_updates(self, timeout: float = 6.0) -> Dict[str, Any]:
        """Queries GitHub Releases API and determines if a newer release exists."""
        try:
            headers = {
                "User-Agent": f"Neito-Agent-Updater/{self.current_version}",
                "Accept": "application/vnd.github.v3+json",
            }
            resp = httpx.get(GITHUB_LATEST_RELEASE_API, headers=headers, timeout=timeout, follow_redirects=True)
            if resp.status_code != 200:
                return {
                    "ok": False,
                    "error": f"GitHub API returned {resp.status_code}",
                    "current_version": self.current_version,
                    "has_update": False,
                }

            data = resp.json()
            self.latest_release_cache = data
            latest_tag = data.get("tag_name", "").strip()
            v_curr = parse_semver(self.current_version)
            v_latest = parse_semver(latest_tag)

            has_update = v_latest > v_curr

            portable_url = ""
            installer_url = ""
            assets = data.get("assets", [])
            for asset in assets:
                name = asset.get("name", "").lower()
                dl_url = asset.get("browser_download_url", "")
                if "portable" in name or name.endswith(".zip"):
                    portable_url = dl_url
                elif "setup" in name or name.endswith(".exe"):
                    installer_url = dl_url

            # Determine best download based on running mode
            if is_installed_setup() and installer_url:
                target_url = installer_url
                target_kind = "installer"
            elif portable_url:
                target_url = portable_url
                target_kind = "portable"
            else:
                target_url = installer_url or portable_url
                target_kind = "installer" if installer_url else "portable"

            return {
                "ok": True,
                "current_version": self.current_version,
                "latest_version": latest_tag.lstrip("vV"),
                "has_update": has_update,
                "release_name": data.get("name", latest_tag),
                "release_notes": data.get("body", ""),
                "published_at": data.get("published_at", ""),
                "html_url": data.get("html_url", ""),
                "download_url": target_url,
                "download_kind": target_kind,
                "portable_url": portable_url,
                "installer_url": installer_url,
            }
        except Exception as e:
            return {
                "ok": False,
                "error": str(e),
                "current_version": self.current_version,
                "has_update": False,
            }

    def start_download_thread(self, download_url: str, on_finished: Optional[Callable[[Optional[Path]], None]] = None):
        """Starts asynchronous background download."""
        t = threading.Thread(target=self._run_download, args=(download_url, on_finished), daemon=True)
        t.start()

    def _run_download(self, download_url: str, on_finished: Optional[Callable[[Optional[Path]], None]] = None):
        with self._download_lock:
            self.download_progress = {"status": "downloading", "percent": 0, "bytes": 0, "total": 0, "error": None}
            temp_dir = Path(tempfile.gettempdir()) / "neito_update"
            temp_dir.mkdir(parents=True, exist_ok=True)

            filename = download_url.split("/")[-1].split("?")[0]
            if not filename:
                filename = "neito_update_payload.bin"
            out_path = temp_dir / filename

            try:
                headers = {"User-Agent": f"Neito-Agent-Updater/{self.current_version}"}
                with httpx.stream("GET", download_url, headers=headers, follow_redirects=True, timeout=60.0) as stream:
                    if stream.status_code != 200:
                        raise RuntimeError(f"HTTP {stream.status_code} while downloading update")

                    total_bytes = int(stream.headers.get("Content-Length", 0))
                    downloaded = 0

                    with open(out_path, "wb") as f:
                        for chunk in stream.iter_bytes(chunk_size=65536):
                            if chunk:
                                f.write(chunk)
                                downloaded += len(chunk)
                                pct = int((downloaded / total_bytes * 100)) if total_bytes > 0 else 50
                                self.download_progress = {
                                    "status": "downloading",
                                    "percent": min(99, pct),
                                    "bytes": downloaded,
                                    "total": total_bytes,
                                    "error": None,
                                }

                self.download_progress = {
                    "status": "completed",
                    "percent": 100,
                    "bytes": downloaded,
                    "total": total_bytes,
                    "file_path": str(out_path),
                    "error": None,
                }
                if on_finished:
                    on_finished(out_path)
            except Exception as e:
                self.download_progress = {
                    "status": "error",
                    "percent": 0,
                    "bytes": 0,
                    "total": 0,
                    "error": str(e),
                }
                if on_finished:
                    on_finished(None)

    def apply_update(self, payload_path: Optional[Path] = None) -> Dict[str, Any]:
        """Applies downloaded update and exits application."""
        if not payload_path:
            p_str = self.download_progress.get("file_path")
            if not p_str or not Path(p_str).exists():
                return {"ok": False, "error": "Không tìm thấy tệp cập nhật đã tải về."}
            payload_path = Path(p_str)

        filename = payload_path.name.lower()

        # 1. Setup Installer (.exe)
        if filename.endswith(".exe"):
            try:
                # Launch installer with elevated or user prompt
                subprocess.Popen([str(payload_path)])
                def _delayed_exit():
                    import time
                    time.sleep(0.5)
                    os._exit(0)
                threading.Thread(target=_delayed_exit, daemon=True).start()
                return {"ok": True, "message": "Đang khởi động trình cài đặt..."}
            except Exception as e:
                return {"ok": False, "error": f"Lỗi khởi chạy bộ cài: {e}"}

        # 2. Portable Package (.zip)
        elif filename.endswith(".zip"):
            try:
                app_dir = Path(sys.executable).resolve().parent if is_running_as_frozen() else Path.cwd()
                temp_dir = Path(tempfile.gettempdir()) / "neito_update"
                bat_path = temp_dir / "apply_patch.bat"

                bat_content = f"""@echo off
chcp 65001 >nul
echo [Neito Updater] Đang đợi tiến trình cũ đóng...
timeout /t 2 /nobreak >nul

echo [Neito Updater] Đang giải nén phiên bản mới...
tar -xf "{payload_path}" -C "{app_dir}"

echo [Neito Updater] Khởi chạy Neito mới...
start "" "{app_dir}\\Neito.exe"
del "%~f0"
"""
                bat_path.write_text(bat_content, encoding="utf-8")
                subprocess.Popen(["cmd.exe", "/c", str(bat_path)], creationflags=0x08000000 if hasattr(subprocess, "CREATE_NO_WINDOW") else 0)

                def _delayed_exit():
                    import time
                    time.sleep(0.5)
                    os._exit(0)
                threading.Thread(target=_delayed_exit, daemon=True).start()
                return {"ok": True, "message": "Đang áp dụng bản cập nhật Portable..."}
            except Exception as e:
                return {"ok": False, "error": f"Lỗi giải nén bản Portable: {e}"}

        return {"ok": False, "error": f"Định dạng tệp không được hỗ trợ: {filename}"}


update_engine = UpdateEngine()
