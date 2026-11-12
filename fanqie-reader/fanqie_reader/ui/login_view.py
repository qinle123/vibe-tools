from __future__ import annotations
import time
from typing import Optional

from ..auth import AuthManager
from ..text_engine import str_visual_width, truncate_to_width, pad_to_width
from .terminal import (
    TerminalApp,
    RESET, BOLD, DIM, INVERSE,
    FG_GREEN, FG_CYAN, FG_YELLOW, FG_WHITE, FG_GRAY, FG_RED,
    BG_BLUE, BG_DARK_GRAY,
    KEY_ENTER, KEY_ESC, KEY_BACKSPACE
)

class LoginView:
    """官方账号扫码登录与管理视图"""

    def __init__(self, term: TerminalApp, auth: AuthManager):
        self.term = term
        self.auth = auth

        self.mode: str = "qr"  # 'qr' 或 'cookie'
        self.cookie_input: str = ""
        self.token: str = ""
        self.qr_path: str = ""
        self.expire_time: int = 0
        self.qr_status: str = "new"  # new, scanned, confirmed, expired, error
        self.msg: str = ""
        self.last_check_time: float = 0.0

        if not self.auth.is_logged_in():
            self._fetch_new_qr()

    def _fetch_new_qr(self) -> None:
        self.qr_status = "fetching"
        self.msg = "正在向番茄官方请求登录二维码..."
        self.render()
        try:
            self.token, self.qr_path, self.expire_time = self.auth.request_qrcode()
            self.qr_status = "new"
            self.msg = "已生成二维码！已自动弹窗，请使用番茄小说App或抖音扫码"
            self.last_check_time = time.time()
            # 自动在 macOS 上打开二维码图片窗口
            self.auth.open_qr_image()
        except Exception as e:
            self.qr_status = "error"
            self.msg = f"获取二维码失败: {e}"

    def render(self) -> None:
        cols, rows = self.term.get_size()
        buffer = []
        buffer.append("\033[H")

        # 1. 顶部标题
        title = " 👤 番茄小说 · 账号同步与登录"
        sub = "支持同步手机书架与阅读进度 "
        gap = max(1, cols - str_visual_width(title) - str_visual_width(sub))
        header = title + (" " * gap) + sub
        buffer.append(f"{INVERSE}{BOLD}{truncate_to_width(header, cols)}{RESET}\n")

        # 2. 当前登录状态
        status_line = ""
        if self.auth.is_logged_in():
            name = self.auth.get_display_name()
            status_line = f"  当前状态: {FG_GREEN}● 已登录 ({name}){RESET}  [按 x 退出登录]"
        else:
            status_line = f"  当前状态: {FG_YELLOW}○ 未登录{RESET}"
        buffer.append(f"\033[K\n\033[K{status_line}\n\033[K{FG_GRAY}{'─' * cols}{RESET}\n")

        # 3. 主操作内容区域
        if self.mode == "qr":
            if self.qr_status == "fetching":
                box = [
                    "",
                    f"{FG_YELLOW}正在生成登录二维码...{RESET}",
                    ""
                ]
            elif self.qr_status == "scanned":
                box = [
                    "",
                    f"{FG_GREEN}{BOLD}📱 手机已扫码！{RESET}",
                    f"{FG_YELLOW}请在手机上点击【确认登录】...{RESET}",
                    ""
                ]
            elif self.qr_status == "confirmed":
                box = [
                    "",
                    f"{FG_GREEN}{BOLD}🎉 登录成功！{RESET}",
                    "正在自动同步云端书架与阅读记录...",
                    ""
                ]
            elif self.qr_status == "expired":
                box = [
                    "",
                    f"{FG_RED}二维码已过期{RESET}",
                    "按 [r] 重新获取新二维码，按 [Esc] 返回",
                    ""
                ]
            elif self.qr_status == "error":
                box = [
                    "",
                    f"{FG_RED}{self.msg}{RESET}",
                    "按 [r] 重试，或按 [c] 切换到 Cookie 导入模式",
                    ""
                ]
            else:
                box = [
                    "",
                    f"{FG_CYAN}{BOLD}【番茄官方扫码登录】{RESET}",
                    "",
                    f"1. 屏幕已自动弹出 {FG_YELLOW}qrcode.png{RESET} 二维码图片窗口",
                    f"2. 请打开手机 {FG_GREEN}番茄小说 App{RESET} 或 {FG_GREEN}抖音 App{RESET} 扫一扫",
                    "3. 在手机上点击【确认授权登录】",
                    "",
                    f"{FG_GRAY}提示：若未弹出窗口，可在浏览器或访达打开 ~/.fanqie_reader/qrcode.png{RESET}",
                    f"{FG_GRAY}或者按 [c] 切换为直接粘贴 Cookie 模式{RESET}",
                    ""
                ]
            
            for line in box:
                buffer.append(f"\033[K  {line}\n")

        else:
            # Cookie 导入模式
            cookie_box = [
                "",
                f"{FG_CYAN}{BOLD}【直接导入 Cookie 模式】{RESET}",
                "如果你已在网页端登录 fanqienovel.com，可将 Cookie 复制粘贴到下方：",
                "",
                f"Cookie: {FG_YELLOW}{truncate_to_width(self.cookie_input + '█', cols - 12)}{RESET}",
                "",
                f"{FG_GRAY}[Enter]保存并验证  [Esc]返回扫码模式{RESET}",
                ""
            ]
            for line in cookie_box:
                buffer.append(f"\033[K  {line}\n")

        # 补全空行
        used_rows = 15
        for _ in range(max(0, rows - used_rows - 3)):
            buffer.append("\033[K\n")

        # 4. 底部指引
        if self.mode == "qr":
            b_left = " [r]刷新二维码  [c]切换Cookie导入  [x]退出登录"
            b_right = " [Esc]返回书架 "
        else:
            b_left = " [Enter]保存Cookie  [Esc]返回扫码模式"
            b_right = " "
        
        b_gap = max(1, cols - str_visual_width(b_left) - str_visual_width(b_right))
        footer = b_left + (" " * b_gap) + b_right
        buffer.append(f"{INVERSE}{truncate_to_width(footer, cols)}{RESET}")

        self.term.write("".join(buffer))
        self.term.flush()

    def run(self) -> bool:
        """运行登录交互，若登录状态改变或成功则返回 True"""
        logged_in_before = self.auth.is_logged_in()

        while True:
            # 如果在二维码模式，周期性轮询二维码状态（每 2 秒）
            if self.mode == "qr" and self.qr_status in ("new", "scanned"):
                now = time.time()
                if now - self.last_check_time >= 2.0:
                    self.last_check_time = now
                    try:
                        st, _ = self.auth.check_qr_status(self.token)
                        if st != self.qr_status:
                            self.qr_status = st
                            if st == "confirmed":
                                self.render()
                                time.sleep(1.0)
                                return True
                    except Exception:
                        pass

            self.render()
            key = self.term.read_key(0.3, text_input=self.mode == "cookie")
            if not key:
                continue

            if key == KEY_ESC:
                if self.mode == "cookie":
                    self.mode = "qr"
                else:
                    break

            elif self.mode == "qr":
                if key in ('r', 'R'):
                    self._fetch_new_qr()
                elif key in ('c', 'C'):
                    self.mode = "cookie"
                elif key in ('x', 'X'):
                    self.auth.logout()
                    self._fetch_new_qr()

            elif self.mode == "cookie":
                if key == KEY_ENTER:
                    if self.cookie_input.strip():
                        self.auth.set_cookie_str(self.cookie_input.strip())
                        self.auth.fetch_user_profile()
                        return True
                elif key == KEY_BACKSPACE:
                    if self.cookie_input:
                        self.cookie_input = self.cookie_input[:-1]
                elif len(key) >= 1 and ord(key[0]) >= 32:
                    self.cookie_input += key

        return self.auth.is_logged_in() != logged_in_before
