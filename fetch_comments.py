"""
Threadsに来たコメント（自分の投稿・自分の返信への返信）を、鍵を使って集めて comments.json に書く。
ブラウザを使わないので、パソコンが寝ていても GitHub Actions（comments.yml）が動かせる。

- 集めるのは、自分が直近14日に出した投稿・返信（me/threads）への直接の返信
- 自分自身の返信は除く
- 鍵は GitHub Secrets の THREADS_ACCESS_TOKEN（ここには書かない）
- DRY_RUN=1 なら件数だけ表示して書かない
"""
import datetime as dt
import json
import os
import sys

import requests

BASE = "https://graph.threads.net/v1.0"
OUT = "comments.json"
DAYS = 14


def get(url, **params):
    params["access_token"] = os.environ["THREADS_ACCESS_TOKEN"]
    r = requests.get(url, params=params, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"{url.replace(BASE, '')} -> {r.status_code} {r.text[:200]}")
    return r.json()


def paged(url, **params):
    while url:
        j = get(url, **params)
        for it in j.get("data", []):
            yield it
        url = (j.get("paging") or {}).get("next")
        params = {}


def main():
    me = get(f"{BASE}/me", fields="id,username")
    my_name = me.get("username", "")
    since = int((dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=DAYS)).timestamp())
    mine = list(paged(f"{BASE}/me/threads", fields="id,text,timestamp,permalink,is_reply", since=since, limit=100))
    print(f"自分の投稿・返信: {len(mine)}件（{DAYS}日以内）")

    old = {}
    if os.path.exists(OUT):
        with open(OUT, encoding="utf-8") as f:
            old = json.load(f).get("comments", {})
    comments = dict(old)
    new = 0
    for t in mine:
        try:
            reps = list(paged(f"{BASE}/{t['id']}/replies",
                              fields="id,text,username,timestamp,permalink,is_reply_owned_by_me", limit=100))
        except RuntimeError as e:
            print("読めない:", t["id"], e)
            continue
        for r in reps:
            if r.get("is_reply_owned_by_me") or r.get("username") == my_name:
                continue
            if r["id"] not in comments:
                new += 1
            comments[r["id"]] = {
                "username": r.get("username", ""),
                "text": r.get("text", ""),
                "at": r.get("timestamp", ""),
                "permalink": r.get("permalink", ""),
                "to_post_id": t["id"],
                "to_post_text": (t.get("text") or "")[:120],
                "to_post_is_my_reply": bool(t.get("is_reply")),
            }
    print(f"コメント: 全{len(comments)}件、新しいもの{new}件")
    if os.environ.get("DRY_RUN") == "1":
        return 0
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({"updated": dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).strftime("%Y-%m-%dT%H:%M+09:00"),
                   "me": my_name, "comments": comments}, f, ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # 鍵の中身は出さない
        print("ERROR:", str(e)[:300])
        sys.exit(1)
