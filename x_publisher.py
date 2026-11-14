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
    clean_acc = "alpha" if "alpha" in account.lower() else "wangkun"
    
    print(f"🚀 启动纯原生 Chrome 浏览器进行 [{acc_name}] 登录凭据捕获...")
    print(f"👉 请在弹出的浏览器中登录您的目标 X 账号: {acc_name}。")
    print("👉 登录成功进入主页 (x.com/home) 后，系统将自动捕获凭证并关闭窗口！")

    chrome_path = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    profile_dir = DIR / f".chrome_profile_{clean_acc}"
    port = 9556 if clean_acc == "alpha" else 9557

    cmd = [
        chrome_path,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={profile_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-blink-features=AutomationControlled",
        "https://x.com/login"
    ]

    import subprocess
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(2)

    logged_in = False
    try:
        with sync_playwright() as p:
            browser = p.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
            ctx = browser.contexts[0] if browser.contexts else None

            for i in range(180):  # 最多等待 360 秒
                time.sleep(2)
                try:
                    if not ctx:
                        if proc.poll() is not None:
                            break
                        continue

                    current_url = ctx.pages[0].url if ctx.pages else ""
                    cookies = ctx.cookies()
                    auth_token = next((c for c in cookies if c.get("name") == "auth_token" and c.get("value")), None)
                    ct0 = next((c for c in cookies if c.get("name") == "ct0" and c.get("value")), None)

                    if auth_token and ("home" in current_url or ct0 or current_url in ["https://x.com/", "https://twitter.com/"]):
                        time.sleep(1)
                        cookies = ctx.cookies()
                        with open(target_path, "w", encoding="utf-8") as f:
                            json.dump(cookies, f, indent=2, ensure_ascii=False)
                        print(f"\n🎉 成功捕获 [{acc_name}] 登录会话！已保存至: {target_path}")
                        logged_in = True
                        break
                except Exception as e:
                    if "target closed" in str(e).lower() or "connection closed" in str(e).lower():
                        break

            try:
                browser.close()
            except Exception:
                pass
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=3)
        except Exception:
            pass

    if not logged_in:
        print("\n❌ 登录超时或未能成功捕获凭据，请重新运行。")
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

def schedule_tweet(account: str, text: str, iso_time: str, headless: bool = False) -> bool:
    target_path = get_cookies_path(account)
    acc_name = "Alpha John" if "alpha" in account.lower() else "王坤PAS"
    tz_name = "America/Los_Angeles" if "alpha" in account.lower() else "Asia/Shanghai"

    if not target_path.exists():
        print(f"❌ 未检测到 [{acc_name}] 凭据文件: {target_path}")
        return False

    with open(target_path, "r", encoding="utf-8") as f:
        cookies = json.load(f)

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=headless)
        context = browser.new_context(
            viewport={"width": 1280, "height": 850},
            timezone_id=tz_name
        )
        context.add_cookies(cookies)
        page = context.new_page()

        try:
            page.goto("https://x.com/compose/post", timeout=30000)
            page.wait_for_timeout(3000)

            # 1. 查找推文输入框并填入文案
            textbox = page.locator('div[data-testid="tweetTextarea_0"]').first
            textbox.wait_for(timeout=10000)
            textbox.click()
            textbox.fill(text)
            page.wait_for_timeout(1000)
            # 按 ESC 关闭可能弹出的 hashtag 或 @ 补全下拉浮窗
            page.keyboard.press("Escape")
            page.wait_for_timeout(500)

            # 2. 点击 Schedule 按钮
            sch_btn = page.locator('button[data-testid="scheduleOption"]').first
            sch_btn.click()
            page.wait_for_timeout(2000)

            # 3. 日历弹窗选择时间 (使用全局 select 定位，完美兼容中英文界面)
            selects = page.locator("select")
            selects.first.wait_for(timeout=10000)

            dt = datetime.fromisoformat(iso_time)
            month_val = str(dt.month)
            day_val = str(dt.day)
            year_val = str(dt.year)
            hour_12 = dt.hour % 12
            if hour_12 == 0:
                hour_12 = 12
            hour_val = str(hour_12)
            minute_val = f"{dt.minute:02d}"
            ampm_val = "am" if dt.hour < 12 else "pm"

            selects.nth(0).select_option(value=month_val)
            selects.nth(1).select_option(value=day_val)
            selects.nth(2).select_option(value=year_val)
            selects.nth(3).select_option(value=hour_val)
            selects.nth(4).select_option(value=minute_val)
            selects.nth(5).select_option(value=ampm_val)
            page.wait_for_timeout(1000)

            # 4. 点击 Confirm (通过 data-testid 定位，语言无关)
            confirm_btn = page.locator('button[data-testid="scheduledConfirmationPrimaryAction"]')
            confirm_btn.click(force=True)
            page.wait_for_timeout(1500)

            # 5. 点击 Schedule 发帖 (通过 data-testid 定位)
            schedule_post_btn = page.locator('button[data-testid="tweetButton"]').first
            schedule_post_btn.click(force=True)
            page.wait_for_timeout(4000)

            print(f"🎉 成功为 [{acc_name}] 排期推文！计划发布时间: {iso_time}")
            browser.close()
            return True
        except Exception as e:
            print(f"❌ 排期失败: {e}")
            browser.close()
            return False

