"""
replies_out.json に入っている返信を、Threadsの鍵で送る（ブラウザ不要）。

replies_out.json の形：
[
 {"reply_to_id": "相手のコメントのID", "text": "返信の本文", "user": "相手の名前（記録用）"}
]

- 送ったものは replied.json に記録し、replies_out.json から消す
- 同じ reply_to_id には二度と送らない
- 禁止語が入っていたら送らずに残す（人が直す）
- 1回の実行で最大20件
"""
import datetime as dt
import json
import os
import sys
import time

import requests

BASE = "https://graph.threads.net/v1.0"
QUEUE, DONE = "replies_out.json", "replied.json"
BANNED = ["必ず", "絶対", "稼げる", "稼げます", "確実に", "保証", "バズる", "誰でも", "治る", "引き寄せられる", "100%"]
MAX = 20


def load(p, d):
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    return d


def save(p, v):
    with open(p, "w", encoding="utf-8") as f:
        json.dump(v, f, ensure_ascii=False, indent=1)


def send(uid, tok, text, reply_to):
    r = requests.post(f"{BASE}/{uid}/threads", data={"media_type": "TEXT", "text": text,
                                                      "reply_to_id": reply_to, "access_token": tok}, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"create {r.status_code} {r.text[:200]}")
    cid = r.json()["id"]
    time.sleep(3)
    r = requests.post(f"{BASE}/{uid}/threads_publish", data={"creation_id": cid, "access_token": tok}, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"publish {r.status_code} {r.text[:200]}")
    return r.json()["id"]


def main():
    queue = load(QUEUE, [])
    done = load(DONE, {})
    if not queue:
        print("送るものなし")
        return 0
    tok = os.environ["THREADS_ACCESS_TOKEN"]
    uid = requests.get(f"{BASE}/me", params={"fields": "id", "access_token": tok}, timeout=30).json()["id"]
    rest, sent = [], 0
    for it in queue:
        rid, text = str(it.get("reply_to_id", "")), (it.get("text") or "").strip()
        if not rid or not text:
            continue
        if rid in done:
            print("済み:", rid)
            continue
        hit = [w for w in BANNED if w in text]
        if hit or sent >= MAX:
            print("残す:", rid, hit or "上限")
            rest.append(it)
            continue
        if os.environ.get("DRY_RUN") == "1":
            print("DRY:", rid, text[:40])
            rest.append(it)
            continue
        try:
            mid = send(uid, tok, text, rid)
            done[rid] = {"id": mid, "text": text, "user": it.get("user", ""),
                         "sent": dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).strftime("%Y-%m-%dT%H:%M+09:00")}
            sent += 1
            print("OK:", it.get("user", ""), text[:40])
            time.sleep(20)   # 人の速さで
        except Exception as e:
            print("ERROR:", rid, str(e)[:200])
            rest.append(it)
    save(DONE, done)
    save(QUEUE, rest)
    print(f"送った: {sent}件、残り: {len(rest)}件")
    return 0


if __name__ == "__main__":
    sys.exit(main())
