"""
リール動画（Instagram用の縦動画）を、その日の朝の投稿文から自動で作る。

GitHub Actions（クラウド）でもパソコンでも動く。
- 朝の投稿（*-am）があって、まだリール（*-reel）が無い日を探す
- 絵文字は動画に入れない（フォントに無く、四角い箱になるため。キャプションには残る）
- 文は「句読点のところ」で改行して、句読点は消す（言葉の途中では切らない）
- Instagramのカードと同じ世界観（薄いピンク・金の罫・明朝）に、1行ずつ現れる動きを付ける
- images/DDDD-reel.mp4 を作り、schedule.json に 12:30 の予約を足す

使い方:
  python make_reels.py            # これから14日ぶん
  python make_reels.py 21         # これから21日ぶん
  python make_reels.py --sample   # 見本を1本だけ作る（予約は足さない）

必要なもの: pillow / imageio-ffmpeg と 日本語の明朝フォント
"""
import datetime as dt
import json
import math
import os
import re
import shutil
import subprocess
import sys
from zoneinfo import ZoneInfo

JST = ZoneInfo("Asia/Tokyo")
HERE = os.path.dirname(os.path.abspath(__file__))
SCHEDULE = os.path.join(HERE, "schedule.json")
IMAGES = os.path.join(HERE, "images")
TAGS = "\n\n#自分軸 #自己肯定感 #自分を大切に #お金の不安 #AI活用 #引き寄せ #手抜きはスキル"
POST_AT = "12:30:00"

W, H, FPS = 1080, 1920, 30
INK = (58, 48, 45)             # 本文（濃い茶）
SAKURA = (194, 104, 130)       # 締めの一行
GOLD = (168, 132, 63)
MUTED = (140, 123, 116)
BG_IN = (255, 253, 252)        # 中心
BG_MID = (253, 240, 243)
BG_OUT = (240, 201, 211)       # 外側

IN_FRAMES = 16                 # 1行が現れるまで
STAGGER = 7                    # 行ごとのずれ
HOLD = 64                      # 見せている時間
OUT_FRAMES = 12                # 消えるまで

