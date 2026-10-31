#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Post Helper CLI
本地交互管理与推文生成辅助工具。
用于查看候选库、精读生成深度 X 帖子草稿、生成一键发推链接以及标记发布状态。
"""

import os
import sys
import json
import urllib.parse
from typing import Dict, Any, List

import requests

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(ROOT_DIR, "state.json")
CANDIDATES_DIR = os.path.join(ROOT_DIR, "candidates")

def load_state() -> Dict[str, Any]:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"seen": {}, "posted": {}, "last_run": None}

def save_state(state: Dict[str, Any]):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)

def get_candidates_list() -> List[Dict[str, Any]]:
    state = load_state()
    seen = state.get("seen", {})
    items = []
    for full_name, data in seen.items():
        items.append({
            "full_name": full_name,
            "date": data.get("date", "Unknown"),
            "stars": data.get("stars", 0),
            "url": data.get("url", f"https://github.com/{full_name}"),
            "source": data.get("source", ""),
            "posted": data.get("posted", False),
        })
    # 按日期降序，Star降序
    items.sort(key=lambda x: (x["date"], x["stars"]), reverse=True)
    return items

def fetch_repo_readme(full_name: str) -> str:
    """尝试通过 GitHub Raw 获取 README 文本片段（前 2500 字符）"""
    branches = ["main", "master"]
    filenames = ["README.md", "readme.md", "README.rst"]
    for b in branches:
        for fn in filenames:
            raw_url = f"https://raw.githubusercontent.com/{full_name}/{b}/{fn}"
            try:
                r = requests.get(raw_url, timeout=5)
                if r.status_code == 200:
                    return r.text[:2500]
            except Exception:
                pass
    return "（未能直接获取到原始 README，请点击项目链接查看）"

def cmd_list(unposted_only: bool = True):
    items = get_candidates_list()
    print("==================================================================")
    print(f"📡 GitHub Trending 候选项目列表 ({'仅显示未发布' if unposted_only else '全部'}):")
    print("==================================================================")
    displayed = 0
    for idx, item in enumerate(items, 1):
        if unposted_only and item["posted"]:
            continue
        status_icon = "✅ 已发布" if item["posted"] else "⏳ 待发布"
        print(f"[{idx}] {item['full_name']} | ⭐ {item['stars']} | 📅 {item['date']} | {status_icon}")
        displayed += 1
    if displayed == 0:
        print("暂无未发布的候选项目。")
    print("==================================================================")
    print("提示：输入 `python3 post_helper.py draft <编号>` 查看详情与推文草稿")

def cmd_draft(target: str):
    items = get_candidates_list()
    matched = None
    if target.isdigit():
        idx = int(target) - 1
        if 0 <= idx < len(items):
            matched = items[idx]
    else:
        for it in items:
            if target.lower() in it["full_name"].lower():
                matched = it
                break

    if not matched:
        print(f"[Error] 未找到对应的候选项目: {target}")
        return

    name = matched["full_name"]
    url = matched["url"]
    stars = matched["stars"]
    date = matched["date"]

    print(f"\n🔍 正在获取 [{name}] 的详细背景信息...")
    readme_snippet = fetch_repo_readme(name)

    print("\n" + "=" * 60)
    print(f"📌 项目：{name} (⭐ {stars}) | 收录日期: {date}")
    print(f"🔗 仓库：{url}")
    print("=" * 60)

    # 生成推文草稿模版
    print("\n📝 【推荐发推文案草稿 · 极简版 (适合单推 280 字符)】:")
    short_tweet = (
        f"🔥 GitHub 热度飙升新星：{name}\n\n"
        f"⭐ 今日 Star 激增，当前已破 {stars:,}+\n"
        f"💡 项目定位与核心亮点：\n"
        f"• (在这里填入 1~2 句核心痛点提炼)\n\n"
        f"🔗 仓库传送门: {url}\n"
        f"#GitHubTrending #AI #OpenSource"
    )
    print(short_tweet)

    tweet_url = "https://twitter.com/intent/tweet?text=" + urllib.parse.quote(short_tweet)
    print(f"\n👉 点击直接在 X 浏览器中预填发布:\n{tweet_url}")

    print("\n" + "=" * 60)
    print("📄 【项目 README 核心摘要片段】:")
    print(readme_snippet[:600] + "...\n")
    print("=" * 60)
    print(f"发布完成后，可运行 `python3 post_helper.py mark {name}` 将其标记为已发布。")

def cmd_mark(target: str):
    state = load_state()
    seen = state.get("seen", {})
    matched_name = None

    items = get_candidates_list()
    if target.isdigit():
        idx = int(target) - 1
        if 0 <= idx < len(items):
            matched_name = items[idx]["full_name"]
    else:
        for name in seen:
            if target.lower() in name.lower():
                matched_name = name
                break

    if not matched_name or matched_name not in seen:
        print(f"[Error] 找不到项目: {target}")
        return

    seen[matched_name]["posted"] = True
    state["seen"] = seen
    save_state(state)
    print(f"✅ 成功将 [{matched_name}] 标记为已发布！")

def main():
    if len(sys.argv) < 2:
        print("用法:")
        print("  python3 post_helper.py list          # 列出所有待发布的候选项目")
        print("  python3 post_helper.py list --all    # 列出全部历史收录项目")
        print("  python3 post_helper.py draft <编号>  # 提取项目 README 并生成推文草稿与发推链接")
        print("  python3 post_helper.py mark <编号>   # 标记指定项目为已发布")
        return

    cmd = sys.argv[1].lower()
    if cmd == "list":
        show_all = len(sys.argv) > 2 and sys.argv[2] == "--all"
        cmd_list(unposted_only=not show_all)
    elif cmd in ["draft", "show"]:
        if len(sys.argv) < 3:
            print("请指定项目编号或名称，例如: python3 post_helper.py draft 1")
            return
        cmd_draft(sys.argv[2])
    elif cmd in ["mark", "mark-posted"]:
        if len(sys.argv) < 3:
            print("请指定项目编号或名称，例如: python3 post_helper.py mark 1")
            return
        cmd_mark(sys.argv[2])
    else:
        print(f"未知命令: {cmd}")

if __name__ == "__main__":
    main()
