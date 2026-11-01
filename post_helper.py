#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Post Helper CLI
本地交互管理、多媒体资源自动提取与推文生成辅助工具。
用于查看候选库、精读生成深度 X 帖子、提取/合成项目配图及一键在浏览器打开预填推文。
"""

import os
import sys
import json
import re
import subprocess
import urllib.parse
from typing import Dict, Any, List, Optional

import requests
from PIL import Image, ImageDraw, ImageFont

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(ROOT_DIR, "state.json")
CANDIDATES_DIR = os.path.join(ROOT_DIR, "candidates")
ASSETS_DIR = os.path.join(ROOT_DIR, "assets")

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
    items.sort(key=lambda x: (x["date"], x["stars"]), reverse=True)
    return items

def resolve_target(target: str) -> Optional[Dict[str, Any]]:
    items = get_candidates_list()
    if target.isdigit():
        idx = int(target) - 1
        if 0 <= idx < len(items):
            return items[idx]
    for it in items:
        if target.lower() in it["full_name"].lower():
            return it
    return None

def fetch_repo_readme(full_name: str) -> str:
    branches = ["main", "master"]
    filenames = ["README.md", "readme.md", "README.rst"]
    for b in branches:
        for fn in filenames:
            raw_url = f"https://raw.githubusercontent.com/{full_name}/{b}/{fn}"
            try:
                r = requests.get(raw_url, timeout=5)
                if r.status_code == 200:
                    return r.text
            except Exception:
                pass
    return ""

def copy_to_clipboard(text: str):
    """复制文本到 macOS 剪贴板"""
    try:
        process = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE, close_fds=True)
        process.communicate(input=text.encode("utf-8"))
        return True
    except Exception as e:
        print(f"[Warning] pbcopy 失败: {e}")
        return False

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

def cmd_media(target: str) -> str:
    """提取官方 README 中的多媒体或生成高质量配图"""
    matched = resolve_target(target)
    if not matched:
        print(f"[Error] 未找到对应的候选项目: {target}")
        return ""

    full_name = matched["full_name"]
    clean_name = full_name.replace("/", "_")
    target_dir = os.path.join(ASSETS_DIR, clean_name)
    os.makedirs(target_dir, exist_ok=True)

    print(f"🔍 正在检索 [{full_name}] 的官方配图与多媒体资源...")
    readme_text = fetch_repo_readme(full_name)

    downloaded = []

    # 1. 下载 GitHub 官方动态 OpenGraph 卡片
    og_url = f"https://opengraph.githubassets.com/1/{full_name}"
    og_path = os.path.join(target_dir, "og_card.png")
    try:
        r = requests.get(og_url, timeout=10)
        if r.status_code == 200 and len(r.content) > 1000:
            with open(og_path, "wb") as f:
                f.write(r.content)
            downloaded.append(("GitHub 官方 OpenGraph 社交卡片", og_path))
    except Exception as e:
        print(f"[Warn] 下载 OpenGraph 卡片失败: {e}")

    # 2. 正则检索 README 中的图片链接
    img_urls = re.findall(r'!\[.*?\]\((.*?)\)', readme_text) + re.findall(r'<img\s+.*?src=[\"\'](.*?)[\"\']', readme_text)
    
    # 过滤出可能是演示图、效果对比图、动图的链接
    demo_keywords = ["demo", "without", "with", "screen", "preview", "architecture", "overview", "showcase", "gif"]
    cand_imgs = []
    for u in img_urls:
        u_clean = u.split("?")[0].strip()
        if any(kw in u_clean.lower() for kw in demo_keywords) and not u_clean.endswith(".svg"):
            # 补全相对路径
            if u_clean.startswith("http"):
                cand_imgs.append(u_clean)
            elif not u_clean.startswith("/"):
                cand_imgs.append(f"https://raw.githubusercontent.com/{full_name}/main/{u_clean}")

    # 下载最多 3 张关键演示图
    for i, img_url in enumerate(cand_imgs[:3], 1):
        ext = os.path.splitext(img_url.split("?")[0])[1] or ".png"
        fn = f"demo_{i}{ext}"
        fp = os.path.join(target_dir, fn)
        try:
            r = requests.get(img_url, timeout=10)
            if r.status_code == 200 and len(r.content) > 2000:
                with open(fp, "wb") as f:
                    f.write(r.content)
                downloaded.append((f"官方演示图 {i} ({img_url.split('/')[-1]})", fp))
        except Exception:
            pass

    # 3. 针对对比图的特殊拼接增强 (如 pbakaus/impeccable)
    comparison_path = os.path.join(target_dir, "comparison.png")
    if os.path.exists(os.path.join(target_dir, "without.webp")) and os.path.exists(os.path.join(target_dir, "with.webp")):
        try:
            img1 = Image.open(os.path.join(target_dir, "without.webp")).convert("RGB")
            img2 = Image.open(os.path.join(target_dir, "with.webp")).convert("RGB")
            h = 800
            w1 = int(img1.width * (h / img1.height))
            w2 = int(img2.width * (h / img2.height))
            img1 = img1.resize((w1, h))
            img2 = img2.resize((w2, h))
            canvas = Image.new("RGB", (w1 + w2 + 20, h + 80), (15, 23, 42))
            canvas.paste(img1, (0, 80))
            canvas.paste(img2, (w1 + 20, 80))
            draw = ImageDraw.Draw(canvas)
            draw.text((30, 25), "❌ WITHOUT IMPECCABLE (AI Slop Default)", fill=(244, 63, 94))
            draw.text((w1 + 50, 25), "✨ WITH IMPECCABLE (Polished Aesthetic)", fill=(16, 185, 129))
            canvas.save(comparison_path, "PNG")
            downloaded.append(("🔥 智能合成对比大图 (Before vs After)", comparison_path))
        except Exception as e:
            print(f"[Warn] 拼接对比图失败: {e}")

    print("\n✅ 多媒体资源已就绪：")
    primary_image = ""
    for label, path in downloaded:
        print(f" - [{label}]: {path}")
        if "comparison" in path or not primary_image:
            primary_image = path

    print(f"\n💡 推荐发推配图: {primary_image}")
    return primary_image

def cmd_tweet(target: str, lang: str = "en"):
    """一键生成推文、复制到剪贴板，并在默认浏览器中唤醒 X 发布界面"""
    matched = resolve_target(target)
    if not matched:
        print(f"[Error] 未找到对应的候选项目: {target}")
        return

    full_name = matched["full_name"]
    stars = matched["stars"]
    url = matched["url"]

    # 1. 抓取与生成配图
    primary_img = cmd_media(full_name)

    # 2. 准备推文内容
    if lang == "en":
        # 英文单推浓缩版（适合直接通过 URL 预填到 X 发推框，保证不超字数）
        intent_text = (
            f"Every website built with Cursor or Claude Code looks identical: Inter font, purple-blue gradients, nested cards.\n\n"
            f"Enter Impeccable (97k+ stars, +2.3k today) — the design vocabulary & quality gate for coding agents.\n\n"
            f"✅ 62 rules to kill AI slop\n"
            f"✅ Real design vocabulary\n"
            f"✅ Built-in UI audit & critique\n"
            f"✅ 100% local, no API key\n\n"
            f"GitHub: {url}\n"
            f"#buildinpublic #Cursor #ClaudeCode #OpenSource"
        )

        # 完整长篇版（自动复制到剪贴板，支持 X Premium 或手动粘贴）
        full_text = (
            f"Every single website generated by Cursor or Claude Code looks completely identical:\n\n"
            f"Inter font for everything. Purple-to-blue gradients. Cards nested inside cards. A rounded-square icon tile floating above every heading. \n\n"
            f"The ultimate, unmistakable \"AI Slop\" aesthetic. \n\n"
            f"When you tell your agent to \"make it pop\", it just hallucinates more gradients.\n\n"
            f"Enter Impeccable (97k+ stars, +2,300 today) — the design vocabulary and quality gate built specifically for coding agents.\n\n"
            f"Here is why it's breaking GitHub right now:\n\n"
            f"✅ 62 Deterministic Slop Rules: Catches ugly AI design patterns, cramped padding, and sloppy hierarchy before you ship. Zero LLM tokens required.\n"
            f"✅ Actual Design Vocabulary: Stop saying \"make it modern\". Use precision playbooks like `/impeccable bolder the pricing cards`.\n"
            f"✅ Automated Aesthetic Critique: Scores your UI against core usability heuristics and ranks what looks broken.\n"
            f"✅ Production Audit: Scans accessibility (A11y), responsive breakpoints, and contrast from P0 (blocking) to P3 (polish).\n\n"
            f"Best part?\n"
            f"Zero API keys needed. Runs 100% locally. \n"
            f"One line to install: `npx impeccable install`\n"
            f"Works natively with Claude Code, Cursor, Codex, Copilot, Devin, and Antigravity.\n\n"
            f"If you vibe code or ship full-stack apps with AI, bookmark this immediately. \n\n"
            f"GitHub: {url}\n"
            f"Docs & Case Studies: https://impeccable.style\n\n"
            f"#buildinpublic #AIagents #Cursor #ClaudeCode #OpenSource #WebDev"
        )
    else:
        intent_text = (
            f"让 AI 写前端页面，全是一个鸟样：Inter 字体、紫蓝渐变、嵌套卡片，浓浓的 AI 塑料味！\n\n"
            f"GitHub 单日暴涨 2300 Star 的开源神器 Impeccable 彻底解决了：\n"
            f"✅ 62条防 AI 塑料味硬规则\n"
            f"✅ 精准设计词汇取代空洞提示词\n"
            f"✅ 自动化审美启发式打分 (critique)\n"
            f"✅ 性能与无障碍体检 (audit)\n\n"
            f"纯本地运行，免 API Key！\n"
            f"传送门: {url}\n"
            f"#开源 #AI编程 #Cursor #ClaudeCode"
        )
        full_text = intent_text

    # 3. 复制完整版到系统剪贴板
    copy_to_clipboard(full_text)
    print("📋 [已复制] 完整版长推文已写入系统剪贴板（如需发长帖，直接 ⌘V 粘贴即可）。")

    # 4. 在默认浏览器中打开 X 发帖界面
    intent_url = "https://twitter.com/intent/tweet?text=" + urllib.parse.quote(intent_text)
    print("🚀 正在唤醒系统默认浏览器打开 X 发帖窗口...")
    try:
        subprocess.run(["open", intent_url], check=True)
        print("✅ 已在浏览器中打开 X 发帖页面！")
    except Exception as e:
        print(f"[Error] 打开浏览器失败: {e}\n可手动访问: {intent_url}")

    if primary_img:
        print(f"\n🖼️ 提示：配图已保存在本地，可直接将此文件拖拽进推特发帖窗口：\n   👉 {primary_img}")

def cmd_autopost(target: str, lang: str = "en"):
    """使用 Playwright 会话凭证执行 100% 全自动后台发推（自动输入文案、传图并点击 Post）"""
    matched = resolve_target(target)
    if not matched:
        print(f"[Error] 未找到对应的候选项目: {target}")
        return

    full_name = matched["full_name"]
    url = matched["url"]
    cookies_path = os.path.join(ROOT_DIR, "cookies.json")
    if not os.path.exists(cookies_path):
        print("\n⚠️ 未检测到 X 登录凭证 cookies.json！")
        print("👉 请在终端运行一次登录绑定命令：python3 x_publisher.py login")
        print("（只需在弹出的浏览器登录一次，系统自动捕获保存凭据，之后永久免登、100% 全自动后台发推！）")
        return

    # 1. 抓取与生成配图
    primary_img = cmd_media(full_name)

    # 2. 准备文案
    if lang == "en":
        text = (
            f"Every single website generated by Cursor or Claude Code looks completely identical:\n\n"
            f"Inter font for everything. Purple-to-blue gradients. Cards nested inside cards. A rounded-square icon tile floating above every heading. \n\n"
            f"The ultimate, unmistakable \"AI Slop\" aesthetic. \n\n"
            f"When you tell your agent to \"make it pop\", it just hallucinates more gradients.\n\n"
            f"Enter Impeccable (97k+ stars, +2,300 today) — the design vocabulary and quality gate built specifically for coding agents.\n\n"
            f"Here is why it's breaking GitHub right now:\n\n"
            f"✅ 62 Deterministic Slop Rules: Catches ugly AI design patterns, cramped padding, and sloppy hierarchy before you ship. Zero LLM tokens required.\n"
            f"✅ Actual Design Vocabulary: Stop saying \"make it modern\". Use precision playbooks like `/impeccable bolder the pricing cards`.\n"
            f"✅ Automated Aesthetic Critique: Scores your UI against core usability heuristics and ranks what looks broken.\n"
            f"✅ Production Audit: Scans accessibility (A11y), responsive breakpoints, and contrast from P0 (blocking) to P3 (polish).\n\n"
            f"Best part?\n"
            f"Zero API keys needed. Runs 100% locally. \n"
            f"One line to install: `npx impeccable install`\n"
            f"Works natively with Claude Code, Cursor, Codex, Copilot, Devin, and Antigravity.\n\n"
            f"If you vibe code or ship full-stack apps with AI, bookmark this immediately. \n\n"
            f"GitHub: {url}\n"
            f"Docs & Case Studies: https://impeccable.style\n\n"
            f"#buildinpublic #AIagents #Cursor #ClaudeCode #OpenSource #WebDev"
        )
    else:
        text = (
            f"让 AI 写前端页面，全是一个鸟样：Inter 字体、紫蓝渐变、嵌套卡片，浓浓的 AI 塑料味！\n\n"
            f"GitHub 单日暴涨 2300 Star 的开源神器 Impeccable 彻底解决了：\n"
            f"✅ 62条防 AI 塑料味硬规则\n"
            f"✅ 精准设计词汇取代空洞提示词\n"
            f"✅ 自动化审美启发式打分 (critique)\n"
            f"✅ 性能与无障碍体检 (audit)\n\n"
            f"纯本地运行，免 API Key！\n"
            f"传送门: {url}\n"
            f"#开源 #AI编程 #Cursor #ClaudeCode"
        )

    import x_publisher
    success = x_publisher.cmd_post(text, primary_img)
    if success:
        cmd_mark(full_name)

def cmd_mark(target: str):
    state = load_state()
    seen = state.get("seen", {})
    matched = resolve_target(target)
    if not matched:
        print(f"[Error] 找不到项目: {target}")
        return

    name = matched["full_name"]
    if name in seen:
        seen[name]["posted"] = True
        state["seen"] = seen
        save_state(state)
        print(f"✅ 成功将 [{name}] 标记为已发布！")

def main():
    if len(sys.argv) < 2:
        print("用法:")
        print("  python3 post_helper.py list                     # 列出待发布候选项目")
        print("  python3 post_helper.py media <编号/项目名>       # 提取/合成项目的官方效果图与社交卡片")
        print("  python3 post_helper.py tweet <编号/项目名> [en]  # 一键唤醒浏览器预填发推并拷贝完整文案")
        print("  python3 post_helper.py mark <编号/项目名>        # 标记为已发布")
        return

    cmd = sys.argv[1].lower()
    if cmd == "list":
        show_all = len(sys.argv) > 2 and sys.argv[2] == "--all"
        cmd_list(unposted_only=not show_all)
    elif cmd == "media":
        if len(sys.argv) < 3:
            print("请指定项目编号或名称")
            return
        cmd_media(sys.argv[2])
    elif cmd in ["tweet", "post"]:
        if len(sys.argv) < 3:
            print("请指定项目编号或名称")
            return
        lang = "en"
        if len(sys.argv) > 3 and sys.argv[3] in ["zh", "cn"]:
            lang = "zh"
        cmd_tweet(sys.argv[2], lang=lang)
    elif cmd in ["auto", "auto-post", "autopost"]:
        if len(sys.argv) < 3:
            print("请指定项目编号或名称")
            return
        lang = "en"
        if len(sys.argv) > 3 and sys.argv[3] in ["zh", "cn"]:
            lang = "zh"
        cmd_autopost(sys.argv[2], lang=lang)
    elif cmd in ["mark", "mark-posted"]:
        if len(sys.argv) < 3:
            print("请指定项目编号或名称")
            return
        cmd_mark(sys.argv[2])
    else:
        print(f"未知命令: {cmd}")

if __name__ == "__main__":
    main()
