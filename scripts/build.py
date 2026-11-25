"""把 debates/*.md 轉成 site/data.json 給網頁讀，順便重寫 README.md 的場次目錄。

用法：python3 scripts/build.py
格式解析失敗的場次會保留原文（raw），網頁照樣能顯示。
"""
import json
import pathlib
import re

from step import CONTROLS, QUOTAS, debate_path, load_control, plan_step, progress

ROOT = pathlib.Path(__file__).resolve().parent.parent
DEBATES = ROOT / "debates"
OUT = ROOT / "site" / "data.json"
README = ROOT / "README.md"

SPEAKER = re.compile(r"^\*\*(.+?)\*\*\s*[：:]\s*(.*)$")


SCORE_HEAD = re.compile(r"^### 評審打分(?:：正方 (\d+)｜反方 (\d+))?")
QUOTE = re.compile(r"^[-•＊*]\s*(正方|反方)\s*[（(]([^）)]*)[）)]\s*[：:]\s*「(.+)」\s*$")
VERDICT_NAMES = ("結算", "評審判決")


def parse(path: pathlib.Path) -> dict:
    """讀一場戰況。新舊格式都吃：
    新：## 立論／質詢…，發言 **正方｜立論**：…，打分 ### 評審打分：正方 8｜反方 7，最後 ## 評審判決
    舊：## 第 N 回合，發言 **正方**：…，最後 ## 主持人結算
    """
    text = path.read_text(encoding="utf-8").strip()
    lines = text.splitlines()
    stem = path.stem  # 2026-11-26_0226
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})_(\d{2})(\d{2})", stem)
    time = f"{m[1]}-{m[2]}-{m[3]} {m[4]}:{m[5]}" if m else stem

    title = ""
    sections = []
    current = None
    item = None  # 正在收文字的發言或打分

    for line in lines:
        s = line.rstrip()
        if not title and s.startswith("# "):
            title = s[2:].strip().strip("*「」\"")
            continue
        if s.startswith("## "):
            current = {"name": s[3:].strip(), "items": [], "text": []}
            sections.append(current)
            item = None
            continue
        if current is None:
            # 舊格式：標題下一行的粗體辯題
            t = s.strip().strip("*")
            if t and title in ("", "辯題"):
                title = t
            continue
        if any(v in current["name"] for v in VERDICT_NAMES):
            current["text"].append(s)
            continue
        sc = SCORE_HEAD.match(s)
        if sc:
            item = {"type": "score", "pro": int(sc[1]) if sc[1] else None,
                    "con": int(sc[2]) if sc[2] else None, "text": ""}
            current["items"].append(item)
            continue
        sm = SPEAKER.match(s.strip())
        if sm and ("｜" in sm[1] or len(sm[1]) <= 10):
            who, _, role = sm[1].partition("｜")
            item = {"type": "msg", "who": who.strip(), "role": role.strip(), "text": sm[2].strip()}
            current["items"].append(item)
        elif item is not None:
            item["text"] = (item["text"] + "\n" + s).strip()

    rounds = []
    for sec in sections:
        if any(v in sec["name"] for v in VERDICT_NAMES) or not sec["items"]:
            continue
        msgs = [{k: x[k] for k in ("who", "role", "text") if x.get(k)} for x in sec["items"] if x["type"] == "msg"]
        rounds.append({"name": sec["name"], "msgs": msgs, "items": sec["items"]})

    verdict_sec = next((sec for sec in sections if any(v in sec["name"] for v in VERDICT_NAMES)), None)
    verdict_lines = verdict_sec["text"] if verdict_sec else []
    quotes, rest = [], []
    for v in verdict_lines:
        q = QUOTE.match(v.strip())
        if q:
            quotes.append({"who": q[1], "stage": q[2].strip(), "text": q[3].replace("**", "").strip()})
        elif not re.match(r"^\s*關鍵發言\s*[：:]?\s*$", v):
            rest.append(v)
    verdict = "\n".join(rest).strip()
    winner = ""
    wm = re.search(r"勝者[^：:]*[：:]\s*\**\s*([A-Za-z一-鿿]+)", verdict)
    if wm:
        winner = wm[1]

    scores = [x for r in rounds for x in r["items"] if x["type"] == "score" and x["pro"] is not None]
    item = {"id": stem, "time": time, "title": title or "（未命名）", "rounds": rounds,
            "verdict": verdict, "winner": winner, "quotes": quotes,
            "totals": {"pro": sum(x["pro"] for x in scores), "con": sum(x["con"] for x in scores),
                       "n": len(scores)} if scores else None}
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
    # next：下一步（{"kind": "speech", "stage", "who", "role"}、score、verdict…），暫停時照「繼續」會做的算
    nxt = plan_step({**c, "cmd": "run" if c["cmd"] == "pause" else c["cmd"]})
    return {**c, "stage": p["stage"], "free": p["free"], "speeches": p["speeches"],
            "status": status, "next": nxt}


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
