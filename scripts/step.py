"""擂台的一步：讀 control.json，決定下一個要發言的是誰，或做結算，或什麼都不做。

control.json 只由網頁寫入，格式：
  {"id": "2026-11-26_153000", "topic": "辯題", "cmd": "run|pause|end", "max": 10}
  max 是回合上限；0 代表無限，打到按「結束」為止。

用法：
  python3 scripts/step.py plan   印出 pro / con / verdict / close / none
  python3 scripts/step.py run    執行這一步（pro、con、verdict 會呼叫 claude）

一步只有一個人發言（正方或反方），所以網頁可以一句一句看到。
workflow 做完後再跑一次 plan，不是 none 就自己再觸發下一次。
"""
import datetime
import json
import os
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
CONTROL = ROOT / "control.json"
DEBATES = ROOT / "debates"
PROMPT = ROOT / "prompt.md"
QUOTA = ROOT / "quota.json"

MAX_CAP = 30          # 有上限時，上限最多 30 回合
UNLIMITED_SAFETY = 200  # 無限模式的保險：真的打到 200 回合就自動結算
CONTEXT_ROUNDS = 6    # 發言時只給 Claude 看最近幾回合，避免越打越慢、越耗額度
ID_RE = re.compile(r"^\d{4}-\d{2}-\d{2}_\d{4,6}$")
ROUND_HEAD = re.compile(r"^## 第 (\d+) 回合\s*$", re.M)
VERDICT_RE = re.compile(r"^## 主持人結算", re.M)
SIDE = {"pro": "正方", "con": "反方"}


