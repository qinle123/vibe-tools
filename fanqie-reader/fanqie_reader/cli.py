from __future__ import annotations
import sys
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

from .api import FanqieAPI
from .storage import StorageManager
from .auth import AuthManager
from .ui.terminal import TerminalApp
from .ui.shelf_view import ShelfView
from .ui.search_view import SearchView
from .ui.reader_view import ReaderView
from .ui.login_view import LoginView

__version__ = "0.1.1"

def headless_sync(api: FanqieAPI, storage: StorageManager, auth: AuthManager) -> None:
    """非交互式命令行书架与进度云端同步（并发极速拉取）"""
    if not auth.is_logged_in():
        print("提示：当前尚未登录番茄小说账号。")
        print("请运行 'fq login' 扫码登录或按 'fq login --cookie <cookie>' 导入账号。")
        return

    print(f"[*] 正在为用户 [{auth.get_display_name()}] 同步云端书架与阅读进度...")
    cookie_header = auth.get_cookie_header()
    try:
        cloud_books = api.get_cloud_bookshelf(cookie_header)
        cloud_progress = api.get_cloud_progress(cookie_header)
        storage.apply_cloud_shelf_order(cloud_books)
        pos_map = {str(p.get("book_id")): p for p in cloud_progress if p.get("book_id")}

        shelf_items = storage.load_shelf()
        existing_ids = {it.book.book_id for it in shelf_items}
        cloud_ids = list(dict.fromkeys(
            str(r.get("book_id", "")) for r in cloud_books
            if str(r.get("book_id", ""))
        ))
        cloud_times = {}
        for row in cloud_books:
            book_id = str(row.get("book_id", ""))
            if book_id:
                cloud_times[book_id] = max(cloud_times.get(book_id, 0.0), float(row.get("last_operate_time", 0) or 0))
        to_fetch_ids = [book_id for book_id in cloud_ids if book_id not in existing_ids]

        new_books = 0
        total_to_fetch = len(to_fetch_ids)

        if total_to_fetch > 0:
            print(f"[*] 检测到 {total_to_fetch} 本手机端新增书籍，正在并发拉取元数据...")
            completed_count = 0
            with ThreadPoolExecutor(max_workers=8) as executor:
                future_to_id = {executor.submit(api.get_book_info, bid): bid for bid in to_fetch_ids}
                for future in as_completed(future_to_id):
                    completed_count += 1
                    try:
                        book = future.result()
                        storage.add_to_shelf(book, added_at=cloud_times.get(book.book_id))
                        new_books += 1
                    except Exception:
                        pass
                    if completed_count % 10 == 0 or completed_count == total_to_fetch:
                        print(f"    进度: {completed_count}/{total_to_fetch}")

        # 对齐阅读进度
        updated_pos = 0
        for b_id, p_info in pos_map.items():
            shelf_item = storage.get_shelf_item(b_id)
            if not shelf_item:
                continue
            c_item_id = str(p_info.get("item_id", ""))
            c_index = int(p_info.get("index", 0) or 0)
            c_time = float(p_info.get("read_timestamp", 0))

            chapters = storage.get_chapters_meta(b_id)
            if chapters and c_item_id:
                matched_index = next((i for i, chapter in enumerate(chapters) if chapter.item_id == c_item_id), None)
                if matched_index is not None:
                    c_index = matched_index
            if c_item_id:
                ch_title = f"第 {c_index + 1} 章"
                if chapters and 0 <= c_index < len(chapters):
                    ch_title = chapters[c_index].title

                storage.update_cloud_progress(b_id, c_index, c_item_id, ch_title, c_time)
                updated_pos += 1

        print(f"[✔] 同步成功！新增 {new_books} 本云端藏书，对齐 {updated_pos} 本手机阅读进度。")
    except Exception as e:
        print(f"[✘] 同步失败: {e}")

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="fanqie",
        description="番茄小说 macOS 终端沉浸式命令行阅读器"
    )
    parser.add_argument("-v", "--version", action="version", version=f"fanqie-reader v{__version__}")
    
    subparsers = parser.add_subparsers(dest="command", help="子命令")

    # 搜索子命令
    search_parser = subparsers.add_parser("search", help="搜索小说")
    search_parser.add_argument("keyword", nargs="?", default="", help="小说关键词或作者")

    # 直接阅读子命令
    read_parser = subparsers.add_parser("read", help="直接阅读小说")
    read_parser.add_argument("book_id", help="番茄小说书籍 ID")

    # 查看书架
    shelf_parser = subparsers.add_parser("shelf", help="打开书架")

    # 登录子命令
    login_parser = subparsers.add_parser("login", help="番茄小说官方账号登录")
    login_parser.add_argument("--cookie", help="直接导入 Cookie 字符串进行登录")
    login_parser.add_argument("--logout", action="store_true", help="退出当前登录账号")
    login_parser.add_argument("--status", action="store_true", help="查看当前登录状态与用户信息")

    # 同步子命令
    sync_parser = subparsers.add_parser("sync", help="一键同步手机端书架与阅读进度")

    args = parser.parse_args()

    api = FanqieAPI()
    storage = StorageManager()
    auth = AuthManager()

    # 处理纯命令行工具操作（无需占用全屏终端模式）
    if args.command == "login":
        if args.logout:
            auth.logout()
            print("[✔] 已成功注销当前账号。")
            return
        if args.status:
            if auth.is_logged_in():
                user = auth.fetch_user_profile() or {}
                print(f"[★] 登录状态: 已登录")
                print(f"    用户昵称: {user.get('user_name', '番茄读者')}")
                print(f"    用户 ID: {user.get('user_id', '未知')}")
            else:
                print("○ 当前未登录。运行 'fq login' 可扫码登录。")
            return
        if args.cookie:
            auth.set_cookie_str(args.cookie)
            user = auth.fetch_user_profile()
            print(f"[✔] Cookie 导入成功！当前用户: {auth.get_display_name()}")
            headless_sync(api, storage, auth)
            return

    if args.command == "sync":
        headless_sync(api, storage, auth)
        return

    # 全屏交互界面
    term = TerminalApp()

    try:
        term.enter_raw_mode()

        if args.command == "login":
            # 打开交互式扫码登录界面
            login_view = LoginView(term, auth)
            changed = login_view.run()
            if changed and auth.is_logged_in():
                # 登录成功，顺带打开书架
                shelf_view = ShelfView(term, api, storage, auth)
                shelf_view.sync_mobile()
                shelf_view.run()

        elif args.command == "search":
            search_view = SearchView(term, api, storage, initial_query=args.keyword)
            chosen_book = search_view.run()
            if chosen_book:
                shelf_item = storage.get_shelf_item(chosen_book.book_id)
                if shelf_item:
                    shelf_view = ShelfView(term, api, storage, auth)
                    shelf_view._open_book_reader(shelf_item)
            else:
                # 返回书架
                shelf_view = ShelfView(term, api, storage, auth)
                shelf_view.run()

        elif args.command == "read":
            book_id = args.book_id
            shelf_item = storage.get_shelf_item(book_id)
            if not shelf_item:
                # 获取书籍详情并加入书架
                book, chapters = api.get_book_detail(book_id)
                shelf_item = storage.add_to_shelf(book)
                storage.save_chapters_meta(book_id, chapters)
            else:
                chapters = storage.get_chapters_meta(book_id)
                if not chapters:
                    book, chapters = api.get_book_detail(book_id)
                    shelf_item.book = book
                    storage.save_chapters_meta(book_id, chapters)

            reader = ReaderView(
                term=term,
                api=api,
                storage=storage,
                book=shelf_item.book,
                chapters=chapters,
                initial_chapter_index=shelf_item.last_chapter_index,
                initial_line_offset=shelf_item.line_offset
            )
            reader.run()

        else:
            # 默认打开主书架界面
            shelf_view = ShelfView(term, api, storage, auth)
            shelf_view.run()

    except KeyboardInterrupt:
        pass
    finally:
        term.restore_mode()

if __name__ == "__main__":
    main()
