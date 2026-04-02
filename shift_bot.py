#!/usr/bin/env python3
"""
排班交班 TG Bot (GitHub Actions 单次运行模式)
4人轮转排班，每4天一个循环，在交班时间发送通知 @ 下班和上班的人。

班次:
  早班 8:00~16:00
  中班 16:00~23:59
  晚班 0:00~8:00

用法:
  python shift_bot.py --shift 0    # 00:00 交班 (中→晚)
  python shift_bot.py --shift 8    # 08:00 交班 (晚→早)
  python shift_bot.py --shift 16   # 16:00 交班 (早→中)
  python shift_bot.py --poll       # 轮询模式，回复查询消息
"""

import os
import sys
import argparse
from datetime import date, datetime, timedelta, timezone

import requests

BOT_TOKEN = os.environ.get("TG_BOT_TOKEN", "")
CHAT_ID = os.environ.get("TG_CHAT_ID", "")

# 员工列表: (姓名, TG用户名)
STAFF = [
    ("高尚", "@Satoshi223"),
    ("艺朗", "@earronyu2"),
    ("罡门", "@Dincoco69"),
    ("小瑜", "@username168168"),
]

# 排班基准日期 (2026年3月29日)
# 当天排班: 高尚=早, 艺朗=中, 罡门=晚, 小瑜=休息
BASE_DATE = date(2026, 3, 29)

CST = timezone(timedelta(hours=8))


def now_cst():
    return datetime.now(CST)


def today_cst():
    return now_cst().date()


def get_schedule(target_date):
    """
    获取指定日期的排班。
    4天一个循环，休息人依次为: 小瑜 -> 罡门 -> 艺朗 -> 高尚 -> 小瑜 ...
    其余3人按原始顺序分别上 早/中/晚 班。
    """
    delta = (target_date - BASE_DATE).days
    rest_index = (3 - delta % 4) % 4

    working = [s for i, s in enumerate(STAFF) if i != rest_index]
    rest_person = STAFF[rest_index]

    return {
        "早": working[0],
        "中": working[1],
        "晚": working[2],
        "休息": rest_person,
    }


def get_current_shift_info():
    """获取当前值班人信息"""
    now = now_cst()
    today = now.date()
    hour = now.hour
    s = get_schedule(today)

    if 0 <= hour < 8:
        shift_name = "晚班"
        shift_time = "00:00~08:00"
        on_duty = s["晚"]
    elif 8 <= hour < 16:
        shift_name = "早班"
        shift_time = "08:00~16:00"
        on_duty = s["早"]
    else:
        shift_name = "中班"
        shift_time = "16:00~23:59"
        on_duty = s["中"]

    rest_name, rest_user = s["休息"]

    msg = (
        f"📋 当前值班 — {today.month}月{today.day}日 {now.strftime('%H:%M')}\n"
        f"\n"
        f"🟢 当前: {shift_name} ({shift_time})\n"
        f"   值班人: {on_duty[0]} {on_duty[1]}\n"
        f"\n"
        f"今日排班:\n"
        f"  晚 00:00~08:00  {s['晚'][0]} {s['晚'][1]}\n"
        f"  早 08:00~16:00  {s['早'][0]} {s['早'][1]}\n"
        f"  中 16:00~23:59  {s['中'][0]} {s['中'][1]}\n"
        f"  休息: {rest_name} {rest_user}"
    )
    return msg


def send_message(text, chat_id=None, reply_to=None):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = {"chat_id": chat_id or CHAT_ID, "text": text, "parse_mode": "HTML"}
    if reply_to:
        data["reply_to_message_id"] = reply_to
    resp = requests.post(url, json=data, timeout=10)
    resp.raise_for_status()
    print("消息发送成功")


