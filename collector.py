#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
GitHub Trending & Fast-Spiking Projects Collector
每天自动侦测 GitHub 上热度急剧上升的开源项目，过滤、分类并归档为候选池。
"""

import os
import re
import json
import datetime
import urllib.parse
from typing import List, Dict, Any, Optional

import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# 若环境中存在 GITHUB_TOKEN（如 GitHub Actions 自动提供），带上以获得更高 API 限流额度
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
API_HEADERS = {
    "Accept": "application/vnd.github.v3+json",
    "User-Agent": "TrendingRadarCollector/1.0",
}
if GITHUB_TOKEN:
    API_HEADERS["Authorization"] = f"Bearer {GITHUB_TOKEN}"

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(ROOT_DIR, "state.json")
CANDIDATES_DIR = os.path.join(ROOT_DIR, "candidates")
CANDIDATES_MD = os.path.join(ROOT_DIR, "candidates.md")

SPAM_KEYWORDS = [
    "hack", "cheat", "free-download", "crack", "bypass", "steam-wallet", "bot-farm", "spoof"
]

def load_state() -> Dict[str, Any]:
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[Warning] Failed to load {STATE_FILE}: {e}")
    return {"seen": {}, "posted": {}, "last_run": None}

def save_state(state: Dict[str, Any]):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)

def fetch_trending_page(url: str, category_name: str) -> List[Dict[str, Any]]:
    """爬取 GitHub Trending 页面"""
    repos = []
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            print(f"[Warn] Fetch {url} returned status {resp.status_code}")
            return repos
        soup = BeautifulSoup(resp.text, "html.parser")
        articles = soup.select("article.Box-row")
        for art in articles:
            h2 = art.find("h2")
            if not h2:
                continue
            a_tag = h2.find("a")
            if not a_tag or not a_tag.get("href"):
                continue
            repo_path = a_tag["href"].strip().strip("/")
            parts = repo_path.split("/")
            if len(parts) != 2:
                continue
            full_name = f"{parts[0]}/{parts[1]}"

            # 简介
            p_desc = art.find("p")
            description = p_desc.text.strip() if p_desc else ""

            # 语言
            lang_span = art.select_one("span[itemprop='programmingLanguage']")
            language = lang_span.text.strip() if lang_span else "Unknown"

            # 总 Star
            stars_a = art.select_one(f"a[href='/{full_name}/stargazers']")
            stars_text = stars_a.text.strip().replace(",", "") if stars_a else "0"
            try:
                total_stars = int(stars_text)
            except ValueError:
                total_stars = 0

            # 今日增长
            stars_today_span = art.select_one("span.d-inline-block.float-sm-right")
            stars_today_text = stars_today_span.text.strip() if stars_today_span else ""

            repos.append({
                "full_name": full_name,
                "url": f"https://github.com/{full_name}",
                "description": description,
                "language": language,
                "stars": total_stars,
                "stars_today": stars_today_text,
                "source": f"Trending ({category_name})",
                "topics": [],
            })
    except Exception as e:
        print(f"[Error] Failed to fetch trending {url}: {e}")
    return repos

def fetch_new_spikes_from_search() -> List[Dict[str, Any]]:
    """通过 GitHub Search API 查找最近 7 天新建且 Star > 50 的爆发性新星项目"""
    repos = []
    today = datetime.date.today()
    seven_days_ago = (today - datetime.timedelta(days=7)).isoformat()
    api_url = f"https://api.github.com/search/repositories?q=created:>{seven_days_ago}+stars:>50&sort=stars&order=desc&per_page=30"

    try:
        resp = requests.get(api_url, headers=API_HEADERS, timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            for item in data.get("items", []):
                full_name = item.get("full_name")
                if not full_name:
                    continue
                repos.append({
                    "full_name": full_name,
                    "url": item.get("html_url", f"https://github.com/{full_name}"),
                    "description": item.get("description") or "",
                    "language": item.get("language") or "Unknown",
                    "stars": item.get("stargazers_count", 0),
                    "stars_today": f"~{item.get('stargazers_count', 0)} (7天内新建)",
                    "source": "Search API (New Spikes)",
                    "topics": item.get("topics", []),
                })
        else:
            print(f"[Warn] Search API returned status {resp.status_code}: {resp.text[:100]}")
    except Exception as e:
        print(f"[Error] Failed to query Search API: {e}")
    return repos

def classify_repo(repo: Dict[str, Any]) -> str:
    """根据描述与主题给项目打上分类标签"""
    text = (repo["full_name"] + " " + repo["description"] + " " + " ".join(repo.get("topics", []))).lower()
    if any(k in text for k in ["agent", "skill", "mcp", "workflow", "autonomous", "claude", "gpt", "rag"]):
        return "🤖 AI & Agent Skills"
    if any(k in text for k in ["video", "audio", "voice", "tts", "diffusion", "motion", "remotion", "whisper", "speech"]):
        return "🎬 AI 视频 / 视觉与多媒体"
    if any(k in text for k in ["llm", "deep learning", "transformer", "model", "benchmark", "inference"]):
        return "🧠 大模型与算法前沿"
    if any(k in text for k in ["cli", "terminal", "debugger", "docker", "devtools", "extension", "rust", "framework"]):
        return "🛠️ 开发者工具 & 架构"
    return "🚀 优质开源精选"

def is_spam(repo: Dict[str, Any]) -> bool:
    """过滤垃圾项目"""
    text = (repo["full_name"] + " " + repo["description"]).lower()
    for kw in SPAM_KEYWORDS:
        if kw in text:
            return True
    if len(repo["description"].strip()) < 5:
        return True
    return False

def build_tweet_url(repo: Dict[str, Any], tag: str) -> str:
    """生成点击即可直接在 X 预填文案的发推链接"""
    name = repo["full_name"]
    url = repo["url"]
    desc = repo["description"]
    # 截取合适长度的描述
    if len(desc) > 90:
        desc = desc[:87] + "..."

    tweet_text = (
        f"🔥 GitHub 热点发现：{name}\n\n"
        f"💡 {desc}\n"
        f"⭐ Stars: {repo['stars']} ({repo['stars_today']})\n"
        f"🏷️ 分类: {tag}\n\n"
        f"🔗 传送门: {url}\n"
        f"#GitHubTrending #OpenSource #AI"
    )
    return "https://twitter.com/intent/tweet?text=" + urllib.parse.quote(tweet_text)

def main():
    print(f"[{datetime.datetime.now()}] 开始检索 GitHub 热度飙升开源项目...")
    state = load_state()
    seen = state.get("seen", {})

    candidates = []

    # 1. 抓取 GitHub Trending 榜单
    trending_sources = [
        ("https://github.com/trending?since=daily", "All"),
        ("https://github.com/trending/python?since=daily", "Python"),
        ("https://github.com/trending/typescript?since=daily", "TypeScript"),
    ]
    for url, cat in trending_sources:
        print(f"Fetching Trending: {cat}...")
        cands = fetch_trending_page(url, cat)
        candidates.extend(cands)

    # 2. 抓取近期新建且热度剧增的新项目
    print("Fetching newly created spiking repos...")
    new_spikes = fetch_new_spikes_from_search()
    candidates.extend(new_spikes)

    # 3. 去重与过滤
    today_str = datetime.date.today().isoformat()
    unique_candidates: Dict[str, Dict[str, Any]] = {}

    for c in candidates:
        name = c["full_name"]
        if name in seen:
            continue
        if is_spam(c):
            continue
        if name not in unique_candidates:
            unique_candidates[name] = c

    new_items = list(unique_candidates.values())
    print(f"发现新候选项目数: {len(new_items)}")

    if not new_items:
        print("今日无新增候选项目（或均已入库）。")
        return

    # 按 star 数和增速综合排序，取前 15 个最亮眼的
    new_items.sort(key=lambda x: x["stars"], reverse=True)
    selected_items = new_items[:15]

    # 4. 记录到 state
    for item in selected_items:
        seen[item["full_name"]] = {
            "date": today_str,
            "stars": item["stars"],
            "url": item["url"],
            "source": item["source"],
            "posted": False
        }
    state["seen"] = seen
    state["last_run"] = datetime.datetime.now().isoformat()
    save_state(state)

    # 5. 生成今日归档文件 candidates/YYYY-MM-DD.md
    os.makedirs(CANDIDATES_DIR, exist_ok=True)
    daily_file = os.path.join(CANDIDATES_DIR, f"{today_str}.md")

    daily_lines = [
        f"# GitHub 热度急剧上升开源项目精选 ({today_str})",
        "",
        f"> 自动收录于 {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}。今日精选 {len(selected_items)} 个爆发新星项目。",
        "",
    ]

    for idx, repo in enumerate(selected_items, 1):
        tag = classify_repo(repo)
        tweet_link = build_tweet_url(repo, tag)
        daily_lines.append(f"### {idx}. [{repo['full_name']}]({repo['url']})")
        daily_lines.append(f"- **分类领域**: `{tag}` | **主要语言**: `{repo['language']}`")
        daily_lines.append(f"- **热度表现**: ⭐ **{repo['stars']}** ({repo['stars_today']}) | 来源: `{repo['source']}`")
        daily_lines.append(f"- **官方介绍**: {repo['description']}")
        if repo.get("topics"):
            daily_lines.append(f"- **标签**: " + ", ".join([f"`{t}`" for t in repo["topics"][:6]]))
        daily_lines.append(f"- **快速发推**: [👉 点击直接在 X 打开并预填发推内容]({tweet_link})")
        daily_lines.append("")

    with open(daily_file, "w", encoding="utf-8") as f:
        f.write("\n".join(daily_lines))
    print(f"已写入每日归档: {daily_file}")

    # 6. 更新或追加到 candidates.md（保持最新未发布的在前面）
    md_header = (
        "# 📡 GitHub Trending 候选项目库 (Candidate Pool)\n\n"
        "每天由 GitHub Actions 自动更新。当你准备发 X 帖子时，只需告诉 AI：“看看候选库，挑出最好的项目写成发推文案”。\n\n"
        "---\n\n"
    )

    existing_content = ""
    if os.path.exists(CANDIDATES_MD):
        with open(CANDIDATES_MD, "r", encoding="utf-8") as f:
            existing_content = f.read()
            # 移除旧 header
            if "---" in existing_content:
                existing_content = existing_content.split("---", 1)[1].strip()

    new_section = "\n".join(daily_lines)
    full_candidates_content = md_header + new_section + "\n\n---\n\n" + existing_content
    with open(CANDIDATES_MD, "w", encoding="utf-8") as f:
        f.write(full_candidates_content)
    print(f"已更新候选池文件: {CANDIDATES_MD}")

if __name__ == "__main__":
    main()
