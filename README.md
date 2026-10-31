# 📡 GitHub Trending Radar

> 每天自动化检索 GitHub 上热度急剧上升的优质开源项目，过滤去重并构建候选池，赋能 X（Twitter）高效技术内容创作。

[![Auto Collect Daily Candidates](https://github.com/WangLongJian/github-trending-radar/actions/workflows/daily_collect.yml/badge.svg)](https://github.com/WangLongJian/github-trending-radar/actions/workflows/daily_collect.yml)
[![Zero External API](https://img.shields.io/badge/External%20APIs-None%20Needed-brightgreen)](#)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

---

## 🌟 核心亮点

- **云端零成本自动化 (GitHub Actions)**：每天 UTC 01:00（北京时间 09:00）自动无服务器运行，无需自备服务器与云函数。
- **零外部 API 依赖**：
  - **不需要申请繁琐的 X (Twitter) 开发者账号**：规避 403 权限问题、免受封控困扰，通过点击预填链接或本地浏览器直接发布。
  - **不需要额外付费的 LLM API Key**：直接与本地 AI 智能体（Antigravity / Claude）对话，让智能体基于候选库精读 README 撰写硬核推文。
- **多维度热度侦测**：
  - 自动抓取 `github.com/trending` 全局、Python、TypeScript 每日榜单。
  - 通过 GitHub Search 挖掘 7 天内新建且 Star 激增的黑马新星。
- **智能过滤与归类**：自动剔除刷星、低质或空 README 仓库，自动归类标签：`🤖 AI & Agent Skills`、`🎬 AI 视频/多媒体`、`🧠 大模型前沿`、`🛠️ 开发者工具`。
- **一键预填发推（One-Click Tweet）**：每个候选项目自动生成 `https://twitter.com/intent/tweet?text=...` 预填超链接，点击即可在已登录浏览器中完成发帖。

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
