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
    pt_slots = generate_24h_jitter_slots(now_pt, PT_TZ, min(5, len(available_alpha)))
    cst_slots = generate_24h_jitter_slots(now_cst, CST_TZ, min(5, len(available_wangkun)))

    from collector import generate_ai_drafts_gemini, generate_fallback_drafts

    # 构建 Alpha John 队列
    alpha_queue = []
    # 先放入历史已发布的推文记录（保留历史审计）
    for item in old_data.get("alpha_john", {}).get("queue", []):
        if item.get("status") == "posted":
            alpha_queue.append(item)

    print("\n🔥 正在为 [Alpha John · 英文] 分配未来 24 小时热度最高项目与随机时刻:")
    for i, slot in enumerate(pt_slots):
        repo_data = available_alpha[i]
        
        # 尝试调用 Gemini API 生成神级文案，否则降级模版
        drafts = generate_ai_drafts_gemini(repo_data, "")
        if not drafts or not drafts.get("alpha_intent"):
            drafts = generate_fallback_drafts(repo_data, repo_data["tag"])
            
        content = drafts["alpha_intent"].strip()
        if len(content) > 270:
            content = content[:265] + "..."

        alpha_queue.append({
            "repo": repo_data["full_name"],
            "url": repo_data["url"],
            "stars": repo_data["stars"],
            "stars_today": repo_data["stars_today"],
            "heat_score": repo_data["heat_score"],
            "scheduled_time": slot.strftime("%Y-%m-%d %H:%M:%S %Z"),
            "iso_time": slot.isoformat(),
            "status": "pending",
            "account": "Alpha John",
            "content": content
        })
        print(f"   [Slot {i+1}] {slot.strftime('%Y-%m-%d %H:%M %Z')} ➔ {repo_data['full_name']} (今日+{repo_data['stars_today_num']}⭐, 总星{repo_data['stars']:,})")

    # 构建 王坤PAS 队列
    wangkun_queue = []
    for item in old_data.get("wangkun_pas", {}).get("queue", []):
        if item.get("status") == "posted":
            wangkun_queue.append(item)

    print("\n🔥 正在为 [王坤PAS · 中文] 分配未来 24 小时热度最高项目与随机时刻:")
    for i, slot in enumerate(cst_slots):
        repo_data = available_wangkun[i]
        
        drafts = generate_ai_drafts_gemini(repo_data, "")
        if not drafts or not drafts.get("wangkun_intent"):
            drafts = generate_fallback_drafts(repo_data, repo_data["tag"])
            
        content = drafts["wangkun_intent"].strip()
        if len(content) > 270:
            content = content[:265] + "..."

        wangkun_queue.append({
            "repo": repo_data["full_name"],
            "url": repo_data["url"],
            "stars": repo_data["stars"],
            "stars_today": repo_data["stars_today"],
            "heat_score": repo_data["heat_score"],
            "scheduled_time": slot.strftime("%Y-%m-%d %H:%M:%S %Z"),
            "iso_time": slot.isoformat(),
            "status": "pending",
            "account": "王坤PAS",
            "content": content
        })
        print(f"   [Slot {i+1}] {slot.strftime('%Y-%m-%d %H:%M %Z')} ➔ {repo_data['full_name']} (今日+{repo_data['stars_today_num']}⭐, 总星{repo_data['stars']:,})")

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
