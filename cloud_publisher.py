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

from tweet_text import fit_tweet, weighted_len
from slots import in_window, next_post_slots

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
            
    # 本地文件后备：优先 X_COOKIES_DIR（本机放在 ~/.secrets/x-auto-poster），其次项目目录
    cookie_dir = Path(os.getenv("X_COOKIES_DIR", DIR))
    cookie_file = cookie_dir / f"cookies_{clean}.json"
    if cookie_file.exists():
        with open(cookie_file, "r", encoding="utf-8") as f:
            return json.load(f)
            
    return None

SHOT_DIR = DIR / "debug_shots"


def _save_shot(page, tag: str):
    """失败时截图，GitHub Actions 会把 debug_shots/ 作为产物上传，方便排查。"""
    try:
        SHOT_DIR.mkdir(exist_ok=True)
        path = SHOT_DIR / f"{tag}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        page.screenshot(path=str(path), full_page=False)
        print(f"   📸 已保存截图: {path.name}")
    except Exception as e:
        print(f"   [Warn] 截图失败: {e}")


def _parse_create_tweet(body: dict):
    """从 CreateTweet 的返回里取推文 id；X 有时返回 200 但带 errors（重复内容、风控等）。"""
    if body.get("errors"):
        msgs = "; ".join(f"{e.get('code')}: {e.get('message')}" for e in body["errors"])
        return None, msgs
    try:
        rid = body["data"]["create_tweet"]["tweet_results"]["result"]["rest_id"]
        return rid, None
    except (KeyError, TypeError):
        return None, f"返回里没有 rest_id: {json.dumps(body, ensure_ascii=False)[:300]}"


