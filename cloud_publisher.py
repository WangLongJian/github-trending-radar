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

from tweet_text import fit_tweet, split_to_fit, weighted_len
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


def _find_rest_id(obj):
    """在 CreateTweet / CreateNoteTweet（Premium 长文）的返回里递归找新推文 id。"""
    if isinstance(obj, dict):
        tr = obj.get("tweet_results")
        if isinstance(tr, dict) and isinstance(tr.get("result"), dict):
            rid = tr["result"].get("rest_id") or tr["result"].get("tweet", {}).get("rest_id")
            if rid:
                return rid
        for v in obj.values():
            rid = _find_rest_id(v)
            if rid:
                return rid
    elif isinstance(obj, list):
        for v in obj:
            rid = _find_rest_id(v)
            if rid:
                return rid
    return None


def _parse_create_tweet(body: dict):
    """取新推文 id；X 有时返回 200 但带 errors（重复内容、风控等）。"""
    if body.get("errors"):
        msgs = "; ".join(f"{e.get('code')}: {e.get('message')}" for e in body["errors"])
        return None, msgs
    rid = _find_rest_id(body.get("data"))
    if rid:
        return rid, None
    return None, f"返回里没有 rest_id: {json.dumps(body, ensure_ascii=False)[:300]}"


def _is_create(r):
    # 普通推文走 CreateTweet，Premium 长文走 CreateNoteTweet
    return ("CreateTweet" in r.url or "CreateNoteTweet" in r.url) and r.request.method == "POST"


def _post_one(page, url: str, text: str, acc_name: str, tag: str, dry_run: bool = False):
    """打开 url（主页=新推文，推文详情页=回复），在内联输入框发一条。
    成功返回推文 id；dry_run 返回 True；失败返回 None。"""
    # X 偶尔加载很慢（日志里出现过 goto 超时），重试一次
    for attempt in (1, 2):
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            break
        except Exception as e:
            if attempt == 2:
                raise
            print(f"   [Warn] 打开 {url} 超时，重试: {e}")
    page.wait_for_timeout(4000)

    if "login" in page.url or "logout" in page.url or "/i/flow" in page.url:
        print(f"❌ [{acc_name}] 登录凭证失效（被跳到 {page.url}），请重新导出 Cookie。")
        _save_shot(page, f"{tag}_login")
        return None

    box = page.locator('[data-testid="tweetTextarea_0"]').first
    box.wait_for(state="visible", timeout=20000)
    box.click()
    page.wait_for_timeout(500)
    # insert_text 走真实输入事件，X 的编辑器能识别；fill 对 contenteditable 不稳
    page.keyboard.insert_text(text)
    page.wait_for_timeout(1500)

    if not box.inner_text().strip():
        print(f"❌ [{acc_name}] 输入框里没有内容，输入失败。")
        _save_shot(page, f"{tag}_empty")
        return None

    post_btn = page.locator('[data-testid="tweetButtonInline"]').first
    post_btn.wait_for(state="visible", timeout=10000)
    if post_btn.get_attribute("aria-disabled") == "true" or post_btn.is_disabled():
        print(f"❌ [{acc_name}] 发布按钮不可点（可能超字数或内容被拦）。")
        _save_shot(page, f"{tag}_disabled")
        return None

    if dry_run:
        print(f"✅ [dry-run] [{acc_name}] 已登录，输入框和发布按钮正常，未点击发布。")
        _save_shot(page, f"{tag}_dryrun")
        return True

    # 不用 Ctrl+Enter：无头浏览器里它不会提交，反而会在光标处插入换行（串推第 4 条出现过）。
    # 直接在按钮元素上触发 click()，不受浮层遮挡影响；没捕获到请求才再用鼠标强制点一次。
    resp = None
    post_btn.evaluate("el => el.scrollIntoView({block: 'center'})")
    page.wait_for_timeout(500)
    try:
        with page.expect_response(_is_create, timeout=15000) as resp_info:
            post_btn.evaluate("el => el.click()")
        resp = resp_info.value
    except Exception:
        print("   [Warn] 按钮 click() 没有触发发帖请求，改用鼠标点击")
    if resp is None:
        with page.expect_response(_is_create, timeout=30000) as resp_info:
            post_btn.click(force=True)
        resp = resp_info.value

    if resp.status != 200:
        print(f"❌ [{acc_name}] 发帖请求返回 HTTP {resp.status}: {resp.text()[:300]}")
        _save_shot(page, f"{tag}_http{resp.status}")
        return None

    tweet_id, err = _parse_create_tweet(resp.json())
    if not tweet_id:
        print(f"❌ [{acc_name}] X 拒绝了这条推文: {err}")
        _save_shot(page, f"{tag}_rejected")
        return None
    return tweet_id


