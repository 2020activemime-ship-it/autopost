"""
AIにやらせる女｜自動投稿システム v2（X + Threads／画像対応／SNS別出し分け）

schedule.json の1件の形：
  {
    "id": "0914-am",
    "at": "2026-09-14T07:30:00",          # JST
    "platforms": ["x", "threads", "instagram"],
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
- 失敗したSNSだけ、6時間以内なら次回の実行で自動再試行（成功済みSNSには二重投稿しない）
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
    ig_uid, ig_tok = os.environ.get("IG_USER_ID"), os.environ.get("IG_ACCESS_TOKEN")
    if ig_tok:
        try:
            r = requests.get(f"https://graph.instagram.com/v21.0/{ig_uid or 'me'}",
                             params={"fields": "username", "access_token": ig_tok}, timeout=30)
            j = r.json()
            print("instagram:", "OK @" + j["username"] if "username" in j else f"NG {j}")
        except Exception as e:
            print("instagram: NG", e)
    else:
        print("instagram: (IG_ACCESS_TOKEN 未設定)")
    print("image_base_url:", os.environ.get("IMAGE_BASE_URL") or "(未設定)")



BANNED = ["必ず", "絶対", "稼げる", "稼げます", "確実に", "保証", "バズる", "誰でも", "治る", "引き寄せられる", "100%"]

def lint_schedule(schedule: list) -> list:
    """投稿前の機械チェック：禁止語・重複・空文。問題があるIDのリストを返す（DRY_RUNで表示）"""
    problems = []
    seen = {}
    for item in schedule:
        txt = item.get("text", "").strip()
        if not txt:
            problems.append((item["id"], "空の本文")); continue
        hits = [w for w in BANNED if w in txt]
        if hits:
            problems.append((item["id"], "禁止語: " + "/".join(hits)))
        key = txt[:40]
        if key in seen:
            problems.append((item["id"], f"重複の疑い: {seen[key]} と冒頭が同じ"))
        seen.setdefault(key, item["id"])
    return problems



def post_instagram(text: str, image: str | None = None) -> str:
    """Instagram投稿。画像が必須（IG APIの仕様）。IMAGE_BASE_URL の公開URLを使う"""
    if len(text) > 2200:
        raise ValueError(f"IGキャプション超過（{len(text)}/2200）")
    if not image:
        raise ValueError("Instagramは画像が必須です（imageを指定してください）")
    if DRY_RUN:
        return f"DRY ig: {text[:30]}… image={image}"
    uid = os.environ.get("IG_USER_ID") or "me"
    tok = os.environ["IG_ACCESS_TOKEN"]
    img_base = os.environ.get("IMAGE_BASE_URL", "").rstrip("/")
    if not img_base:
        raise ValueError("IMAGE_BASE_URL が未設定です")
    base = f"https://graph.instagram.com/v21.0/{uid}"

    r = requests.post(f"{base}/media", data={
        "image_url": f"{img_base}/{os.path.basename(image)}",
        "caption": text,
        "access_token": tok,
    }, timeout=60)
    r.raise_for_status()
    creation_id = r.json()["id"]

    # 画像処理の完了を待ってから公開
    last = None
    for _ in range(10):
        time.sleep(5)
        r2 = requests.post(f"{base}/media_publish",
                           data={"creation_id": creation_id, "access_token": tok}, timeout=60)
        if r2.ok:
            return str(r2.json()["id"])
        last = r2
    last.raise_for_status()
    return ""


POSTERS = {"x": post_x, "threads": post_threads, "instagram": post_instagram}


def main() -> int:
    now = dt.datetime.now(JST)
    schedule = load(SCHEDULE, [])
    posted = load(POSTED, {})
    changed = False
    if DRY_RUN:
        print("=== DRY RUN（投稿しません）===")
        check_credentials()
        probs = lint_schedule(schedule)
        print("=== 投稿チェック ===", "問題なし" if not probs else "")
        for pid, why in probs:
            print("  NG", pid, why)

    for item in schedule:
        key = item["id"]
        prev = posted.get(key, {}).get("results", {})
        # 既に全SNS成功 or スキップ済みなら終わり。失敗したSNSだけ再試行する
        pending = [p for p in item.get("platforms", [])
                   if not (str(prev.get(p, "")) and not str(prev.get(p, "")).startswith("ERROR"))]
        if "skipped" in prev or not pending:
            continue
        when = dt.datetime.fromisoformat(item["at"])
        if when.tzinfo is None:
            when = when.replace(tzinfo=JST)
        if when > now:
            continue
        if now - when > dt.timedelta(hours=MAX_LATE_HOURS):
            if not DRY_RUN:
                posted[key] = {"at": now.isoformat(), "results": {**prev, "skipped": "too late"}}
                changed = True
            continue

        image = item.get("image")
        results = dict(prev)
        hits = [w for w in BANNED if w in item.get("text", "")]
        if hits:
            posted[key] = {"at": now.isoformat(), "results": {"skipped": "禁止語 " + "/".join(hits)}}
            changed = True
            print(key, "skipped (禁止語)", hits)
            continue
        for platform in pending:
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
