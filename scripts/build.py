"""把 debates/*.md 轉成 site/data.json，給網頁讀。

用法：python3 scripts/build.py
格式解析失敗的場次會保留原文（raw），網頁照樣能顯示。
"""
import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
DEBATES = ROOT / "debates"
OUT = ROOT / "site" / "data.json"

SPEAKER = re.compile(r"^\*\*(.+?)\*\*\s*[：:]\s*(.*)$")


def parse(path: pathlib.Path) -> dict:
    text = path.read_text(encoding="utf-8").strip()
    lines = text.splitlines()
    stem = path.stem  # 2026-11-26_0226
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})_(\d{2})(\d{2})", stem)
    time = f"{m[1]}-{m[2]}-{m[3]} {m[4]}:{m[5]}" if m else stem

    title = ""
    sections = []
    current = None
    msg = None

    for line in lines:
        s = line.rstrip()
        if not title and s.startswith("# "):
            title = s[2:].strip().strip("*「」\"")
            continue
        if s.startswith("## "):
            current = {"name": s[3:].strip(), "msgs": [], "text": []}
            sections.append(current)
            msg = None
            continue
        if current is None:
            # 舊格式：標題下一行的粗體辯題
            t = s.strip().strip("*")
            if t and title in ("", "辯題"):
                title = t
            continue
        sm = SPEAKER.match(s.strip())
        if sm and "結算" not in current["name"]:
            msg = {"who": sm[1].strip(), "text": sm[2].strip()}
            current["msgs"].append(msg)
        elif msg is not None:
            msg["text"] = (msg["text"] + "\n" + s).strip()
        else:
            current["text"].append(s)

    rounds = [
        {"name": sec["name"], "msgs": sec["msgs"]}
        for sec in sections
        if sec["msgs"] and "結算" not in sec["name"]
    ]
    verdict_sec = next((sec for sec in sections if "結算" in sec["name"]), None)
    verdict = "\n".join(verdict_sec["text"]).strip() if verdict_sec else ""
    winner = ""
    wm = re.search(r"勝者[^：:]*[：:]\s*\**\s*([A-Za-z一-鿿]+)", verdict)
    if wm:
        winner = wm[1]

    item = {"id": stem, "time": time, "title": title or "（未命名）", "rounds": rounds,
            "verdict": verdict, "winner": winner}
    if not rounds:
        item["raw"] = text
    return item


def main():
    items = [parse(p) for p in sorted(DEBATES.glob("*.md"), reverse=True)]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"debates": items}, ensure_ascii=False), encoding="utf-8")
    print(f"寫入 {OUT}，共 {len(items)} 場")


if __name__ == "__main__":
    main()