def publish_thread(account: str, parts, done_ids=None, dry_run: bool = False):
    """发一条推文或一组串推。parts 是每条的文字；done_ids 是上次已发出的部分（断点续发）。
    第 1 条在主页发，之后每条回复上一条。返回 (已发出的 id 列表, 是否全部发完)。"""
    acc_name = "Alpha John" if "alpha" in account.lower() else "王坤PAS"
    tag = "alpha" if "alpha" in account.lower() else "wangkun"
    ids = list(done_ids or [])
    cookies = get_cookies_for(account)
    if not cookies:
        print(f"❌ 未能加载 [{acc_name}] 的 Cookies 凭据！请检查 Secrets 或本地文件。")
        return ids, False

    kind = f"{len(parts)} 条串推" if len(parts) > 1 else "推文"
    print(f"🚀 正在以 [{acc_name}] 身份发布{kind}{'（dry-run，不点发布）' if dry_run else ''}"
          f"{f'，从第 {len(ids) + 1} 条续发' if ids else ''}...")
    with sync_playwright() as p:
        # X_BROWSER_CHANNEL=msedge 时用系统自带的 Edge（本机计划任务用），否则用 Playwright 自带 Chromium
        channel = os.getenv("X_BROWSER_CHANNEL") or None
        browser = p.chromium.launch(
            headless=True,
            channel=channel,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 900}
        )
        context.add_cookies(cookies)
        page = context.new_page()
        try:
            for idx in range(len(ids), len(parts)):
                url = "https://x.com/home" if not ids else f"https://x.com/i/status/{ids[-1]}"
                rid = _post_one(page, url, parts[idx], acc_name, tag, dry_run=dry_run)
                if dry_run:
                    browser.close()
                    return ids, bool(rid)
                if not rid:
                    browser.close()
                    return ids, False
                ids.append(rid)
                print(f"🎉 [{acc_name}] 第 {idx + 1}/{len(parts)} 条发布成功: https://x.com/i/status/{rid}")
                if idx + 1 < len(parts):
                    page.wait_for_timeout(3000)
            browser.close()
            return ids, True
        except Exception as e:
            print(f"❌ 发布异常: {e}")
            _save_shot(page, f"{tag}_exception")
            browser.close()
            return ids, False


def publish_tweet(account: str, text: str, dry_run: bool = False):
    """单条发布（兼容旧调用）：成功返回推文 id，dry_run 成功返回 True，失败返回 False。"""
    ids, ok = publish_thread(account, [text], dry_run=dry_run)
    if dry_run:
        return ok
    return ids[0] if ok and ids else False


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


def build_parts(item, premium: bool):
    """把队列项目变成要发的每条文字。
    - 有 thread（中文号串推）：每条单独按 X 长度规则检查，超长就拆
    - Premium 账号（Alpha John）：长文原样发，只做上限保护
    - 其它：压到 280 以内"""
    url = item.get("url", "")
    if item.get("thread"):
        parts = []
        for t in item["thread"]:
            parts.extend(split_to_fit(t))
        return parts
    text = item["content"].strip()
    if premium:
        return [text[:24000]]
    fitted = fit_tweet(text, url)
    if fitted != text:
        print(f"   ✂️ 文案按 X 规则调整长度: {weighted_len(text)} -> {weighted_len(fitted)}")
    return [fitted]


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
            # 上次串推只发了一半的优先续发，否则发热度最高的
            partial = [it for it in pending if it.get("thread_ids")]
            due_item = partial[0] if partial else max(pending, key=_heat)
            print(f"\n📢 [{acc_name}] 发布热度最高的待发项目: {due_item['repo']} (热度 {_heat(due_item):,}, 当前: {now_local.strftime('%Y-%m-%d %H:%M %Z')})")
            parts = build_parts(due_item, premium=(acc == "alpha"))
            if os.getenv("X_DRY_RUN"):
                _ids, ok = publish_thread(acc, parts, dry_run=True)
                print(f"🧪 [{acc_name}] 空跑模式：{'登录与输入正常' if ok else '检查失败'}，未发帖、未改状态。")
                if not ok:
                    failures.append(acc_name)
                continue_after = True
            else:
                continue_after = False
                ids, ok = publish_thread(acc, parts, done_ids=due_item.get("thread_ids"))
                if ids:
                    due_item["thread_ids"] = ids
                    due_item["tweet_url"] = f"https://x.com/i/status/{ids[0]}"
            if continue_after:
                pass
            elif ok:
                due_item["status"] = "posted"
                due_item["posted_at"] = datetime.now(ZoneInfo("UTC")).isoformat()
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
