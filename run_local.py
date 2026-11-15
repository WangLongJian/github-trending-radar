#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""本机定时发帖入口（Windows 计划任务 "X Auto Poster" 每 4 小时调用一次）。

1. git pull 拿到云端每日抓取后的最新队列
2. 运行 cloud_publisher.py：两个号各发 1 条热度最高的待发项目，并按热度重排剩余时刻
3. 把 schedule_queue.json 提交推送回 GitHub
日志: logs/run_local.log    最近一次结果: logs/last_run.json
"""

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

DIR = Path(__file__).resolve().parent
LOG_DIR = DIR / "logs"
LOG_FILE = LOG_DIR / "run_local.log"
LAST_RUN = LOG_DIR / "last_run.json"
COOKIES_DIR = Path.home() / ".secrets" / "x-auto-poster"
PYTHON = Path(sys.executable).with_name("python.exe")  # pythonw 启动时也用 python.exe 跑子进程
if not PYTHON.exists():
    PYTHON = Path(sys.executable)
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def log(msg: str):
    LOG_DIR.mkdir(exist_ok=True)
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def run(cmd, timeout=600):
    env = dict(os.environ, PYTHONIOENCODING="utf-8", X_COOKIES_DIR=str(COOKIES_DIR))
    r = subprocess.run(cmd, cwd=DIR, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=timeout, env=env, creationflags=NO_WINDOW)
    out = (r.stdout or "") + (r.stderr or "")
    for l in out.strip().splitlines():
        log("   " + l)
    return r.returncode, out


def trim_log(max_lines=3000):
    try:
        lines = LOG_FILE.read_text(encoding="utf-8").splitlines()
        if len(lines) > max_lines:
            LOG_FILE.write_text("\n".join(lines[-max_lines:]) + "\n", encoding="utf-8")
    except FileNotFoundError:
        pass


def main():
    log("========== 开始本轮 ==========")
    status = {"started_at": datetime.now().astimezone().isoformat(), "publish_exit": None, "pushed": False}

    code, _ = run(["git", "pull", "--rebase", "--autostash"], timeout=120)
    if code != 0:
        log("⚠️ git pull 失败，用本地队列继续")

    # 开关文件（放在 logs/ 里，不进 git）：
    #   PAUSE   存在则本轮完全不发帖
    #   DRY_RUN 存在则只登录、输入、重排队列，不点发布
    if (LOG_DIR / "PAUSE").exists():
        log("⏸️ 检测到 logs/PAUSE，本轮跳过发帖")
        return
    if (LOG_DIR / "DRY_RUN").exists():
        os.environ["X_DRY_RUN"] = "1"
        log("🧪 检测到 logs/DRY_RUN，本轮只空跑")
    code, out = run([str(PYTHON), "cloud_publisher.py"], timeout=900)
    status["publish_exit"] = code
    status["posted"] = [l.strip() for l in out.splitlines() if "发布成功" in l]
    status["errors"] = [l.strip() for l in out.splitlines() if l.strip().startswith("❌")]

    _code, changes = run(["git", "status", "--porcelain", "schedule_queue.json"])
    if changes.strip():
        run(["git", "add", "schedule_queue.json"])
        run(["git", "commit", "-m", "Local publisher: update queue status [skip ci]"])
        for _attempt in range(3):
            c, _out = run(["git", "push"], timeout=120)
            if c == 0:
                status["pushed"] = True
                break
            run(["git", "pull", "--rebase", "--autostash"], timeout=120)
    else:
        status["pushed"] = True  # 没有改动，无需推送

    status["finished_at"] = datetime.now().astimezone().isoformat()
    LAST_RUN.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"========== 结束（发帖退出码 {status['publish_exit']}，推送 {'成功' if status['pushed'] else '失败'}）==========")
    trim_log()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # 计划任务里没有控制台，异常一定要进日志
        log(f"💥 运行异常: {e!r}")
        raise
