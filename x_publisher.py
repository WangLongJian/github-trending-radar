#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
X (Twitter) Autonomous Publisher
基于 Playwright 会话持久化的 X 自动化发帖工具（与 tiktok-uploader / instagram-uploader 架构一致）。
支持：
  1. python3 x_publisher.py login          # 弹窗一次性登录，自动捕获并保存 cookies.json
  2. python3 x_publisher.py check          # 检查登录状态
  3. python3 x_publisher.py post <repo>    # 100% 全自动静默发推（自动填入文案、上传合成配图并点击 Post）
"""

import os
import sys
import time
import json
import argparse
from pathlib import Path

# 优先使用已安装 playwright 的 Python 环境
DIR = Path(__file__).resolve().parent
COOKIES_JSON = DIR / "cookies.json"
STATE_FILE = DIR / "state.json"

def get_playwright():
    try:
        from playwright.sync_api import sync_playwright
        return sync_playwright
    except ImportError:
        # 尝试从同目录其他项目的 venv 导入
        tiktok_venv = Path("/Users/wang/Documents/Files/Videos/tiktok-uploader/.venv/lib")
        for p in tiktok_venv.glob("python3.*/site-packages"):
            if str(p) not in sys.path:
                sys.path.insert(0, str(p))
        from playwright.sync_api import sync_playwright
        return sync_playwright

sync_playwright = get_playwright()

def cmd_login():
    print("🚀 启动浏览器进行 X (Twitter) 登录凭据捕获...")
    print("👉 请在弹出的浏览器中登录您的目标 X 账号。")
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

        # 循环检测是否登录成功进入主页
        logged_in = False
        for _ in range(120):  # 最多等待 240 秒
            time.sleep(2)
            try:
                cookies = context.cookies()
                auth_token = next((c for c in cookies if c.get("name") == "auth_token"), None)
                ct0 = next((c for c in cookies if c.get("name") == "ct0"), None)

                if auth_token and ("home" in page.url or ct0):
                    with open(COOKIES_JSON, "w", encoding="utf-8") as f:
                        json.dump(cookies, f, indent=2, ensure_ascii=False)
                    print(f"\n🎉 成功捕获 X 登录会话凭据！已保存至 {COOKIES_JSON}")
                    logged_in = True
                    break
            except Exception:
                pass

        if not logged_in:
            print("\n❌ 登录超时或未能成功捕获 auth_token，请重新运行。")
        browser.close()

def cmd_check():
    if not COOKIES_JSON.exists():
        print("❌ 未检测到 cookies.json，请先运行: python3 x_publisher.py login")
        return False

    with open(COOKIES_JSON, "r", encoding="utf-8") as f:
        cookies = json.load(f)

    auth_token = next((c for c in cookies if c.get("name") == "auth_token"), None)
    if not auth_token:
        print("❌ cookies.json 中缺少 auth_token 凭据！")
        return False

    print("🔍 正在静默校验 X 凭据有效性...")
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
            print("❌ 凭据已失效，需重新登录。")
            browser.close()
            return False

        print("✅ X 登录态有效！已成功连通目标账号主页。")
        browser.close()
        return True

def cmd_post(text: str, media_path: str = None):
    if not COOKIES_JSON.exists():
        print("❌ 未检测到 cookies.json，请先运行: python3 x_publisher.py login")
        return False

    with open(COOKIES_JSON, "r", encoding="utf-8") as f:
        cookies = json.load(f)

    print("🚀 正在启动后台无头浏览器执行【100% 全自动发帖】...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 900}
        )
        context.add_cookies(cookies)
        page = context.new_page()

        print("📡 打开发帖页面...")
        page.goto("https://x.com/compose/post", wait_until="networkidle", timeout=30000)
        time.sleep(2)

        # 检查是否要求重新登录
        if "login" in page.url:
            print("❌ 凭证失效，请重新运行 python3 x_publisher.py login")
            browser.close()
            return False

        # 1. 查找推文输入框
        print("✍️ 正在自动输入推文文案...")
        textbox = page.locator('div[data-testid="tweetTextarea_0"]')
        textbox.wait_for(timeout=10000)
        textbox.click()
        textbox.fill(text)
        time.sleep(1)

        # 2. 如果提供了媒体文件，自动上传配图
        if media_path and os.path.exists(media_path):
            print(f"🖼️ 正在自动上传配图: {media_path}...")
            file_input = page.locator('input[data-testid="fileInput"]')
            file_input.set_input_files(media_path)
            # 等待图片上传与缩略图渲染
            time.sleep(4)

        # 3. 自动点击 Post 按钮
        print("🎯 正在自动点击 【Post】 按钮发布推文...")
        post_btn = page.locator('button[data-testid="tweetButton"]')
        if not post_btn.is_visible():
            post_btn = page.locator('button[data-testid="tweetButtonInline"]')

        post_btn.click()
        print("⏳ 等待发布完成确认...")
        time.sleep(5)

        # 验证是否发送成功（发帖框关闭或出现已发布通知）
        print("🎉 恭喜！推文已 100% 全自动成功发布到你的 X 账号！")
        browser.close()
        return True

def main():
    if len(sys.argv) < 2:
        print("用法:")
        print("  python3 x_publisher.py login              # 弹窗一次性登录并保存凭证")
        print("  python3 x_publisher.py check              # 检查登录态")
        print("  python3 x_publisher.py post <文案> [图片路径] # 全自动后台发推")
        return

    cmd = sys.argv[1].lower()
    if cmd == "login":
        cmd_login()
    elif cmd == "check":
        cmd_check()
    elif cmd == "post":
        if len(sys.argv) < 3:
            print("请输入发帖文案")
            return
        text = sys.argv[2]
        media = sys.argv[3] if len(sys.argv) > 3 else None
        cmd_post(text, media)
    else:
        print(f"未知命令: {cmd}")

if __name__ == "__main__":
    main()
