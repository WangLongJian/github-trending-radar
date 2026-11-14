#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Cloud Publisher for GitHub Actions
运行在 GitHub Actions 上的云端无人值守发帖引擎：
1. 从 GitHub Secrets 读取 COOKIES_ALPHA 和 COOKIES_WANGKUN
2. 判断当前时区时刻 (PT 太平洋时间 vs CST 北京时间)
3. 提取对应账号待发推文并全自动云端发布
4. 回写状态至 schedule_queue.json 与 state.json
"""

import os
import sys
import json
import time
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path

DIR = Path(__file__).resolve().parent
QUEUE_FILE = DIR / "schedule_queue.json"
STATE_FILE = DIR / "state.json"

PT_TZ = ZoneInfo("America/Los_Angeles")
CST_TZ = ZoneInfo("Asia/Shanghai")
DAILY_SLOTS = [9, 12, 15, 18, 21]

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

def get_cookies_for(account: str):
    clean = "alpha" if "alpha" in account.lower() else "wangkun"
    env_var = "COOKIES_ALPHA" if clean == "alpha" else "COOKIES_WANGKUN"
    
    # 优先从环境变量 (GitHub Secrets) 读取
    raw = os.getenv(env_var)
    if raw:
        try:
            return json.loads(raw)
        except Exception as e:
            print(f"[Warn] Failed to parse env {env_var}: {e}")
            
    # 本地文件后备
    cookie_file = DIR / f"cookies_{clean}.json"
    if cookie_file.exists():
        with open(cookie_file, "r", encoding="utf-8") as f:
            return json.load(f)
            
    return None

def publish_tweet(account: str, text: str) -> bool:
    acc_name = "Alpha John" if "alpha" in account.lower() else "王坤PAS"
    cookies = get_cookies_for(account)
    if not cookies:
        print(f"❌ 未能加载 [{acc_name}] 的 Cookies 凭据！请检查 Secrets 或本地文件。")
        return False

    print(f"🚀 正在云端以 [{acc_name}] 身份静默发布推文...")
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 900}
        )
        context.add_cookies(cookies)
        page = context.new_page()

        try:
            page.goto("https://x.com/compose/post", wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(3000)

            # 检查是否被踢到登录页
            if "login" in page.url:
                print(f"❌ [{acc_name}] 登录凭证失效，请更新 Secrets 中的 Cookie。")
                browser.close()
                return False

            textbox = page.locator('div[data-testid="tweetTextarea_0"]').first
            textbox.wait_for(timeout=10000)
            textbox.click()
            textbox.fill(text)
            page.wait_for_timeout(1000)
            page.keyboard.press("Escape")
            page.wait_for_timeout(500)

            post_btn = page.locator('button[data-testid="tweetButton"]').first
            post_btn.click(force=True)
            page.wait_for_timeout(5000)

            print(f"🎉 恭喜！[{acc_name}] 推文已 100% 成功发布至 X！")
            browser.close()
            return True
        except Exception as e:
            print(f"❌ 发布异常: {e}")
            browser.close()
            return False

def run_scheduled_job(force_account: str = None):
    now_utc = datetime.now(ZoneInfo("UTC"))
    now_pt = datetime.now(PT_TZ)
    now_cst = datetime.now(CST_TZ)
    
    print(f"⏰ 当前时间检查:")
    print(f"   UTC: {now_utc.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"   PT:  {now_pt.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"   CST: {now_cst.strftime('%Y-%m-%d %H:%M:%S')}")

    if not QUEUE_FILE.exists():
        print(f"❌ 找不到队列文件: {QUEUE_FILE}")
        return

    with open(QUEUE_FILE, "r", encoding="utf-8") as f:
        queue_data = json.load(f)

    accounts = ["alpha", "wangkun"] if not force_account else [force_account]

    for acc in accounts:
        acc_key = "alpha_john" if acc == "alpha" else "wangkun_pas"
        acc_name = "Alpha John" if acc == "alpha" else "王坤PAS"
        tz = PT_TZ if acc == "alpha" else CST_TZ
        now_local = datetime.now(tz)

        queue_list = queue_data.get(acc_key, {}).get("queue", [])
        
        # 查找当前时间已到达预定时刻的待发推文
        due_item = None
        for item in queue_list:
            if item.get("status") == "pending":
                item_dt = datetime.fromisoformat(item["iso_time"])
                if now_local >= item_dt or force_account:
                    due_item = item
                    break

        if not due_item:
            print(f"☕ [{acc_name}] 当前暂无到期的待发推文。")
            continue

        print(f"\n📢 [{acc_name}] 触发到期发布任务: {due_item['repo']} (计划: {due_item['scheduled_time']}, 当前: {now_local.strftime('%Y-%m-%d %H:%M:%S %Z')})")
        ok = publish_tweet(acc, due_item["content"])
        if ok:
            due_item["status"] = "posted"
            due_item["posted_at"] = datetime.now().isoformat()
            
            with open(QUEUE_FILE, "w", encoding="utf-8") as f:
                json.dump(queue_data, f, indent=2, ensure_ascii=False)
            print(f"✅ [{acc_name}] 任务状态已更新为 posted！")

if __name__ == "__main__":
    force = sys.argv[1].lower() if len(sys.argv) > 1 else None
    run_scheduled_job(force)
