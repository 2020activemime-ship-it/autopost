# 投稿記録（posted.json）を2つ合体する。
# 「どちらかに投稿済みの記録があれば、投稿済み」として残す。記録が消えて二重投稿になるのを防ぐため。
#   使い方: python merge_posted.py 手元の記録.json posted.json   （結果は posted.json に上書き）
import json
import sys


def load(path):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def ok(v):
    """投稿に成功した値か（投稿IDなど）。ERROR や空は失敗扱い"""
    return bool(v) and not str(v).startswith("ERROR")


def merge_item(a, b):
    ra, rb = a.get("results", {}), b.get("results", {})
    results = {}
    for k in set(ra) | set(rb):
        va, vb = ra.get(k), rb.get(k)
        if k == "skipped":
            results[k] = va or vb
        elif ok(va):
            results[k] = va
        elif ok(vb):
            results[k] = vb
        else:
            results[k] = va if va is not None else vb
    at = max(str(a.get("at", "")), str(b.get("at", "")))
    return {"at": at, "results": results}


def main():
    local_path, target_path = sys.argv[1], sys.argv[2]
    local, remote = load(local_path), load(target_path)
    merged = dict(remote)
    for key, item in local.items():
        merged[key] = merge_item(item, remote[key]) if key in remote else item
    with open(target_path, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)
    print(f"merge_posted: local={len(local)} remote={len(remote)} merged={len(merged)}")


if __name__ == "__main__":
    main()
