from __future__ import annotations
import base64
import json
import os
import subprocess
import time
import urllib.request
import urllib.parse
from http.cookies import SimpleCookie
from pathlib import Path
from typing import Dict, Optional, Tuple, Any, Callable

PASSPORT_QUERY = (
    "aid=2503&app_name=novelapp&version_code=57700&device_platform=web&channel=novel"
    "&sdk_version=1.6.1&passport_sdk_version=2.0.0&new_user=0"
)
ORIGIN = "https://fanqienovel.com"
NEXT_URL = urllib.parse.quote(f"{ORIGIN}/")

class AuthManager:
    """番茄小说官方账号认证与 Session 管理器"""

    def __init__(self, base_dir: Optional[Path] = None):
        if base_dir:
            self.base_dir = Path(base_dir)
        else:
            self.base_dir = Path.home() / ".fanqie_reader"
        self.auth_file = self.base_dir / "auth.json"
        self.qr_file = self.base_dir / "qrcode.png"
        self.cookies: Dict[str, str] = {}
        self.user_info: Dict[str, Any] = {}
        self.load()

    def load(self) -> None:
        if self.auth_file.exists():
            try:
                with open(self.auth_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.cookies = data.get("cookies", {})
                    self.user_info = data.get("user_info", {})
            except Exception:
                self.cookies = {}
                self.user_info = {}

    def save(self) -> None:
        self.base_dir.mkdir(parents=True, exist_ok=True)
        temp_file = self.auth_file.with_suffix(".tmp")
        try:
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump({
                    "cookies": self.cookies,
                    "user_info": self.user_info,
                    "updated_at": time.time()
                }, f, ensure_ascii=False, indent=2)
            temp_file.replace(self.auth_file)
        except Exception:
            if temp_file.exists():
                temp_file.unlink(missing_ok=True)

    def logout(self) -> None:
        self.cookies = {}
        self.user_info = {}
        if self.auth_file.exists():
            self.auth_file.unlink(missing_ok=True)

    def is_logged_in(self) -> bool:
        return bool(self.cookies.get("sessionid") or self.cookies.get("sid_tt"))

    def get_cookie_header(self) -> str:
        return "; ".join([f"{k}={v}" for k, v in self.cookies.items()])

    def set_cookie_str(self, cookie_str: str) -> None:
        """从原生 Cookie 字符串解析并保存"""
        cookie = SimpleCookie()
        cookie.load(cookie_str)
        for key, morsel in cookie.items():
            self.cookies[key] = morsel.value
        self.save()

    def _extract_cookies_from_headers(self, headers: Any) -> None:
        # 兼容 urllib set-cookie
        for h in headers.get_all("Set-Cookie", []):
            sc = SimpleCookie()
            sc.load(h)
            for k, morsel in sc.items():
                if morsel.value:
                    self.cookies[k] = morsel.value

    def fetch_user_profile(self) -> Optional[Dict[str, Any]]:
        """检查登录态并获取用户信息"""
        if not self.is_logged_in():
            return None
        
        url = f"{ORIGIN}/api/reader/user/info"
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Cookie": self.get_cookie_header(),
            "Referer": f"{ORIGIN}/"
        })
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode())
                if data.get("code") == 0:
                    d = data.get("data", {})
                    self.user_info = {
                        "user_id": d.get("user_id", ""),
                        "user_name": d.get("user_name", "") or d.get("name", "番茄读者"),
                        "avatar_url": d.get("avatar_url", ""),
                        "is_vip": d.get("is_vip", False)
                    }
                    self.save()
                    return self.user_info
        except Exception:
            pass
        return self.user_info or {"user_name": "已登录用户"}

    def get_display_name(self) -> str:
        if not self.is_logged_in():
            return "未登录"
        return self.user_info.get("user_name") or "已登录"

    def request_qrcode(self) -> Tuple[str, str, int]:
        """
        向官方请求登录二维码
        返回 (token, qr_image_path, expire_time)
        """
        url = f"{ORIGIN}/passport/web/get_qrcode/?next={NEXT_URL}&{PASSPORT_QUERY}"
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Referer": f"{ORIGIN}/"
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            self._extract_cookies_from_headers(resp.headers)
            res_json = json.loads(resp.read().decode())
            data = res_json.get("data", {})
            token = data.get("token", "")
            b64_img = data.get("qrcode", "")
            expire_time = int(data.get("expire_time", 0))

            if not token or not b64_img:
                raise RuntimeError("获取二维码失败，请稍后重试。")

            # 保存二维码图片
            img_bytes = base64.b64decode(b64_img)
            with open(self.qr_file, "wb") as f:
                f.write(img_bytes)

            return token, str(self.qr_file), expire_time

    def check_qr_status(self, token: str) -> Tuple[str, Optional[str]]:
        """
        检查二维码扫码状态
        返回 (status, redirect_url)
        status: 'new' | 'scanned' | 'confirmed' | 'expired'
        """
        url = f"{ORIGIN}/passport/web/check_qrconnect/?next={NEXT_URL}&token={token}&{PASSPORT_QUERY}"
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Cookie": self.get_cookie_header(),
            "Referer": f"{ORIGIN}/"
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            self._extract_cookies_from_headers(resp.headers)
            res_json = json.loads(resp.read().decode())
            d = res_json.get("data", {})
            status = d.get("status", "new")
            redirect_url = d.get("redirect_url")
            
            if status == "confirmed":
                # 保存最新 Cookie
                self.save()
                self.fetch_user_profile()

            return status, redirect_url

    def open_qr_image(self) -> None:
        """在 macOS 上自动用 Preview 预览二维码图片"""
        if self.qr_file.exists():
            try:
                subprocess.run(["open", str(self.qr_file)], check=False)
            except Exception:
                pass
