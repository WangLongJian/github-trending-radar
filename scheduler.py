#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
X (Twitter) Dual-Account Schedule Queue Manager
管理 Alpha John (PT 太平洋时间) 与 王坤PAS (CST 北京时间) 的发推时间队列：
- 每天发推时间段: 09:00 - 24:00
- 每隔 3 小时一条: 09:00, 12:00, 15:00, 18:00, 21:00 (每天最多 5 条)
- 自动生成专属情绪爆款文案并记录排期状态
"""

import os
import sys
import json
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import List, Dict, Any

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(ROOT_DIR, "state.json")
CANDIDATES_MD = os.path.join(ROOT_DIR, "candidates.md")
QUEUE_FILE = os.path.join(ROOT_DIR, "schedule_queue.json")

DAILY_SLOTS = [9, 12, 15, 18, 21]

PT_TZ = ZoneInfo("America/Los_Angeles")
CST_TZ = ZoneInfo("Asia/Shanghai")

def get_next_slots(start_dt: datetime, count: int, tz: ZoneInfo) -> List[datetime]:
    slots = []
    current_date = start_dt.date()
    while len(slots) < count:
        for hour in DAILY_SLOTS:
            slot_dt = datetime(current_date.year, current_date.month, current_date.day, hour, 0, 0, tzinfo=tz)
            if slot_dt > start_dt:
                slots.append(slot_dt)
                if len(slots) >= count:
                    break
        current_date += timedelta(days=1)
    return slots

def parse_all_candidates() -> List[Dict[str, Any]]:
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

        # Stars
        stars = 1000
        m_stars = re.search(r'⭐\s*\*\*([\d,]+)\*\*', b)
        if m_stars:
            try:
                stars = int(m_stars.group(1).replace(",", ""))
            except Exception:
                pass

        # 官方介绍
        desc = ""
        m_desc = re.search(r'\*\*官方介绍\*\*:\s*(.+)', b)
        if m_desc:
            desc = m_desc.group(1).strip()

        # 检查是否已有现成专版
        alpha_draft = None
        wangkun_draft = None

        m_alpha = re.search(r'### 🇬🇧 \[Alpha John 专版 · English\]\s*```text\s*(.*?)\s*```', b, re.DOTALL)
        if m_alpha:
            alpha_draft = m_alpha.group(1).strip()

        m_wangkun = re.search(r'### 🇨🇳 \[王坤PAS 专版 · 中文\]\s*```text\s*(.*?)\s*```', b, re.DOTALL)
        if m_wangkun:
            wangkun_draft = m_wangkun.group(1).strip()

        projects.append({
            "full_name": full_name,
            "url": url,
            "tag": tag,
            "language": lang,
            "stars": stars,
            "description": desc,
            "alpha_draft": alpha_draft,
            "wangkun_draft": wangkun_draft
        })

    return projects

def build_schedule_queues():
    projects = parse_all_candidates()
    print(f"📦 解析出有效独立项目总数: {len(projects)}")

    now_pt = datetime.now(PT_TZ)
    now_cst = datetime.now(CST_TZ)

    pt_slots = get_next_slots(now_pt, len(projects), PT_TZ)
    cst_slots = get_next_slots(now_cst, len(projects), CST_TZ)

    from collector import generate_fallback_drafts

    alpha_queue = []
    wangkun_queue = []

    for i, p in enumerate(projects):
        slot_pt = pt_slots[i]
        slot_cst = cst_slots[i]

        repo_dict = {
            "full_name": p["full_name"],
            "url": p["url"],
            "description": p["description"],
            "language": p["language"],
            "stars": p["stars"],
            "stars_today": f"{p['stars']:,} stars",
            "topics": []
        }

        # 如果已有专版文案直接使用，没有则生成专属高情绪文案
        if p["alpha_draft"]:
            alpha_text = p["alpha_draft"]
        else:
            drafts = generate_fallback_drafts(repo_dict, p["tag"])
            alpha_text = drafts["alpha_full"]

        if p["wangkun_draft"]:
            wangkun_text = p["wangkun_draft"]
        else:
            drafts = generate_fallback_drafts(repo_dict, p["tag"])
            wangkun_text = drafts["wangkun_full"]

        alpha_queue.append({
            "repo": p["full_name"],
            "url": p["url"],
            "scheduled_time": slot_pt.strftime("%Y-%m-%d %H:%M:%S %Z"),
            "iso_time": slot_pt.isoformat(),
            "status": "pending",
            "account": "Alpha John",
            "content": alpha_text,
            "media": None
        })

        wangkun_queue.append({
            "repo": p["full_name"],
            "url": p["url"],
            "scheduled_time": slot_cst.strftime("%Y-%m-%d %H:%M:%S %Z"),
            "iso_time": slot_cst.isoformat(),
            "status": "pending",
            "account": "王坤PAS",
            "content": wangkun_text,
            "media": None
        })

    queue_data = {
        "alpha_john": {
            "timezone": "America/Los_Angeles (PT)",
            "daily_slots": ["09:00", "12:00", "15:00", "18:00", "21:00"],
            "total_queued": len(alpha_queue),
            "start_time": alpha_queue[0]["scheduled_time"] if alpha_queue else None,
            "end_time": alpha_queue[-1]["scheduled_time"] if alpha_queue else None,
            "queue": alpha_queue
        },
        "wangkun_pas": {
            "timezone": "Asia/Shanghai (CST)",
            "daily_slots": ["09:00", "12:00", "15:00", "18:00", "21:00"],
            "total_queued": len(wangkun_queue),
            "start_time": wangkun_queue[0]["scheduled_time"] if wangkun_queue else None,
            "end_time": wangkun_queue[-1]["scheduled_time"] if wangkun_queue else None,
            "queue": wangkun_queue
        }
    }

    with open(QUEUE_FILE, "w", encoding="utf-8") as f:
        json.dump(queue_data, f, indent=2, ensure_ascii=False)

    print(f"✅ 成功生成全量排期队列！保存至: {QUEUE_FILE}")
    print(f"🇬🇧 Alpha John (PT): 共 {len(alpha_queue)} 条推文 | 排期范围: {queue_data['alpha_john']['start_time']} 至 {queue_data['alpha_john']['end_time']} (约持续 {len(alpha_queue)//5} 天)")
    print(f"🇨🇳 王坤PAS (CST): 共 {len(wangkun_queue)} 条推文 | 排期范围: {queue_data['wangkun_pas']['start_time']} 至 {queue_data['wangkun_pas']['end_time']} (约持续 {len(wangkun_queue)//5} 天)")

if __name__ == "__main__":
    build_schedule_queues()
