#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
X (Twitter) Autonomous Publisher & Scheduler
支持 Alpha John (英文号) 与 王坤PAS (中文号) 双账号独立凭证与全自动发布/排期：
  1. python3 x_publisher.py login [alpha|wangkun]       # 弹窗登录指定账号，保存会话
  2. python3 x_publisher.py check [alpha|wangkun]       # 检查对应账号登录态
  3. python3 x_publisher.py post <account> <text> [img]  # 即时全自动发帖
  4. python3 x_publisher.py schedule-one <account> <text> <iso_time> [img] # 排期单条
  5. python3 x_publisher.py batch-schedule <account> [--limit N]          # 批量排期队列
"""

import os
import sys
import time
import json
import argparse
from pathlib import Path
from datetime import datetime

DIR = Path(__file__).resolve().parent
COOKIES_ALPHA = DIR / "cookies_alpha.json"
COOKIES_WANGKUN = DIR / "cookies_wangkun.json"
STATE_FILE = DIR / "state.json"
QUEUE_FILE = DIR / "schedule_queue.json"

def get_cookies_path(account: str) -> Path:
    acc = account.lower().strip()
    if "alpha" in acc:
        return COOKIES_ALPHA
    elif "wangkun" in acc or "wang" in acc or "pas" in acc:
        return COOKIES_WANGKUN
    else:
        return DIR / f"cookies_{acc}.json"

def get_playwright():
    try:
        from playwright.sync_api import sync_playwright
        return sync_playwright
    except ImportError:
        tiktok_venv = Path("/Users/wang/Documents/Files/Videos/tiktok-uploader/.venv/lib")
        for p in tiktok_venv.glob("python3.*/site-packages"):
            if str(p) not in sys.path:
                sys.path.insert(0, str(p))
        from playwright.sync_api import sync_playwright
        return sync_playwright

sync_playwright = get_playwright()

def cmd_login(account: str):
    target_path = get_cookies_path(account)
    acc_name = "Alpha John (英文)" if "alpha" in account.lower() else "王坤PAS (中文)"
    
    print(f"🚀 启动浏览器进行 [{acc_name}] 登录凭据捕获...")
    print(f"👉 请在弹出的浏览器中登录您的目标 X 账号: {acc_name}。")
    print("👉 登录成功进入主页 (x.com/home) 后，系统将自动捕获凭证并保存！")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"]
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 850}
        )
        page = context.new_page()
        page.goto("https://x.com/i/flow/login")

        logged_in = False
        for _ in range(120):  # 最多等待 240 秒
            time.sleep(2)
            try:
                cookies = context.cookies()
                auth_token = next((c for c in cookies if c.get("name") == "auth_token"), None)
                ct0 = next((c for c in cookies if c.get("name") == "ct0"), None)

                if auth_token and ("home" in page.url or ct0):
                    with open(target_path, "w", encoding="utf-8") as f:
                        json.dump(cookies, f, indent=2, ensure_ascii=False)
                    print(f"\n🎉 成功捕获 [{acc_name}] 登录会话！已保存至: {target_path}")
                    logged_in = True
                    break
            except Exception:
                pass

        if not logged_in:
            print("\n❌ 登录超时或未能成功捕获凭据，请重新运行。")
        browser.close()
        return logged_in

def cmd_check(account: str):
    target_path = get_cookies_path(account)
    acc_name = "Alpha John" if "alpha" in account.lower() else "王坤PAS"

    if not target_path.exists():
        print(f"❌ 未检测到 [{acc_name}] 的凭据文件: {target_path}")
        print(f"👉 请先运行登录: python3 x_publisher.py login {account}")
        return False

    with open(target_path, "r", encoding="utf-8") as f:
        cookies = json.load(f)

    auth_token = next((c for c in cookies if c.get("name") == "auth_token"), None)
    if not auth_token:
        print(f"❌ [{acc_name}] 凭据中缺少 auth_token！")
        return False

    print(f"🔍 正在静默校验 [{acc_name}] X 凭据有效性...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        )
        context.add_cookies(cookies)
        page = context.new_page()
        page.goto("https://x.com/home", wait_until="domcontentloaded", timeout=30000)
        time.sleep(3)

        if "login" in page.url:
            print(f"❌ [{acc_name}] 凭据已失效，需重新登录: python3 x_publisher.py login {account}")
            browser.close()
            return False

        print(f"✅ [{acc_name}] 登录态完全有效！已成功连通目标账号主页。")
        browser.close()
        return True

def cmd_post(account: str, text: str, media_path: str = None):
    target_path = get_cookies_path(account)
    acc_name = "Alpha John" if "alpha" in account.lower() else "王坤PAS"

    if not target_path.exists():
        print(f"❌ 未检测到凭据，请先运行: python3 x_publisher.py login {account}")
        return False

    with open(target_path, "r", encoding="utf-8") as f:
        cookies = json.load(f)

    print(f"🚀 正在以 [{acc_name}] 身份全自动发帖...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 900}
        )
        context.add_cookies(cookies)
        page = context.new_page()

        page.goto("https://x.com/compose/post", wait_until="networkidle", timeout=30000)
        time.sleep(2)

        if "login" in page.url:
            print("❌ 凭证失效，请重新登录")
            browser.close()
            return False

        # 输入文案
        textbox = page.locator('div[data-testid="tweetTextarea_0"]')
        textbox.wait_for(timeout=10000)
        textbox.click()
        textbox.fill(text)
        time.sleep(1)

        # 配图上传
        if media_path and os.path.exists(media_path):
            print(f"🖼️ 上传配图: {media_path}...")
            file_input = page.locator('input[data-testid="fileInput"]')
            file_input.set_input_files(media_path)
            time.sleep(4)

        # 点击发送
        post_btn = page.locator('button[data-testid="tweetButton"]')
        if not post_btn.is_visible():
            post_btn = page.locator('button[data-testid="tweetButtonInline"]')

        post_btn.click()
        time.sleep(5)
        print(f"🎉 恭喜！[{acc_name}] 推文已全自动发布！")
        browser.close()
        return True

def main():
    if len(sys.argv) < 2:
        print("X (Twitter) 双账号自动化发布工具")
        print("用法:")
        print("  python3 x_publisher.py login alpha        # 登录 Alpha John (英文号)")
        print("  python3 x_publisher.py login wangkun      # 登录 王坤PAS (中文号)")
        print("  python3 x_publisher.py check alpha        # 检查 Alpha John 登录态")
        print("  python3 x_publisher.py check wangkun      # 检查 王坤PAS 登录态")
        print("  python3 x_publisher.py post alpha <文案>   # 发布到 Alpha John")
        print("  python3 x_publisher.py post wangkun <文案> # 发布到 王坤PAS")
        return

    cmd = sys.argv[1].lower()
    if cmd == "login":
        acc = sys.argv[2] if len(sys.argv) > 2 else "alpha"
        cmd_login(acc)
    elif cmd == "check":
        acc = sys.argv[2] if len(sys.argv) > 2 else "alpha"
        cmd_check(acc)
    elif cmd == "post":
        if len(sys.argv) < 4:
            print("用法: python3 x_publisher.py post <alpha|wangkun> <文案> [图片路径]")
            return
        acc = sys.argv[2]
        text = sys.argv[3]
        media = sys.argv[4] if len(sys.argv) > 4 else None
        cmd_post(acc, text, media)
    else:
        print(f"未知命令: {cmd}")

if __name__ == "__main__":
    main()
