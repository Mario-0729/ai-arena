"""把 debates/*.md 轉成 site/data.json 給網頁讀，順便重寫 README.md 的場次目錄。

用法：python3 scripts/build.py
格式解析失敗的場次會保留原文（raw），網頁照樣能顯示。
"""
import json
import pathlib
import re

from step import CONTROLS, QUOTAS, debate_path, load_control, plan, progress

ROOT = pathlib.Path(__file__).resolve().parent.parent
DEBATES = ROOT / "debates"
OUT = ROOT / "site" / "data.json"
README = ROOT / "README.md"

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


def sort_key(stem):
    """2026-11-26_153000-2 排在 -10 前面；同一秒開的多場照編號排。"""
    m = re.match(r"(.+_\d+)(?:-(\d+))?$", stem)
    return (m[1], int(m[2] or 0)) if m else (stem, 0)


def live_status(c):
    """某一場的狀態（依它自己的控制檔）。"""
    p = progress(debate_path(c))
    if p["ended"]:
        status = "ended"
    else:
        status = {"run": "running", "pause": "paused", "end": "ending"}[c["cmd"]]
    # next：下一步是誰（pro 正方、con 反方、verdict 主持人結算、none 沒有）
    return {**c, "rounds": p["done"], "status": status, "next": plan(c)}


def load_quota():
    """每場各自存一份，取最新回報的那份。"""
    best = None
    for f in QUOTAS.glob("*.json"):
        try:
            q = json.loads(f.read_text(encoding="utf-8"))
        except ValueError:
            continue
        if isinstance(q, dict) and (best is None or str(q.get("at", "")) > str(best.get("at", ""))):
            best = q
    return best


STATUS_TEXT = {"ended": "", "running": "（進行中）", "paused": "（暫停）",
               "ending": "（結算中）", "stopped": "（中斷）"}


def write_readme(items):
    lines = ["# AI 吵架擂台", "", "站長在網頁出題，Claude 分成正方、反方自己吵，最新的在最上面。", ""]
    for d in items:
        lines.append(f"- [{d['id']}｜{d['title']}](debates/{d['id']}.md){STATUS_TEXT[d['status']]}")
    README.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    states = {}
    for f in CONTROLS.glob("*.json"):
        c = load_control(f.stem)
        if c:
            states[c["id"]] = live_status(c)
    # live：還沒結束的場次（剛按開始、還沒有戰況檔的也在裡面）
    live = sorted((s for s in states.values() if s["status"] != "ended"),
                  key=lambda s: sort_key(s["id"]), reverse=True)
    paths = sorted(DEBATES.glob("*.md"), key=lambda p: sort_key(p.stem), reverse=True)
    items = [parse(p) for p in paths]
    for d in items:
        st = states.get(d["id"])
        if st:
            d["status"], d["max"] = st["status"], st["max"]
        else:
            d["status"] = "ended" if d["verdict"] else "stopped"
    OUT.parent.mkdir(parents=True, exist_ok=True)
    data = {"live": live, "quota": load_quota(), "debates": items}
    OUT.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    write_readme(items)
    print(f"寫入 {OUT}，共 {len(items)} 場")


if __name__ == "__main__":
    main()
