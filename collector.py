#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
GitHub Trending & Fast-Spiking Projects Collector (Dual-Account AI Edition)
每天自动侦测 GitHub 上热度急剧上升的开源项目，结合大模型多维度情绪与吸睛策略，
自动为两个不同账号生成定制化爆款推文：
  - [Alpha John]：英文专版，侧重海外全球极客、出海创业、效率杠杆与开发者生态
  - [王坤PAS]：中文专版，侧重认知反差、搞钱杠杆、一人公司与技术破局
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

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

API_HEADERS = {
    "Accept": "application/vnd.github.v3+json",
    "User-Agent": "TrendingRadarCollector/2.0",
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

            p_desc = art.find("p")
            description = p_desc.text.strip() if p_desc else ""

            lang_span = art.select_one("span[itemprop='programmingLanguage']")
            language = lang_span.text.strip() if lang_span else "Unknown"

            stars_a = art.select_one(f"a[href='/{full_name}/stargazers']")
            stars_text = stars_a.text.strip().replace(",", "") if stars_a else "0"
            try:
                total_stars = int(stars_text)
            except ValueError:
                total_stars = 0

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
            print(f"[Warn] Search API returned status {resp.status_code}")
    except Exception as e:
        print(f"[Error] Failed to query Search API: {e}")
    return repos

def fetch_readme_snippet(full_name: str) -> str:
    branches = ["main", "master"]
    filenames = ["README.md", "readme.md"]
    for b in branches:
        for fn in filenames:
            raw_url = f"https://raw.githubusercontent.com/{full_name}/{b}/{fn}"
            try:
                r = requests.get(raw_url, timeout=5)
                if r.status_code == 200:
                    return r.text[:2000]
            except Exception:
                pass
    return ""

def classify_repo(repo: Dict[str, Any]) -> str:
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
    text = (repo["full_name"] + " " + repo["description"]).lower()
    for kw in SPAM_KEYWORDS:
        if kw in text:
            return True
    if len(repo["description"].strip()) < 5:
        return True
    return False

def generate_ai_drafts_gemini(repo: Dict[str, Any], readme_snippet: str) -> Optional[Dict[str, str]]:
    """使用 Gemini API 生成高情绪、强反差的中英文双版本推文"""
    if not GEMINI_API_KEY:
        return None

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
    
    prompt = f"""You are a world-class viral tech copywriter for X (Twitter).
Analyze this trending GitHub repository:
- Project: {repo['full_name']}
- Stars: {repo['stars']} ({repo['stars_today']})
- URL: {repo['url']}
- Description: {repo['description']}
- README Excerpt:
{readme_snippet[:1500]}

Generate TWO completely different, highly emotional and compelling viral X post drafts:

1. [Alpha John Version] - For English Tech Twitter:
- Target account: Alpha John (English only)
- Tone: High-energy, Silicon Valley builder / solopreneur / extreme leverage / tech insider vibe.
- Angle options (choose the best fitting one): Massive efficiency gain, solo-founder software factory, killing AI slop, developer leverage, investor alpha.
- Provide:
  - "alpha_intent": Under 260 characters single-tweet version with emojis, punchy hook, bullet points, and link.
  - "alpha_full": 500-800 characters full-length viral tweet with emotional hook, before vs after, feature checklist, and hashtags.

2. [王坤PAS Version] - For Chinese Tech Twitter:
- Target account: 王坤PAS (中文)
- Tone: 强烈情绪共鸣, 击碎认知差, 痛点对比(普通人的傻做法 vs 顶级的十倍杠杆), 充满搞钱/一人公司/技术破局感.
- Provide:
  - "wangkun_intent": 260字符以内极简单推版（带吸引人眼球的开头、排比打勾和链接）.
  - "wangkun_full": 500-800字符完整长文爆款版（黄金第一句、痛点共鸣、排比清单、打消门槛说明、热门话题标签）.

Return strictly valid JSON:
{{
  "alpha_intent": "...",
  "alpha_full": "...",
  "wangkun_intent": "...",
  "wangkun_full": "..."
}}
"""

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.85, "maxOutputTokens": 1500}
    }

    try:
        resp = requests.post(url, json=payload, timeout=20)
        if resp.status_code == 200:
            data = resp.json()
            raw_text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
            # 提取 JSON 代码块
            if "```json" in raw_text:
                raw_text = raw_text.split("```json")[1].split("```")[0].strip()
            elif "```" in raw_text:
                raw_text = raw_text.split("```")[1].split("```")[0].strip()
            return json.loads(raw_text)
    except Exception as e:
        print(f"[Warn] Gemini generation failed: {e}")
    return None

