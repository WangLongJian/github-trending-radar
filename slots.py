#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""本机定时任务的发帖时刻。

Windows 计划任务每 4 小时跑一次，锚定太平洋时间 01:00（即 PT 1/5/9/13/17/21 点）。
每个账号只在自己时区的 09:00-24:00 窗口内发帖，每次最多 1 条。
冬令时下两个号每天都正好落进 4 个运行时刻：
  Alpha John (PT)  : 09 / 13 / 17 / 21
  王坤PAS   (CST)  : 09 / 13 / 17 / 21  (= PT 17 / 21 / 01 / 05)
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

RUN_TZ = ZoneInfo("America/Los_Angeles")
RUN_ANCHOR_HOUR = 1      # 计划任务从 PT 01:00 开始
RUN_EVERY_HOURS = 4
WINDOW_START, WINDOW_END = 9, 24   # 账号本地时间 [09:00, 24:00)


def in_window(dt_local: datetime) -> bool:
    return WINDOW_START <= dt_local.hour < WINDOW_END


def upcoming_runs(now: datetime, count: int):
    """从 now 之后（不含当前这一轮）列出接下来的运行时刻（PT 时区）。"""
    now_pt = now.astimezone(RUN_TZ)
    t = now_pt.replace(minute=0, second=0, microsecond=0)
    while (t.hour - RUN_ANCHOR_HOUR) % RUN_EVERY_HOURS != 0 or t <= now_pt:
        t += timedelta(hours=1)
        t = t.astimezone(RUN_TZ)
    out = []
    for _ in range(count * 10):
        out.append(t)
        if len(out) >= count:
            break
        t = (t + timedelta(hours=RUN_EVERY_HOURS)).astimezone(RUN_TZ)
    return out


def next_post_slots(now: datetime, account_tz: ZoneInfo, count: int):
    """接下来 count 个会给该账号发帖的运行时刻（换算成账号时区）。"""
    slots = []
    for t in upcoming_runs(now, count * 3):
        local = t.astimezone(account_tz)
        if in_window(local):
            slots.append(local)
            if len(slots) >= count:
                break
    return slots