def load_control():
    """讀 control.json，格式不對就當作沒有。"""
    try:
        c = json.loads(CONTROL.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return None
    if not isinstance(c, dict) or not ID_RE.match(str(c.get("id", ""))):
        return None
    topic = " ".join(str(c.get("topic", "")).split())[:200]
    if not topic:
        return None
    cmd = c.get("cmd") if c.get("cmd") in ("run", "pause", "end") else "pause"
    try:
        mx = int(c.get("max", 10))
    except (TypeError, ValueError):
        mx = 10
    mx = 0 if mx <= 0 else min(MAX_CAP, mx)
    return {"id": c["id"], "topic": topic, "cmd": cmd, "max": mx}


def debate_path(c):
    return DEBATES / f"{c['id']}.md"


def progress(path):
    """回傳戰況：已完成幾回合、最後一回合誰講過、有沒有結算。"""
    p = {"done": 0, "last": 0, "pro": False, "con": False, "ended": False}
    if not path.exists():
        return p
    text = path.read_text(encoding="utf-8")
    p["ended"] = bool(VERDICT_RE.search(text))
    heads = list(ROUND_HEAD.finditer(text))
    if heads:
        last = text[heads[-1].end():]
        last = VERDICT_RE.split(last)[0]
        p["last"] = len(heads)
        p["pro"] = "**正方**" in last
        p["con"] = "**反方**" in last
        p["done"] = len(heads) if p["con"] else len(heads) - 1
    return p


def plan(c):
    if not c:
        return "none"
    p = progress(debate_path(c))
    if p["ended"]:
        return "none"
    if c["cmd"] == "end":
        return "verdict" if p["last"] else "close"
    if c["cmd"] != "run":
        return "none"
    if p["last"] and p["pro"] and not p["con"]:
        return "con"
    limit = c["max"] or UNLIMITED_SAFETY
    return "verdict" if p["done"] >= limit else "pro"


def context_for_speech(text):
    """只留題目和最近幾回合。"""
    heads = list(ROUND_HEAD.finditer(text))
    if len(heads) <= CONTEXT_ROUNDS:
        return text
    cut = heads[-CONTEXT_ROUNDS].start()
    skipped = len(heads) - CONTEXT_ROUNDS
    return text.splitlines()[0] + f"\n\n（前面 {skipped} 回合省略）\n\n" + text[cut:]


def context_for_verdict(text, limit=60000):
    if len(text) <= limit:
        return text
    return text[:4000] + "\n\n（中間省略）\n\n" + text[-(limit - 4000):]


def save_quota(info):
    """把 Claude 回報的額度狀態存起來，網頁會顯示。沒回報就保留上一次的。"""
    if not info:
        return
    now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8)))
    QUOTA.write_text(json.dumps({"at": now.strftime("%Y-%m-%d %H:%M"), "info": info},
                                ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def ask_claude(c, context, task):
    prompt = (
        f"{PROMPT.read_text(encoding='utf-8').strip()}\n\n---\n\n"
        f"辯題：{c['topic']}\n"
        f"回合上限：{c['max'] or '無限（站長按結束才停）'}\n\n"
        f"目前戰況：\n\n{context}\n\n---\n\n{task}"
    )
    cmd = os.environ.get("CLAUDE_BIN", "claude")
    r = subprocess.run([cmd, "-p", prompt, "--output-format", "stream-json", "--verbose"],
                       capture_output=True, text=True, timeout=300)
    result, info = None, None
    for line in r.stdout.splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if ev.get("type") == "rate_limit_event" and isinstance(ev.get("rate_limit_info"), dict):
            info = ev["rate_limit_info"]
        elif ev.get("type") == "result":
            result = ev
    save_quota(info)
    out = (result or {}).get("result")
    if r.returncode != 0 or not result or result.get("is_error") or not isinstance(out, str) or not out.strip():
        print("Claude 回報錯誤：", file=sys.stderr)
        detail = {k: (result or {}).get(k) for k in ("subtype", "result", "errors")}
        print(json.dumps(detail, ensure_ascii=False)[:2000] if result else r.stderr[-2000:], file=sys.stderr)
        sys.exit(1)
    # 標題和「正方：」由程式寫，Claude 如果自己加了就拿掉
    lines = [s for s in out.strip().splitlines() if not re.match(r"^#{1,6}\s", s)]
    body = "\n".join(lines).strip()
    body = re.sub(r"^\**(正方|反方|主持人)\**\s*[：:]\s*", "", body)
    return body.strip()


def run(c):
    action = plan(c)
    if action == "none":
        print("沒有要做的事")
        return
    DEBATES.mkdir(exist_ok=True)
    path = debate_path(c)
    if not path.exists():
        path.write_text(f"# {c['topic']}\n", encoding="utf-8")
    text = path.read_text(encoding="utf-8").rstrip()
    p = progress(path)

    if action in ("pro", "con"):
        n = p["last"] + 1 if action == "pro" else p["last"]
        who = SIDE[action]
        if c["max"] and n == c["max"]:
            stage = f"第 {n} 回合，也是最後一回合，請做結辯"
        elif n == 1:
            stage = "第 1 回合，請立論"
        else:
            stage = f"第 {n} 回合"
        if c["max"]:
            stage += f"（共 {c['max']} 回合）"
        if action == "pro":
            stage += "。你先講"
        else:
            stage += "。正方剛講完，請先回應他這回合的說法"
        task = f"你的任務：以「{who}」身分發言。現在是{stage}。只寫{who}這一段話本身，不要寫名字、標題、前言或說明。"
        body = ask_claude(c, context_for_speech(text), task)
        if action == "pro":
            text += f"\n\n## 第 {n} 回合\n\n**正方**：{body}"
        else:
            text += f"\n\n**反方**：{body}"
        print(f"第 {n} 回合 {who} 發言完畢")
    elif action == "verdict":
        task = "你的任務：以主持人身分結算這場辯論，照「主持人結算」的規則寫。不要寫標題或前言。"
        body = ask_claude(c, context_for_verdict(text), task)
        text += f"\n\n## 主持人結算\n\n{body}"
        print("結算完成")
    else:  # close：還沒開打就按結束
        text += "\n\n## 主持人結算\n\n還沒開打就結束了，不判勝負。"
        print("沒開打就結束")

    path.write_text(text + "\n", encoding="utf-8")


def main():
    what = sys.argv[1] if len(sys.argv) > 1 else ""
    c = load_control()
    if what == "plan":
        print(plan(c))
    elif what == "run":
        run(c)
    else:
        print(__doc__)
        sys.exit(2)


if __name__ == "__main__":
    main()