def generate_fallback_drafts(repo: Dict[str, Any], tag: str) -> Dict[str, str]:
    """当未配置 API Key 时的动态高情绪模版引擎"""
    name = repo["full_name"]
    url = repo["url"]
    stars = repo["stars"]
    desc = repo["description"]
    today_stars = repo["stars_today"]

    # Alpha John 英文版
    alpha_intent = (
        f"Game-changer on GitHub: {name} is blowing up (⭐ {stars:,}, {today_stars})!\n\n"
        f"💡 {desc[:90]}...\n"
        f"✅ 10x leverage for builders & solo founders\n"
        f"✅ Production-grade & 100% open-source\n\n"
        f"🔗 Check it out: {url}\n"
        f"#OpenSource #BuildInPublic #AI"
    )

    alpha_full = (
        f"Why is everyone talking about {name} right now? (⭐ {stars:,}, {today_stars})\n\n"
        f"If you're still doing this manually, you're giving away an unfair advantage:\n\n"
        f"💡 What it does: {desc}\n\n"
        f"Here's why it's breaking GitHub:\n"
        f"✅ Massive engineering leverage\n"
        f"✅ Designed for autonomous agent workflows\n"
        f"✅ Zero vendor lock-in, 100% open-source\n\n"
        f"Solo builders and founders: bookmark this before everyone else catches up.\n\n"
        f"GitHub: {url}\n"
        f"#buildinpublic #AI #TechTrends #OpenSource"
    )

    # 王坤PAS 中文版
    wangkun_intent = (
        f"认知被狠狠刷新了！GitHub 爆火新星：{name}（⭐ {stars:,}，{today_stars}）\n\n"
        f"💡 {desc[:85]}...\n"
        f"✅ 一人超级公司 10 倍效率杠杆\n"
        f"✅ 击碎传统低效做法，纯开源免费\n\n"
        f"🔗 传送门: {url}\n"
        f"#开源 #AI #搞钱 #独立开发"
    )

    wangkun_full = (
        f"认知被狠狠刷新了。\n\n"
        f"当你还在用老方法死磕时，GitHub 上单日暴涨的开源神器彻底降维打击了：{name}（当前已破 {stars:,} ⭐）！\n\n"
        f"💡 核心定位：{desc}\n\n"
        f"它击中了最痛的几个点：\n"
        f"✅ 真正的 10 倍人效杠杆，把传统几天的工作缩短到分钟级\n"
        f"✅ 告别千篇一律的玩具脚本，直出生产可用成果\n"
        f"✅ 100% 纯开源免费，无需复杂付费门槛\n\n"
        f"想在 AI 时代跑通一人公司、拉满个人产能的，强烈建议连夜研究一下。\n\n"
        f"GitHub: {url}\n"
        f"#开源 #AI #一人公司 #独立开发 #搞钱 #技术破局"
    )

    return {
        "alpha_intent": alpha_intent,
        "alpha_full": alpha_full,
        "wangkun_intent": wangkun_intent,
        "wangkun_full": wangkun_full,
    }

