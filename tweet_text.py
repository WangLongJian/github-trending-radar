#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按 X 的规则计算推文长度，并在超长时裁剪（保住 GitHub 链接）。

X 的计数规则（twitter-text v3）：
- 链接一律算 23
- 拉丁字母等常用区段算 1，中文、日文、emoji 等算 2
- 上限 280
"""

import re

MAX_WEIGHT = 280
URL_WEIGHT = 23
URL_RE = re.compile(r"https?://\S+")
# 截断坏掉的链接，比如 "https://..." 或 "https://deeptutor.info/...."
BROKEN_URL_RE = re.compile(r"https?://\S*?\.{3,}\S*")
_LIGHT_RANGES = ((0, 4351), (8192, 8205), (8208, 8223), (8242, 8247))


def _char_weight(ch: str) -> int:
    cp = ord(ch)
    for lo, hi in _LIGHT_RANGES:
        if lo <= cp <= hi:
            return 1
    return 2


def weighted_len(text: str) -> int:
    total = 0
    pos = 0
    for m in URL_RE.finditer(text):
        total += sum(_char_weight(c) for c in text[pos:m.start()])
        total += URL_WEIGHT
        pos = m.end()
    total += sum(_char_weight(c) for c in text[pos:])
    return total


def fit_tweet(text: str, repo_url: str = "", limit: int = MAX_WEIGHT - 5) -> str:
    """把推文压到 limit 以内（留 5 的余量），尽量保留结构和 GitHub 链接。"""
    text = text.strip()

    # 1. 删掉被截断的坏链接（"https://..."），后面会补上完整的仓库链接
    text = BROKEN_URL_RE.sub("", text)
    # 描述里引用的外部官网链接也删掉，节省长度，只保留 GitHub 链接
    if repo_url:
        text = URL_RE.sub(lambda m: m.group(0) if "github.com" in m.group(0) else "", text)
        if repo_url not in text:
            # 被旧截断逻辑切坏的 "🔗 Check it ou..." 这种行，整行换掉
            text = re.sub(r"^🔗[^\n:：]*\.{2,}\s*$", "🔗 Check it out:", text, flags=re.M)
            # 原来的 "🔗 Check it out: https://..." 被删成 "🔗 Check it out:"，就把链接补回这一行
            lines = text.split("\n")
            for i in range(len(lines) - 1, -1, -1):
                if re.search(r"[:：]\s*$", lines[i]) and "🔗" in lines[i]:
                    lines[i] = lines[i].rstrip() + " " + repo_url
                    break
            else:
                lines.append(f"\n🔗 {repo_url}")
            text = "\n".join(lines)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()

    if weighted_len(text) <= limit:
        return text

    # 2. 从末尾逐个去掉 hashtag
    while weighted_len(text) > limit:
        m = re.search(r"\s*#\S+\s*$", text)
        if not m:
            break
        text = text[:m.start()].rstrip()
    if weighted_len(text) <= limit:
        return text

    # 3. 截短最长的一行（不含链接的那行，通常是 💡 描述）
    lines = text.split("\n")
    while weighted_len("\n".join(lines)) > limit:
        candidates = [(weighted_len(l), i) for i, l in enumerate(lines) if not URL_RE.search(l) and len(l) > 8]
        if not candidates:
            break
        _, idx = max(candidates)
        line = lines[idx].rstrip("…")
        lines[idx] = line[:-2].rstrip() + "…"
    text = "\n".join(lines)

    # 4. 兜底：还超就删掉不含链接的整行（从后往前）
    while weighted_len(text) > limit:
        lines = text.split("\n")
        for i in range(len(lines) - 1, -1, -1):
            if lines[i].strip() and not URL_RE.search(lines[i]):
                del lines[i]
                break
        else:
            break
        text = "\n".join(lines).strip()
    return text