def poll_and_reply():
    """轮询 Telegram 消息，回复 @bot 的查询"""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"

    # 获取待处理消息
    resp = requests.get(url, params={"timeout": 0}, timeout=10)
    resp.raise_for_status()
    updates = resp.json().get("result", [])

    if not updates:
        print("没有新消息")
        return

    # 获取 bot 自己的用户名
    me_resp = requests.get(
        f"https://api.telegram.org/bot{BOT_TOKEN}/getMe", timeout=10
    )
    me_resp.raise_for_status()
    bot_username = me_resp.json()["result"]["username"].lower()
    bot_id = me_resp.json()["result"]["id"]

    replied = 0
    for update in updates:
        msg = update.get("message", {})
        if not msg:
            continue

        text = msg.get("text", "")
        chat_id = msg.get("chat", {}).get("id")
        message_id = msg.get("message_id")

        # 检测是否 @ 了 bot 或发送了 /duty /值班 命令
        should_reply = False

        # 检查 entities 中是否有 bot mention
        for entity in msg.get("entities", []):
            if entity.get("type") == "mention":
                mention = text[entity["offset"]:entity["offset"] + entity["length"]]
                if mention.lower() == f"@{bot_username}":
                    should_reply = True
                    break
            elif entity.get("type") == "bot_command":
                cmd = text[entity["offset"]:entity["offset"] + entity["length"]]
                if cmd.lower() in ("/duty", "/值班", f"/duty@{bot_username}", f"/值班@{bot_username}"):
                    should_reply = True
                    break

        # 检查是否是回复 bot 的消息
        reply_to = msg.get("reply_to_message", {})
        if reply_to.get("from", {}).get("id") == bot_id:
            should_reply = True

        if should_reply:
            info = get_current_shift_info()
            send_message(info, chat_id=chat_id, reply_to=message_id)
            replied += 1

    # 标记所有消息为已读，避免下次重复处理
    last_update_id = updates[-1]["update_id"]
    requests.get(url, params={"offset": last_update_id + 1, "timeout": 0}, timeout=10)
    print(f"处理了 {len(updates)} 条消息，回复了 {replied} 条")


# ── 交班通知 ──

def handover_0():
    today = today_cst()
    yesterday = today - timedelta(days=1)
    off_name, off_user = get_schedule(yesterday)["中"]
    on_name, on_user = get_schedule(today)["晚"]
    s = get_schedule(today)
    rest_name, rest_user = s["休息"]

    return (
        f"🔔 交班通知 — {today.month}月{today.day}日 00:00\n"
        f"\n"
        f"⬇️ 中班下班: {off_name} {off_user}\n"
        f"⬆️ 晚班上班: {on_name} {on_user}\n"
        f"\n"
        f"📋 今日排班:\n"
        f"  晚 00:00~08:00  {s['晚'][0]} {s['晚'][1]}\n"
        f"  早 08:00~16:00  {s['早'][0]} {s['早'][1]}\n"
        f"  中 16:00~23:59  {s['中'][0]} {s['中'][1]}\n"
        f"  休息: {rest_name} {rest_user}\n"
        f"\n"
        f"请做好交接！"
    )


def handover_8():
    today = today_cst()
    s = get_schedule(today)
    off_name, off_user = s["晚"]
    on_name, on_user = s["早"]

    return (
        f"🔔 交班通知 — {today.month}月{today.day}日 08:00\n"
        f"\n"
        f"⬇️ 晚班下班: {off_name} {off_user}\n"
        f"⬆️ 早班上班: {on_name} {on_user}\n"
        f"\n"
        f"请做好交接！"
    )


def handover_16():
    today = today_cst()
    s = get_schedule(today)
    off_name, off_user = s["早"]
    on_name, on_user = s["中"]

    return (
        f"🔔 交班通知 — {today.month}月{today.day}日 16:00\n"
        f"\n"
        f"⬇️ 早班下班: {off_name} {off_user}\n"
        f"⬆️ 中班上班: {on_name} {on_user}\n"
        f"\n"
        f"请做好交接！"
    )


HANDLERS = {0: handover_0, 8: handover_8, 16: handover_16}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--shift", type=int, choices=[0, 8, 16],
                       help="交班时间: 0, 8, 或 16")
    group.add_argument("--poll", action="store_true",
                       help="轮询模式: 检查并回复查询消息")
    args = parser.parse_args()

    if not BOT_TOKEN or not CHAT_ID:
        print("错误: 请设置环境变量 TG_BOT_TOKEN 和 TG_CHAT_ID")
        sys.exit(1)

    if args.poll:
        poll_and_reply()
    else:
        msg = HANDLERS[args.shift]()
        print(msg)
        send_message(msg)
