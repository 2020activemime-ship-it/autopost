"""
AIにやらせる女｜自動投稿システム v2（X + Threads／画像対応／SNS別出し分け）

schedule.json の1件の形：
  {
    "id": "0914-am",
    "at": "2026-09-14T07:30:00",          # JST
    "platforms": ["x", "threads"],
    "text": "共通の本文",
    "text_x": "Xだけ別の本文（任意）",
    "text_threads": "Threadsだけ別の本文（任意・500字まで）",
    "image": "images/0914-am.png"          # 任意。あれば画像付き
  }

機能：
- 予定時刻(JST)を過ぎた未投稿だけを公式APIで投稿、posted.json に記録（二重投稿しない）
- SNS別テキスト：text_<platform> があればそれを使う（なければ text）
- X の文字数ガード：日本語は1文字=2カウント（上限280）。超えたらXはスキップして ERROR を記録
- 画像：X はファイルをアップロード、Threads は公開URL（IMAGE_BASE_URL + ファイル名）
- DRY_RUN=1 なら投稿せず「何を出すか」だけ表示（テスト用・記録もしない）
- 予定から6時間以上過ぎた古い投稿は出さない（事故防止）
"""
import datetime as dt
import json
import os
import sys
import time
from zoneinfo import ZoneInfo

import requests

JST = ZoneInfo("Asia/Tokyo")
SCHEDULE = "schedule.json"
POSTED = "posted.json"
MAX_LATE_HOURS = 6
DRY_RUN = os.environ.get("DRY_RUN") == "1"


def load(path, default):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return default


def text_for(item: dict, platform: str) -> str:
    return (item.get(f"text_{platform}") or item["text"]).strip()


def x_weighted_len(s: str) -> int:
    # Xの仕様：日本語などの全角系は1文字=2、半角英数は1（上限280）
    return sum(2 if ord(ch) > 0x2E7F else 1 for ch in s)


def post_x(text: str, image: str | None = None) -> str:
    if x_weighted_len(text) > 280:
        raise ValueError(f"X文字数オーバー（{x_weighted_len(text)}/280）。text_x で短い版を用意してください")
    if DRY_RUN:
        return f"DRY x: {text[:30]}… image={image}"
    import tweepy

    keys = dict(
        consumer_key=os.environ["X_API_KEY"],
        consumer_secret=os.environ["X_API_SECRET"],
        access_token=os.environ["X_ACCESS_TOKEN"],
        access_token_secret=os.environ["X_ACCESS_SECRET"],
    )
    client = tweepy.Client(**keys)
    media_ids = None
    if image and os.path.exists(image):
        try:
            auth = tweepy.OAuth1UserHandler(
                keys["consumer_key"], keys["consumer_secret"],
                keys["access_token"], keys["access_token_secret"],
            )
            media = tweepy.API(auth).media_upload(image)
            media_ids = [media.media_id]
        except Exception as e:  # 画像だけ失敗したら文字だけで投稿
            print(f"[x] image upload failed, posting text only: {e}")
    r = client.create_tweet(text=text, media_ids=media_ids)
    return str(r.data["id"])


def post_threads(text: str, image: str | None = None) -> str:
    if len(text) > 500:
        raise ValueError(f"Threads文字数オーバー（{len(text)}/500）")
    if DRY_RUN:
        return f"DRY threads: {text[:30]}… image={image}"
    uid = os.environ.get("THREADS_USER_ID") or "me"  # 未設定なら "me"（自分）でOK
    tok = os.environ["THREADS_ACCESS_TOKEN"]
    base = f"https://graph.threads.net/v1.0/{uid}"
    data = {"text": text, "access_token": tok, "media_type": "TEXT"}
    if image:
        img_base = os.environ.get("IMAGE_BASE_URL", "").rstrip("/")
        if img_base:
            data["media_type"] = "IMAGE"
            data["image_url"] = f"{img_base}/{os.path.basename(image)}"
        else:
            print("[threads] IMAGE_BASE_URL not set, posting text only")

    r = requests.post(f"{base}/threads", data=data, timeout=30)
    r.raise_for_status()
    creation_id = r.json()["id"]

    last = None
    for _ in range(6):  # 画像は処理待ちが要ることがある
        r2 = requests.post(
            f"{base}/threads_publish",
            data={"creation_id": creation_id, "access_token": tok},
            timeout=30,
        )
        if r2.ok:
            return str(r2.json()["id"])
        last = r2
        time.sleep(5)
    last.raise_for_status()
    return ""


def check_credentials() -> None:
    """DRY_RUN時：投稿せずに鍵が有効かだけ確認する"""
    print("=== 鍵チェック ===")
    tok = os.environ.get("THREADS_ACCESS_TOKEN")
    if tok:
        try:
            r = requests.get("https://graph.threads.net/v1.0/me",
                             params={"fields": "id,username", "access_token": tok}, timeout=30)
            j = r.json()
            print("threads:", "OK @" + j["username"] if "username" in j else f"NG {j}")
        except Exception as e:
            print("threads: NG", e)
    else:
        print("threads: (THREADS_ACCESS_TOKEN 未設定)")
    if all(os.environ.get(k) for k in ("X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_SECRET")):
        try:
            import tweepy
            c = tweepy.Client(
                consumer_key=os.environ["X_API_KEY"], consumer_secret=os.environ["X_API_SECRET"],
                access_token=os.environ["X_ACCESS_TOKEN"], access_token_secret=os.environ["X_ACCESS_SECRET"],
            )
            me = c.get_me()
            print("x:", "OK @" + me.data.username)
        except Exception as e:
            print("x: NG", e)
    else:
        print("x: (X の鍵が未設定)")
    print("image_base_url:", os.environ.get("IMAGE_BASE_URL") or "(未設定)")


POSTERS = {"x": post_x, "threads": post_threads}


def main() -> int:
    now = dt.datetime.now(JST)
    schedule = load(SCHEDULE, [])
    posted = load(POSTED, {})
    changed = False
    if DRY_RUN:
        print("=== DRY RUN（投稿しません）===")
        check_credentials()

    for item in schedule:
        key = item["id"]
        if key in posted:
            continue
        when = dt.datetime.fromisoformat(item["at"])
        if when.tzinfo is None:
            when = when.replace(tzinfo=JST)
        if when > now:
            continue
        if now - when > dt.timedelta(hours=MAX_LATE_HOURS):
            if not DRY_RUN:
                posted[key] = {"at": now.isoformat(), "results": {"skipped": "too late"}}
                changed = True
            continue

        image = item.get("image")
        results = {}
        for platform in item.get("platforms", []):
            fn = POSTERS.get(platform)
            if not fn:
                results[platform] = "unknown platform"
                continue
            try:
                results[platform] = fn(text_for(item, platform), image)
            except Exception as e:
                results[platform] = f"ERROR: {e}"
        print(key, results)
        if not DRY_RUN:
            posted[key] = {"at": now.isoformat(), "results": results}
            changed = True

    if changed:
        with open(POSTED, "w", encoding="utf-8") as f:
            json.dump(posted, f, ensure_ascii=False, indent=2)
    elif not DRY_RUN:
        print("nothing due at", now.isoformat())
    return 0


if __name__ == "__main__":
    sys.exit(main())
