"""
投稿の数字（見られた数・いいね・保存・シェアなど）を集めて metrics.json に書く。
GitHub Actions（metrics.yml）が毎日1回動かす。鍵は GitHub Secrets のものを使う（ここには書かない）。

- 集めるのは投稿から14日以内のもの（それより古い数字はほぼ動かないので、APIのムダを省く）
- X は数字を読むのにもお金がかかる（1件ごと）。まとめて1回で読むので、1日あたりごく少額
- 権限が足りないSNSは、エラーを記録してほかのSNSは続ける
- DRY_RUN=1 なら、読む予定の件数だけ表示してAPIは呼ばない
"""
import datetime as dt
import json
import os
from zoneinfo import ZoneInfo

import requests

JST = ZoneInfo("Asia/Tokyo")
POSTED, METRICS, SCHEDULE = "posted.json", "metrics.json", "schedule.json"
DAYS = 14
DRY_RUN = os.environ.get("DRY_RUN") == "1"


def load(path, default):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return default


def threads_metrics(media_id):
    tok = os.environ["THREADS_ACCESS_TOKEN"]
    r = requests.get(f"https://graph.threads.net/v1.0/{media_id}/insights",
                     params={"metric": "views,likes,replies,reposts,quotes,shares", "access_token": tok}, timeout=30)
    r.raise_for_status()
    return {m["name"]: (m.get("values") or [{}])[0].get("value", m.get("total_value", {}).get("value"))
            for m in r.json().get("data", [])}


def instagram_metrics(media_id):
    tok = os.environ["IG_ACCESS_TOKEN"]
    r = requests.get(f"https://graph.instagram.com/v21.0/{media_id}/insights",
                     params={"metric": "views,reach,likes,comments,shares,saved,total_interactions",
                             "access_token": tok}, timeout=30)
    r.raise_for_status()
    return {m["name"]: (m.get("values") or [{}])[0].get("value") for m in r.json().get("data", [])}


def x_metrics(ids):
    """最大100件まとめて1回で読む"""
    import tweepy
    client = tweepy.Client(consumer_key=os.environ["X_API_KEY"], consumer_secret=os.environ["X_API_SECRET"],
                           access_token=os.environ["X_ACCESS_TOKEN"], access_token_secret=os.environ["X_ACCESS_SECRET"])
    out = {}
    for k in range(0, len(ids), 100):
        r = client.get_tweets(ids=ids[k:k + 100], tweet_fields=["public_metrics", "non_public_metrics"],
                              user_auth=True)
        for t in r.data or []:
            m = dict(t.public_metrics or {})
            m.update(t.non_public_metrics or {})
            out[str(t.id)] = m
    return out


def main():
    posted = load(POSTED, {})
    sched = {i["id"]: i for i in load(SCHEDULE, [])}
    metrics = load(METRICS, {})
    now = dt.datetime.now(JST)
    recent = {pid: rec for pid, rec in posted.items()
              if now - dt.datetime.fromisoformat(rec["at"]) <= dt.timedelta(days=DAYS)}
    todo = [(pid, p, mid) for pid, rec in recent.items() for p, mid in rec.get("results", {}).items()
            if mid and not str(mid).startswith(("ERROR", "DRY"))]
    print(f"数字を読む投稿: {len(todo)}件（{DAYS}日以内）")
    if DRY_RUN:
        return 0

    errors = {}
    x_ids = [mid for _, p, mid in todo if p == "x"]
    x_data = {}
    if x_ids:
        try:
            x_data = x_metrics(x_ids)
        except Exception as e:
            errors["x"] = str(e)[:200]
    for pid, p, mid in todo:
        try:
            if p == "x":
                m = x_data.get(str(mid))
            elif p == "threads":
                m = threads_metrics(mid) if "threads" not in errors else None
            elif p == "instagram":
                m = instagram_metrics(mid) if "instagram" not in errors else None
            else:
                m = None
        except Exception as e:
            errors[p] = str(e)[:200]
            m = None
        if m:
            item = sched.get(pid, {})
            metrics.setdefault(pid, {"at": posted[pid]["at"], "text": (item.get("text") or "")[:120],
                                     "kind": pid.split("-", 1)[-1]})
            metrics[pid][p] = m
            metrics[pid]["updated"] = now.isoformat(timespec="minutes")
    metrics["_errors"] = errors
    with open(METRICS, "w", encoding="utf-8") as f:
        json.dump(metrics, f, ensure_ascii=False, indent=1)
    print("書きました:", METRICS, "／エラー:", errors or "なし")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