def cmd_batch_schedule(account: str, limit: int = 5):
    acc_key = "alpha_john" if "alpha" in account.lower() else "wangkun_pas"
    acc_name = "Alpha John" if "alpha" in account.lower() else "王坤PAS"
    
    if not QUEUE_FILE.exists():
        print(f"❌ 未找到队列文件: {QUEUE_FILE}，请先运行 python3 scheduler.py")
        return

    with open(QUEUE_FILE, "r", encoding="utf-8") as f:
        queue_data = json.load(f)

    acc_queue = queue_data.get(acc_key, {}).get("queue", [])
    pending_items = [item for item in acc_queue if item.get("status") == "pending"]

    print(f"📋 [{acc_name}] 待排期推文共 {len(pending_items)} 条，本次计划排期前 {min(limit, len(pending_items))} 条...")

    success_count = 0
    for idx, item in enumerate(pending_items[:limit], 1):
        print(f"\n[{idx}/{min(limit, len(pending_items))}] 正在为 {item['repo']} 进行定时排期 (预计: {item['scheduled_time']})...")
        ok = schedule_tweet(account, item["content"], item["iso_time"], headless=False)
        if ok:
            item["status"] = "scheduled"
            item["scheduled_at"] = datetime.now().isoformat()
            success_count += 1
            # 及时保存进度
            with open(QUEUE_FILE, "w", encoding="utf-8") as f:
                json.dump(queue_data, f, indent=2, ensure_ascii=False)
        time.sleep(3)

    print(f"\n🏁 [{acc_name}] 排期任务完成！成功排期 {success_count} 条推文。")

def main():
    if len(sys.argv) < 2:
        print("X (Twitter) 双账号自动化发布与排期工具")
        print("用法:")
        print("  python3 x_publisher.py login alpha             # 登录 Alpha John (英文号)")
        print("  python3 x_publisher.py login wangkun           # 登录 王坤PAS (中文号)")
        print("  python3 x_publisher.py check alpha             # 检查 Alpha John 登录态")
        print("  python3 x_publisher.py check wangkun           # 检查 王坤PAS 登录态")
        print("  python3 x_publisher.py schedule alpha [--limit N]   # 批量为 Alpha John 执行排期")
        print("  python3 x_publisher.py schedule wangkun [--limit N] # 批量为 王坤PAS 执行排期")
        print("  python3 x_publisher.py post alpha <文案>        # 即时发布到 Alpha John")
        print("  python3 x_publisher.py post wangkun <文案>      # 即时发布到 王坤PAS")
        return

    cmd = sys.argv[1].lower()
    if cmd == "login":
        acc = sys.argv[2] if len(sys.argv) > 2 else "alpha"
        cmd_login(acc)
    elif cmd == "check":
        acc = sys.argv[2] if len(sys.argv) > 2 else "alpha"
        cmd_check(acc)
    elif cmd == "schedule":
        acc = sys.argv[2] if len(sys.argv) > 2 else "alpha"
        limit = 5
        if "--limit" in sys.argv:
            idx = sys.argv.index("--limit")
            if idx + 1 < len(sys.argv):
                limit = int(sys.argv[idx + 1])
        cmd_batch_schedule(acc, limit)
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