def main():
    print(f"[{datetime.datetime.now()}] 启动 GitHub Trending 雷达双账号定制版...")
    state = load_state()
    seen = state.get("seen", {})

    candidates = []
    trending_sources = [
        ("https://github.com/trending?since=daily", "All"),
        ("https://github.com/trending/python?since=daily", "Python"),
        ("https://github.com/trending/typescript?since=daily", "TypeScript"),
    ]
    for url, cat in trending_sources:
        cands = fetch_trending_page(url, cat)
        candidates.extend(cands)

    new_spikes = fetch_new_spikes_from_search()
    candidates.extend(new_spikes)

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
        print("今日无新增候选项目。")
        return

    new_items.sort(key=lambda x: x["stars"], reverse=True)
    selected_items = new_items[:15]

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

    os.makedirs(CANDIDATES_DIR, exist_ok=True)
    daily_file = os.path.join(CANDIDATES_DIR, f"{today_str}.md")

    daily_lines = [
        f"# 📡 GitHub Trending 双账号定制精选 ({today_str})",
        "",
        f"> 自动收录于 {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}。今日精选 {len(selected_items)} 个爆发新星项目。",
        "",
        "---",
        "",
    ]

    for idx, repo in enumerate(selected_items, 1):
        tag = classify_repo(repo)
        readme = fetch_readme_snippet(repo["full_name"])

        # 生成定制化文案（优先调用 Gemini，若无 Key 则用高情绪模板）
        drafts = generate_ai_drafts_gemini(repo, readme)
        if not drafts:
            drafts = generate_fallback_drafts(repo, tag)

        alpha_intent_url = "https://twitter.com/intent/tweet?text=" + urllib.parse.quote(drafts["alpha_intent"])
        wangkun_intent_url = "https://twitter.com/intent/tweet?text=" + urllib.parse.quote(drafts["wangkun_intent"])

        daily_lines.append(f"## {idx}. [{repo['full_name']}]({repo['url']})")
        daily_lines.append(f"- **分类领域**: `{tag}` | **语言**: `{repo['language']}` | ⭐ **{repo['stars']:,}** ({repo['stars_today']})")
        daily_lines.append(f"- **官方介绍**: {repo['description']}")
        daily_lines.append("")
        
        # Alpha John 专区
        daily_lines.append("### 🇬🇧 [Alpha John 专版 · English]")
        daily_lines.append("```text")
        daily_lines.append(drafts["alpha_full"].strip())
        daily_lines.append("```")
        daily_lines.append(f"👉 **[点击直接在 X 打开并排期 (Alpha John)]({alpha_intent_url})**")
        daily_lines.append("")

        # 王坤PAS 专区
        daily_lines.append("### 🇨🇳 [王坤PAS 专版 · 中文]")
        daily_lines.append("```text")
        daily_lines.append(drafts["wangkun_full"].strip())
        daily_lines.append("```")
        daily_lines.append(f"👉 **[点击直接在 X 打开并排期 (王坤PAS)]({wangkun_intent_url})**")
        daily_lines.append("")
        daily_lines.append("---")
        daily_lines.append("")

    with open(daily_file, "w", encoding="utf-8") as f:
        f.write("\n".join(daily_lines))
    print(f"已写入每日归档: {daily_file}")

    md_header = (
        "# 📡 GitHub Trending 候选项目库 (Candidate Pool)\n\n"
        "每天由 GitHub Actions 自动更新。专为两个 X 账号提供定制化爆款推文：\n"
        "- 🇬🇧 **Alpha John**：英文专版（全球极客 / 一人公司 / 独立开发）\n"
        "- 🇨🇳 **王坤PAS**：中文专版（认知反差 / 搞钱杠杆 / 技术破局）\n\n"
        "---\n\n"
    )

    existing_content = ""
    if os.path.exists(CANDIDATES_MD):
        with open(CANDIDATES_MD, "r", encoding="utf-8") as f:
            existing_content = f.read()
            if "---" in existing_content:
                existing_content = existing_content.split("---", 1)[1].strip()

    new_section = "\n".join(daily_lines[4:])
    full_candidates_content = md_header + new_section + "\n\n---\n\n" + existing_content
    with open(CANDIDATES_MD, "w", encoding="utf-8") as f:
        f.write(full_candidates_content)
    print(f"已更新候选池文件: {CANDIDATES_MD}")

if __name__ == "__main__":
    main()