def publish_tweet(account: str, text: str, dry_run: bool = False):
    """在 x.com/home 的内联输入框发帖，成功返回推文 id，失败返回 False。

    只有拿到 CreateTweet 的 200 返回且里面有新推文 id，才算成功。
    旧版在 /compose/post 弹窗里按了 Escape，会弹出“放弃帖子？”遮罩挡住发帖按钮，
    又不校验返回，导致一条没发却标成 posted。
    dry_run=True 时只登录、输入、检查按钮可点，不点发布。
    """
    acc_name = "Alpha John" if "alpha" in account.lower() else "王坤PAS"
    tag = "alpha" if "alpha" in account.lower() else "wangkun"
    cookies = get_cookies_for(account)
    if not cookies:
        print(f"❌ 未能加载 [{acc_name}] 的 Cookies 凭据！请检查 Secrets 或本地文件。")
        return False

    print(f"🚀 正在以 [{acc_name}] 身份发布推文{'（dry-run，不点发布）' if dry_run else ''}...")
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
            page.goto("https://x.com/home", wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(4000)

            if "login" in page.url or "logout" in page.url or "/i/flow" in page.url:
                print(f"❌ [{acc_name}] 登录凭证失效（被跳到 {page.url}），请重新导出 Cookie 更新 Secrets。")
                _save_shot(page, f"{tag}_login")
                browser.close()
                return False

            box = page.locator('[data-testid="tweetTextarea_0"]').first
            box.wait_for(state="visible", timeout=20000)
            box.click()
            page.wait_for_timeout(500)
            # insert_text 走真实输入事件，X 的编辑器能识别；fill 对 contenteditable 不稳
            page.keyboard.insert_text(text)
            page.wait_for_timeout(1500)

            typed = box.inner_text().strip()
            if not typed:
                print(f"❌ [{acc_name}] 输入框里没有内容，输入失败。")
                _save_shot(page, f"{tag}_empty")
                browser.close()
                return False

            post_btn = page.locator('[data-testid="tweetButtonInline"]').first
            post_btn.wait_for(state="visible", timeout=10000)
            if post_btn.get_attribute("aria-disabled") == "true" or post_btn.is_disabled():
                print(f"❌ [{acc_name}] 发布按钮不可点（可能超字数或内容被拦）。")
                _save_shot(page, f"{tag}_disabled")
                browser.close()
                return False

            if dry_run:
                print(f"✅ [dry-run] [{acc_name}] 已登录，输入框和发布按钮正常，未点击发布。")
                _save_shot(page, f"{tag}_dryrun")
                browser.close()
                return True

            # 光标还在输入框里，直接 Ctrl+Enter 提交（X 的官方快捷键），避开各种浮层挡按钮的问题。
            # 只有没捕获到 CreateTweet 请求时才改用强制点击，所以不会重复发帖。
            is_create = lambda r: "CreateTweet" in r.url and r.request.method == "POST"
            resp = None
            try:
                with page.expect_response(is_create, timeout=12000) as resp_info:
                    page.keyboard.press("Control+Enter")
                resp = resp_info.value
            except Exception:
                print("   [Warn] Ctrl+Enter 没有触发发帖请求，改为点击 Post 按钮")
            if resp is None:
                post_btn.evaluate("el => el.scrollIntoView({block: 'center'})")
                page.wait_for_timeout(500)
                with page.expect_response(is_create, timeout=30000) as resp_info:
                    post_btn.click(force=True)
                resp = resp_info.value

            if resp.status != 200:
                print(f"❌ [{acc_name}] CreateTweet 返回 HTTP {resp.status}: {resp.text()[:300]}")
                _save_shot(page, f"{tag}_http{resp.status}")
                browser.close()
                return False

            tweet_id, err = _parse_create_tweet(resp.json())
            if not tweet_id:
                print(f"❌ [{acc_name}] X 拒绝了这条推文: {err}")
                _save_shot(page, f"{tag}_rejected")
                browser.close()
                return False

            print(f"🎉 [{acc_name}] 发布成功: https://x.com/i/status/{tweet_id}")
            browser.close()
            return tweet_id
        except Exception as e:
            print(f"❌ 发布异常: {e}")
            _save_shot(page, f"{tag}_exception")
            browser.close()
            return False

def _heat(item) -> int:
    try:
        return int(item.get("heat_score") or 0)
    except (TypeError, ValueError):
        return 0


def reschedule_pending(queue_list, tz, now_utc):
    """把剩下的 pending 按热度从高到低，依次排到接下来的发帖时刻。"""
    pending = sorted((it for it in queue_list if it.get("status") == "pending"), key=_heat, reverse=True)
    slots = next_post_slots(now_utc, tz, len(pending))
    for it, slot in zip(pending, slots):
        it["scheduled_time"] = slot.strftime("%Y-%m-%d %H:%M:%S %Z")
        it["iso_time"] = slot.isoformat()
    # 队列里按时间顺序排，便于阅读
    others = [it for it in queue_list if it.get("status") != "pending"]
    queue_list[:] = others + sorted(pending, key=lambda it: it["iso_time"])


def run_scheduled_job(force_account: str = None):
    """每次运行：每个账号若在本地 09:00-24:00 窗口内，发 1 条热度最高的 pending；
    然后把剩下的按热度重新排到接下来的运行时刻。
    force_account 指定时忽略窗口，立即为该账号发 1 条。"""
    now_utc = datetime.now(ZoneInfo("UTC"))
    print("⏰ 当前时间检查:")
    print(f"   UTC: {now_utc.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"   PT:  {now_utc.astimezone(PT_TZ).strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"   CST: {now_utc.astimezone(CST_TZ).strftime('%Y-%m-%d %H:%M:%S')}")

    if not QUEUE_FILE.exists():
        print(f"❌ 找不到队列文件: {QUEUE_FILE}")
        return

    with open(QUEUE_FILE, "r", encoding="utf-8") as f:
        queue_data = json.load(f)

    accounts = ["alpha", "wangkun"] if not force_account else [force_account]
    failures = []

    for acc in accounts:
        acc_key = "alpha_john" if acc == "alpha" else "wangkun_pas"
        acc_name = "Alpha John" if acc == "alpha" else "王坤PAS"
        tz = PT_TZ if acc == "alpha" else CST_TZ
        now_local = now_utc.astimezone(tz)
        queue_list = queue_data.get(acc_key, {}).get("queue", [])

        pending = [it for it in queue_list if it.get("status") == "pending"]
        if not pending:
            print(f"☕ [{acc_name}] 队列里没有待发推文。")
        elif not force_account and not in_window(now_local):
            print(f"🌙 [{acc_name}] 当地 {now_local.strftime('%H:%M')} 不在 09:00-24:00 发帖窗口，本轮不发。")
        else:
            due_item = max(pending, key=_heat)
            print(f"\n📢 [{acc_name}] 发布热度最高的待发项目: {due_item['repo']} (热度 {_heat(due_item):,}, 当前: {now_local.strftime('%Y-%m-%d %H:%M %Z')})")
            text = fit_tweet(due_item["content"], due_item.get("url", ""))
            if text != due_item["content"]:
                print(f"   ✂️ 文案按 X 规则调整长度: {weighted_len(due_item['content'])} -> {weighted_len(text)}")
            if os.getenv("X_DRY_RUN"):
                ok = publish_tweet(acc, text, dry_run=True)
                print(f"🧪 [{acc_name}] 空跑模式：{'登录与输入正常' if ok else '检查失败'}，未发帖、未改状态。")
                if not ok:
                    failures.append(acc_name)
                tweet_id = None
            else:
                tweet_id = publish_tweet(acc, text)
            if os.getenv("X_DRY_RUN"):
                pass
            elif tweet_id:
                due_item["status"] = "posted"
                due_item["posted_at"] = datetime.now(ZoneInfo("UTC")).isoformat()
                due_item["tweet_url"] = f"https://x.com/i/status/{tweet_id}"
                due_item.pop("last_error_at", None)
                print(f"✅ [{acc_name}] 任务状态已更新为 posted！")
            else:
                # 不改成 posted，下一轮继续重试；连续失败 3 次标为 failed 跳过，避免卡死队列
                due_item["fail_count"] = due_item.get("fail_count", 0) + 1
                due_item["last_error_at"] = datetime.now(ZoneInfo("UTC")).isoformat()
                if due_item["fail_count"] >= 3:
                    due_item["status"] = "failed"
                    print(f"⛔ [{acc_name}] {due_item['repo']} 连续失败 3 次，标记为 failed 并跳过。")
                failures.append(acc_name)

        reschedule_pending(queue_list, tz, now_utc)
        nxt = [it for it in queue_list if it.get("status") == "pending"]
        if nxt:
            print(f"🗓️ [{acc_name}] 重新排期（按热度）:")
            for it in nxt:
                print(f"     {it['scheduled_time']}  {it['repo']}  热度 {_heat(it):,}")

    with open(QUEUE_FILE, "w", encoding="utf-8") as f:
        json.dump(queue_data, f, indent=2, ensure_ascii=False)

    if failures:
        print(f"\n❌ 本轮发布失败的账号: {', '.join(failures)}")
        sys.exit(1)

if __name__ == "__main__":
    args = [a.lower() for a in sys.argv[1:]]
    if "--dry-run" in args:
        # 只验证登录和输入框，不发帖：python cloud_publisher.py --dry-run alpha
        accs = [a for a in args if a != "--dry-run"] or ["alpha", "wangkun"]
        results = {a: publish_tweet(a, "dry-run test, not posted", dry_run=True) for a in accs}
        sys.exit(0 if all(results.values()) else 1)
    force = args[0] if args else None
    run_scheduled_job(force)
