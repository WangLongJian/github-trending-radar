# 📡 GitHub Trending Radar

> 每天自动化检索 GitHub 上热度急剧上升的优质开源项目，过滤去重并构建候选池，赋能 X（Twitter）高效技术内容创作。

[![Auto Collect Daily Candidates](https://github.com/WangLongJian/github-trending-radar/actions/workflows/daily_collect.yml/badge.svg)](https://github.com/WangLongJian/github-trending-radar/actions/workflows/daily_collect.yml)
[![Zero External API](https://img.shields.io/badge/External%20APIs-None%20Needed-brightgreen)](#)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

---

## 🌟 核心亮点

- **云端零成本自动化 (GitHub Actions)**：每天 UTC 01:00（北京时间 09:00）自动无服务器运行，无需自备服务器与云函数。
- **双账号独立精准定位**：
  - 🇬🇧 **Alpha John**：专供英文内容（全球技术圈、Build in Public、极客黑客、硅谷一人独角兽公司）。
  - 🇨🇳 **王坤PAS**：专供中文内容（击碎认知差、搞钱杠杆、一人公司、避免被 AI 淘汰的深度硬核文案）。
- **结合大模型多维度情绪文案引擎**：拒绝千篇一律的官方说明书，支持多维度吸睛策略（提高效率、商业搞钱、一人公司、创作者必备、量化/投资分析神器）。
- **一键排期发布（Schedule）**：每个项目针对两个账号分别生成定制文案与点击预填链接，在 X 网页端点击 📅 日历图标即可一键完成未来排期。

---

## 📂 项目结构

```text
github-trending-radar/
├── .github/workflows/
│   └── daily_collect.yml       # GitHub Actions 每日定时运行工作流
├── candidates/                 # 每日归档历史目录
│   └── 2026-10-30.md           # 每日精选开源项目清单
├── candidates.md               # 滚动更新的主候选池（最新未发布项目置顶）
├── collector.py                # 核心收集与分类脚本（云端 & 本地共用）
├── post_helper.py              # 本地交互管理与一键推文生成 CLI
├── requirements.txt            # Python 极简依赖 (requests, beautifulsoup4)
├── state.json                  # 已收录与已发布项目的去重状态库
└── README.md                   # 项目文档
```

---

## 🚀 协同工作流（如何使用）

### 模式 A：人机对话（最推荐、推文质量最高）

每天任何时候，直接在聊天窗口唤醒 AI 助手：
> **你**：“查看一下今天的 candidates 项目，挑出最好的两个写成 X 帖子。”
>
> **AI**：自动读取 `candidates.md`，拉取对应项目的完整 README，生成结构化技术评析（定位、痛点、技术特色、边界、适合谁），并附带一键发推链接。
>
> **你**：点击链接，浏览器已自动填入文案，点击【Post】即发布！

---

### 模式 B：使用本地 CLI 助手 (`post_helper.py`)

```bash
# 1. 查看当前待发布的候选项目列表
python3 post_helper.py list

# 2. 提取指定编号项目的 README 并生成推文草稿与发推链接
python3 post_helper.py draft 1

# 3. 在 X 上发布完成后，将其标记为已发布（下次列表自动隐藏）
python3 post_helper.py mark 1
```

---

## ⚙️ 部署说明

本仓库已部署于 GitHub，依靠 GitHub Actions 自动化运转：
1. **定时运行**：每天定时触发，通过 `github-actions[bot]` 自动提交最新 candidates 到仓库。
2. **手动触发**：亦可在 GitHub 网页仓库的 **Actions** 标签页中，选择 **Daily Trending Radar Collector**，点击 **Run workflow** 随时手动抓取。

---

## 📄 许可证

本项目遵循 [MIT License](LICENSE)。
