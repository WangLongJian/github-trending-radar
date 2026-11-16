#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Dynamic Heat-Priority & 24H Jitter Scheduler for X (Twitter)
核心规则:
1. 仅排期未来 24 小时内的发布窗口
2. 严格按热度（单日爆发增速 stars_today 权重优先，总星次之）从高到低倒序排序
3. 越热门的项目排在越靠前的时间槽位
4. 动态插队预占 (Preemption): 若新抓取的项目热度超过已排期但未发布的项目，自动按热度插队到前排，热度较低项目自动顺延
5. 随机发推时间: 按 4 小时为一个发布区块 (240 分钟)，每个区块内随机抽取 1～240 分钟作为精确发布时刻，彻底拟人化防风控
"""

import os
import sys
import json
import re
import random
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import List, Dict, Any, Optional

from tweet_text import fit_tweet
from slots import next_post_slots

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(ROOT_DIR, "state.json")
CANDIDATES_MD = os.path.join(ROOT_DIR, "candidates.md")
QUEUE_FILE = os.path.join(ROOT_DIR, "schedule_queue.json")

PT_TZ = ZoneInfo("America/Los_Angeles")
CST_TZ = ZoneInfo("Asia/Shanghai")

def parse_candidates_pool() -> List[Dict[str, Any]]:
    """解析候选池并计算全量项目的热度得分"""
    if not os.path.exists(CANDIDATES_MD):
        return []
    with open(CANDIDATES_MD, "r", encoding="utf-8") as f:
        text = f.read()

    blocks = re.split(r'\n(?=#{2,3} \d+\. \[)', text)
    projects = []
    seen = set()

    for b in blocks:
        m_head = re.search(r'#{2,3} \d+\. \[(.+?)\]\((https://github\.com/.+?)\)', b)
        if not m_head:
            continue
        full_name = m_head.group(1).strip()
        if full_name in seen:
            continue
        seen.add(full_name)
        url = m_head.group(2).strip()

        # 分类 & 语言
        tag = "🚀 优质开源精选"
        m_tag = re.search(r'\*\*分类领域\*\*:\s*`([^`]+)`', b)
        if m_tag:
            tag = m_tag.group(1)

        lang = "Unknown"
        m_lang = re.search(r'\*\*(?:主要)?语言\*\*:\s*`([^`]+)`', b)
        if m_lang:
            lang = m_lang.group(1)

        # Stars & Stars Today
        stars = 1000
        m_stars = re.search(r'⭐\s*\*\*([\d,]+)\*\*', b)
        if m_stars:
            try:
                stars = int(m_stars.group(1).replace(",", ""))
            except Exception:
                pass

        m_today = re.search(r'\(([\d,]+)\s*stars?\s*today\)', b, re.IGNORECASE)
        stars_today_num = int(m_today.group(1).replace(",", "")) if m_today else 0
        stars_today_str = f"{stars_today_num} stars today" if stars_today_num else f"{stars:,} stars"

        # 官方介绍
        desc = ""
        m_desc = re.search(r'\*\*官方介绍\*\*:\s*(.+)', b)
        if m_desc:
            desc = m_desc.group(1).strip()

        # 热度综合评分：单日爆发 Star 权重 100,000 + 累计总星数
        heat_score = (stars_today_num * 100000) + stars

        projects.append({
            "full_name": full_name,
            "url": url,
            "tag": tag,
            "language": lang,
            "stars": stars,
            "stars_today": stars_today_str,
            "stars_today_num": stars_today_num,
            "description": desc,
            "heat_score": heat_score
        })

    # 严格按照热度降序排序（最爆的项目在最前面）
    projects.sort(key=lambda x: x["heat_score"], reverse=True)
    return projects

def generate_24h_jitter_slots(now_dt: datetime, tz: ZoneInfo, slots_count: int = 5) -> List[datetime]:
    """
    生成未来 24 小时内的随机排期时刻：
    - 按 4 小时为一个发布区块 (240分钟)
    - 每个区块生成 1～240 的随机分钟数确定精确发帖时间
    - 确保时间严格单调递增并位于未来 24 小时之内
    """
    slots = []
    # 基础起始时间对齐到当前小时整点
    base_time = now_dt.replace(minute=0, second=0, microsecond=0)
    
    # 使用当日日期作为种子基数以防重复抖动过频，同时保留随机性
    rng = random.Random(int(now_dt.timestamp() // 3600))
    
    for i in range(slots_count):
        block_start = base_time + timedelta(hours=i * 4)
        jitter = rng.randint(15, 230)  # 在 4 小时 (240分钟) 内随机浮动，留出缓冲
        slot_dt = block_start + timedelta(minutes=jitter)
        
        # 确保排期时间在当前时刻之后至少 5 分钟
        if slot_dt <= now_dt + timedelta(minutes=5):
            slot_dt = now_dt + timedelta(minutes=rng.randint(15, 45))
            
        slots.append(slot_dt)
        
    slots.sort()
    return slots

def build_dynamic_schedule():
    all_projects = parse_candidates_pool()
    print(f"📦 解析候选池项目总数: {len(all_projects)}")

    now_utc = datetime.now(ZoneInfo("UTC"))
    now_pt = datetime.now(PT_TZ)
    now_cst = datetime.now(CST_TZ)

    # 读取旧队列以保留已发布的推文状态
    old_data = {}
    if os.path.exists(QUEUE_FILE):
        try:
            with open(QUEUE_FILE, "r", encoding="utf-8") as f:
                old_data = json.load(f)
        except Exception:
            pass

    # 找出两个账号已发布的项目，已发布的项目不再重复参与未来排期
    posted_alpha = set()
    for item in old_data.get("alpha_john", {}).get("queue", []):
        if item.get("status") == "posted":
            posted_alpha.add(item["repo"])

    posted_wangkun = set()
    for item in old_data.get("wangkun_pas", {}).get("queue", []):
        if item.get("status") == "posted":
            posted_wangkun.add(item["repo"])

    # 过滤出未发布的候选池（按热度倒序排列）
    available_alpha = [p for p in all_projects if p["full_name"] not in posted_alpha]
    available_wangkun = [p for p in all_projects if p["full_name"] not in posted_wangkun]

    # 未来 24 小时窗口按 4 小时一段，规划 5 个随机时刻
    # 时刻对齐本机计划任务（每 4 小时一轮，见 slots.py）；热度最高的排最前
    pt_slots = next_post_slots(now_utc, PT_TZ, min(5, len(available_alpha)))
    cst_slots = next_post_slots(now_utc, CST_TZ, min(5, len(available_wangkun)))

    from collector import generate_ai_drafts_gemini, generate_fallback_drafts, fetch_readme_snippet

    # 已经用 Gemini 写好新格式文案的待发项目，直接复用，不重复调用
    reuse = {}
    for acc_key in ("alpha_john", "wangkun_pas"):
        for item in old_data.get(acc_key, {}).get("queue", []):
            if item.get("status") == "pending" and item.get("copy_source") == "gemini_v2":
                reuse[(acc_key, item["repo"])] = item

    drafts_cache = {}

    def get_drafts(repo_data):
        """每个项目只调一次 Gemini（两个号的文案一次生成），带 README 上下文。失败返回 None。"""
        name = repo_data["full_name"]
        if name not in drafts_cache:
            readme = ""
            try:
                readme = fetch_readme_snippet(name)
            except Exception as e:
                print(f"   [Warn] 读取 {name} README 失败: {e}")
            drafts_cache[name] = generate_ai_drafts_gemini(repo_data, readme)
        return drafts_cache[name]

    def base_item(repo_data, slot, account):
        return {
            "repo": repo_data["full_name"],
            "url": repo_data["url"],
            "stars": repo_data["stars"],
            "stars_today": repo_data["stars_today"],
            "heat_score": repo_data["heat_score"],
            "scheduled_time": slot.strftime("%Y-%m-%d %H:%M:%S %Z"),
            "iso_time": slot.isoformat(),
            "status": "pending",
            "account": account,
        }

    def build_queue(acc_key, account, available, slots):
        queue = [it for it in old_data.get(acc_key, {}).get("queue", []) if it.get("status") == "posted"]
        print(f"\n🔥 正在为 [{account}] 分配热度最高项目与发帖时刻:")
        candidates = iter(available)
        for n, slot in enumerate(slots):
            item = None
            # Gemini 失败的项目跳过，换下一个热度项目；全都失败才用模板兜底
            for repo_data in candidates:
                old = reuse.get((acc_key, repo_data["full_name"]))
                if old:
                    item = dict(old, **base_item(repo_data, slot, account))
                    break
                drafts = get_drafts(repo_data)
                if not drafts:
                    print(f"   ⚠️ {repo_data['full_name']} 文案生成失败，跳过")
                    continue
                item = base_item(repo_data, slot, account)
                item["copy_source"] = "gemini_v2"
                if acc_key == "alpha_john":
                    # Alpha John 有 Premium，直接发长文
                    item["content"] = drafts["alpha_full"].strip()
                else:
                    # 王坤PAS 没有 Premium，发串推；content 留完整长文便于查看
                    item["thread"] = drafts["wangkun_thread"]
                    item["content"] = drafts["wangkun_full"].strip()
                break
            if item is None:
                if not available:
                    break
                repo_data = available[min(n, len(available) - 1)]
                fb = generate_fallback_drafts(repo_data, repo_data["tag"])
                item = base_item(repo_data, slot, account)
                item["copy_source"] = "template"
                item["content"] = fb["alpha_full" if acc_key == "alpha_john" else "wangkun_intent"].strip()
                print(f"   ⚠️ 没有可用的 AI 文案，{repo_data['full_name']} 用模板兜底")
            queue.append(item)
            print(f"   [Slot {n+1}] {slot.strftime('%Y-%m-%d %H:%M %Z')} ➔ {item['repo']} (热度 {item['heat_score']:,})")
        return queue

    alpha_queue = build_queue("alpha_john", "Alpha John", available_alpha, pt_slots)
    wangkun_queue = build_queue("wangkun_pas", "王坤PAS", available_wangkun, cst_slots)

    # 后续未入选未来 24 小时的低热度项目，保留在待排期池中
    backlog_alpha = available_alpha[len(pt_slots):]
    backlog_wangkun = available_wangkun[len(cst_slots):]

    final_data = {
        "rule_config": {
            "window": "Rolling 24 Hours",
            "ranking_strategy": "Heat Score (stars_today velocity primary, total_stars secondary)",
            "interval": "4-hour blocks with 1-240 minutes randomized jitter",
            "preemption": "Enabled (hotter repos preempt earlier slots; lower repos pushed back)"
        },
        "alpha_john": {
            "timezone": "America/Los_Angeles (PT)",
            "next_24h_count": len(pt_slots),
            "backlog_count": len(backlog_alpha),
            "queue": alpha_queue
        },
        "wangkun_pas": {
            "timezone": "Asia/Shanghai (CST)",
            "next_24h_count": len(cst_slots),
            "backlog_count": len(backlog_wangkun),
            "queue": wangkun_queue
        }
    }

    with open(QUEUE_FILE, "w", encoding="utf-8") as f:
        json.dump(final_data, f, indent=2, ensure_ascii=False)

    print(f"\n✅ 动态 24 小时热度排期队列已成功生成并保存至: {QUEUE_FILE}")

if __name__ == "__main__":
    build_dynamic_schedule()