MINCHO_BOLD = ["/usr/share/fonts/opentype/noto/NotoSerifCJK-Medium.ttc",
               "/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc",
               "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc",
               os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", "yumindb.ttf")]
MINCHO_THIN = ["/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc",
               "/usr/share/fonts/opentype/noto/NotoSerifCJK-Light.ttc",
               os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", "yumin.ttf")]

PUNCT = ("、", "。", "！", "？", "，", "…")
EMOJI = re.compile("[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\uFE0F\u2661\u2665\u203C\u2049]")


def pick(paths):
    for p in paths:
        if os.path.exists(p):
            return p
    # 見つからなければ、入っているフォントの中から明朝（Serif）系を探す
    import glob
    for pat in ("/usr/share/fonts/**/*Serif*CJK*", "/usr/share/fonts/**/*Serif*JP*",
                "/usr/share/fonts/**/*Mincho*", "/usr/share/fonts/**/*CJK*"):
        found = sorted(glob.glob(pat, recursive=True))
        if found:
            return found[0]
    raise SystemExit("日本語のフォントが見つかりません: " + ", ".join(paths))


# ---------- 文を読みやすく分ける ----------

def clean(text):
    """絵文字と余分な空白を落とす（動画のフォントに絵文字が無いため）"""
    return EMOJI.sub("", text).replace("　", " ").strip()


def balanced(s):
    return s.count("「") == s.count("」")


def split_lines(line):
    parts, buf = [], ""
    for ch in line:
        buf += ch
        if ch in PUNCT and balanced(buf):
            parts.append(buf); buf = ""
    if buf:
        parts.append(buf)
    return parts or [line]


def to_slides(text):
    blocks = [b.strip() for b in re.split(r"\n\s*\n", clean(text)) if b.strip()]
    slides = []
    for b in blocks:
        lines = [clean(l) for l in b.split("\n")]
        lines = [l for l in lines if l]
        while lines:
            slides.append(lines[:3]); lines = lines[3:]
    return slides[:4]


def wrap(lines):
    out = []
    for line in lines:
        out += split_lines(line)
    out = [l.rstrip("、。，… ").strip() for l in out]
    out = [l for l in out if l]
    while len(out) > 4:
        i = min(range(len(out) - 1), key=lambda k: len(out[k]) + len(out[k + 1]))
        out[i:i + 2] = [out[i] + " " + out[i + 1]]
    return out


# ---------- 背景 ----------

_BG = {}


def base_background():
    """薄いピンクのグラデーション（Instagramのカードと同じ雰囲気）を1枚作る"""
    from PIL import Image, ImageFilter
    if "bg" in _BG:
        return _BG["bg"]
    small = Image.new("RGB", (W // 8, H // 8))
    px = small.load()
    cx, cy = small.width / 2, small.height * 0.46
    rad = small.height * 0.62
    for y in range(small.height):
        for x in range(small.width):
            d = min(1.0, math.hypot((x - cx) * 1.25, y - cy) / rad)
            if d < 0.55:
                k = d / 0.55
                c = tuple(int(BG_IN[i] + (BG_MID[i] - BG_IN[i]) * k) for i in range(3))
            else:
                k = (d - 0.55) / 0.45
                c = tuple(int(BG_MID[i] + (BG_OUT[i] - BG_MID[i]) * (k ** 0.9)) for i in range(3))
            px[x, y] = c
    big = small.resize((int(W * 1.16), int(H * 1.16)), Image.BICUBIC).filter(ImageFilter.GaussianBlur(6))
    _BG["bg"] = big
    return big


def background(t):
    """t は 0〜1。少しだけ動かして、止まった画にしない"""
    big = base_background()
    dx = int((big.width - W) * (0.5 + 0.5 * math.sin(t * math.pi * 0.9)))
    dy = int((big.height - H) * (0.5 + 0.5 * math.cos(t * math.pi * 0.7)))
    return big.crop((dx, dy, dx + W, dy + H)).copy()


def bokeh_sprite(radius, alpha, color):
    """ふんわり光る丸を1枚作る（背景に漂わせる粒）"""
    from PIL import Image, ImageDraw, ImageFilter
    pad = int(radius * 0.9)                      # ぼかしが外にはみ出して四角く切れないよう余白をとる
    size = radius * 2 + pad * 2
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    dr = ImageDraw.Draw(img)
    dr.ellipse([pad, pad, pad + radius * 2, pad + radius * 2], fill=color + (alpha,))
    return img.filter(ImageFilter.GaussianBlur(radius * 0.38))


_SPRITES = {}


def particles(img, t):
    """光の粒をゆっくり漂わせる。同じ動画の中で位置が少しずつ変わる"""
    import random
    if "list" not in _SPRITES:
        rnd = random.Random(7)
        _SPRITES["s"] = [bokeh_sprite(r, a, c) for r, a, c in
                         ((150, 26, (255, 255, 255)), (110, 22, (255, 235, 240)),
                          (86, 20, (255, 214, 226)), (200, 16, (255, 255, 255)))]
        _SPRITES["list"] = [(rnd.random(), rnd.random(), rnd.randrange(4),
                             0.25 + rnd.random() * 0.7, rnd.random() * 6.28) for _ in range(11)]
    for (bx, by, si, speed, phase) in _SPRITES["list"]:
        sp = _SPRITES["s"][si]
        x = int(bx * W + 90 * math.sin(t * math.pi * speed + phase))
        y = int(by * H - t * H * 0.12 * speed - 60 * math.cos(t * math.pi * speed + phase)) % (H + 400) - 200
        img.paste(sp, (x - sp.width // 2, y - sp.height // 2), sp)
    return img


def ease_out(x):
    return 1 - (1 - x) ** 3


# ---------- 1枚ぶん ----------

def render_slide(lines, accent, fonts, out_dir, start_index, slide_no, slide_total):
    from PIL import ImageDraw
    mincho, thin = fonts
    lines = wrap(lines)
    longest = max(len(t) for t in lines)
    size = min(96, max(38, int(940 / longest)))
    font = mincho(size)
    eyebrow = thin(30)
    handle = thin(28)
    gap = int(size * 1.62)                       # 明朝は行間を広くとる
    base_y = 930 - (len(lines) - 1) * gap // 2

    total = IN_FRAMES + STAGGER * (len(lines) - 1) + HOLD + OUT_FRAMES
    idx = start_index
    for f in range(total):
        t = (slide_no - 1 + f / total) / slide_total
        img = particles(background(t), t)
        d = ImageDraw.Draw(img, "RGBA")

        # 金の細い枠（カードと同じ）
        d.rectangle([70, 70, W - 70, H - 70], outline=GOLD + (150,), width=2)

        # 上の小さな見出し
        d.text((W // 2, 250), "AIにやらせる女", font=eyebrow, fill=GOLD + (205,), anchor="mm")
        d.line([(W // 2 - 60, 292), (W // 2 + 60, 292)], fill=GOLD + (150,), width=1)

        # 本文：1行ずつ、下からゆっくり
        fade_out = 1.0
        if f >= total - OUT_FRAMES:
            fade_out = 1 - (f - (total - OUT_FRAMES)) / OUT_FRAMES
        for i, text in enumerate(lines):
            p = (f - i * STAGGER) / IN_FRAMES
            p = 0.0 if p < 0 else (1.0 if p > 1 else p)
            e = ease_out(p)
            alpha = int(255 * e * fade_out)
            if alpha <= 2:
                continue
            col = SAKURA if (accent and i == len(lines) - 1) else INK
            y = base_y + i * gap + int((1 - e) * 34)
            d.text((W // 2, y), text, font=font, fill=col + (alpha,), anchor="mm")

        # 下：アカウント名と、進み具合の線
        d.text((W // 2, H - 250), "@ai_woman01", font=handle, fill=MUTED + (215,), anchor="mm")
        bar_w, bx, by = 260, (W - 260) // 2, H - 200
        d.line([(bx, by), (bx + bar_w, by)], fill=GOLD + (60,), width=2)
        done = (slide_no - 1 + f / total) / slide_total
        d.line([(bx, by), (bx + int(bar_w * done), by)], fill=GOLD + (225,), width=2)

        img.save(os.path.join(out_dir, f"{idx:05d}.jpg"), quality=93)
        idx += 1
    return idx


def build_video(slides, out_path, workdir):
    from PIL import ImageFont
    import imageio_ffmpeg
    if os.path.isdir(workdir):
        shutil.rmtree(workdir)
    os.makedirs(workdir)
    bold_path, thin_path = pick(MINCHO_BOLD), pick(MINCHO_THIN)
    cache = {}

    def mincho(sz):
        return cache.setdefault(("b", sz), ImageFont.truetype(bold_path, sz))

    def thin(sz):
        return cache.setdefault(("t", sz), ImageFont.truetype(thin_path, sz))

    idx = 0
    for n, lines in enumerate(slides, start=1):
        idx = render_slide(lines, accent=(n == len(slides)), fonts=(mincho, thin),
                           out_dir=workdir, start_index=idx, slide_no=n, slide_total=len(slides))

    args = [imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-framerate", str(FPS),
            "-i", os.path.join(workdir, "%05d.jpg"),
            "-f", "lavfi", "-t", str(idx / FPS), "-i", "anullsrc=r=44100:cl=stereo",
            "-map", "0:v", "-map", "1:a",
            "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart", "-shortest", out_path]
    r = subprocess.run(args, capture_output=True, text=True)
    shutil.rmtree(workdir, ignore_errors=True)
    if r.returncode:
        raise SystemExit("動画にできませんでした: " + r.stderr[-400:])
    return idx / FPS


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    sample = "--sample" in sys.argv
    days_ahead = int(args[0]) if args else 14
    with open(SCHEDULE, encoding="utf-8") as f:
        sched = json.load(f)
    ids = {i["id"] for i in sched}
    today = dt.datetime.now(JST).date()
    limit = today + dt.timedelta(days=days_ahead)
    os.makedirs(IMAGES, exist_ok=True)
    workdir = os.path.join(HERE, "_reelwork")

    if sample:
        item = next(i for i in reversed(sched) if i["id"].endswith("-am"))
        out = os.path.join(IMAGES, "sample-reel.mp4")
        sec = build_video(to_slides(item["text"]), out, workdir)
        print(f"見本を作りました: {out}（{sec:.1f}秒）")
        return 0

    made = []
    for item in list(sched):
        if not item["id"].endswith("-am"):
            continue
        day = item["id"][:4]
        date = dt.date(today.year, int(day[:2]), int(day[2:]))
        if not (today <= date <= limit) or f"{day}-reel" in ids:
            continue
        slides = to_slides(item["text"])
        if len(slides) < 2:
            print(day, "スキップ（文が短い）"); continue
        name = f"{day}-reel.mp4"
        sec = build_video(slides, os.path.join(IMAGES, name), workdir)
        sched.append({"id": f"{day}-reel", "at": f"{date.isoformat()}T{POST_AT}",
                      "platforms": ["instagram"], "video": f"images/{name}",
                      "text": item["text"] + TAGS})
        made.append(name)
        print(f"作った: {name}（{sec:.1f}秒）")

    if made:
        sched.sort(key=lambda i: i["at"])
        with open(SCHEDULE, "w", encoding="utf-8") as f:
            json.dump(sched, f, ensure_ascii=False, indent=1)
    print(f"できたリール: {len(made)} 本")
    return 0


if __name__ == "__main__":
    sys.exit(main())
