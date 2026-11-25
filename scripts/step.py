"""擂台的一步：讀 control.json，決定要打下一回合、做結算，還是什麼都不做。

control.json 只由網頁寫入，格式：
  {"id": "2026-11-26_153000", "topic": "辯題", "cmd": "run|pause|end", "max": 10}

用法：
  python3 scripts/step.py plan   印出 round / verdict / close / none
  python3 scripts/step.py run    執行這一步（round、verdict 會呼叫 claude）

每次只做一步。workflow 做完後再跑一次 plan，不是 none 就自己再觸發下一次，
所以「開始」會一回合接一回合打下去，直到暫停、結束或打滿回合上限。
"""
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

MAX_CAP = 30  # 回合上限的上限，避免無限打下去
ID_RE = re.compile(r"^\d{4}-\d{2}-\d{2}_\d{4,6}$")
ROUND_RE = re.compile(r"^## 第 \d+ 回合", re.M)
VERDICT_RE = re.compile(r"^## 主持人結算", re.M)


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
    return {"id": c["id"], "topic": topic, "cmd": cmd, "max": max(1, min(MAX_CAP, mx))}


def debate_path(c):
    return DEBATES / f"{c['id']}.md"


def progress(path):
    """回傳（已打幾回合, 是否已結算）。"""
    if not path.exists():
        return 0, False
    text = path.read_text(encoding="utf-8")
    return len(ROUND_RE.findall(text)), bool(VERDICT_RE.search(text))


def plan(c):
    if not c:
        return "none"
    rounds, ended = progress(debate_path(c))
    if ended:
        return "none"
    if c["cmd"] == "end":
        return "verdict" if rounds else "close"
    if c["cmd"] == "run":
        return "round" if rounds < c["max"] else "verdict"
    return "none"


def ask_claude(c, text, task):
    prompt = (
        f"{PROMPT.read_text(encoding='utf-8').strip()}\n\n---\n\n"
        f"辯題：{c['topic']}\n回合上限：{c['max']}\n\n"
        f"目前戰況：\n\n{text}\n\n---\n\n{task}"
    )
    cmd = os.environ.get("CLAUDE_BIN", "claude")
    r = subprocess.run([cmd, "-p", prompt], capture_output=True, text=True, timeout=300)
    out = r.stdout.strip()
    if r.returncode != 0 or not out:
        print("Claude 回報錯誤：", file=sys.stderr)
        print((out or r.stderr)[-2000:], file=sys.stderr)
        sys.exit(1)
    # 不管 Claude 有沒有自己加標題，標題一律由這裡寫
    lines = [s for s in out.splitlines() if not re.match(r"^#{1,6}\s", s)]
    return "\n".join(lines).strip()


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
    rounds, _ = progress(path)

    if action == "round":
        n = rounds + 1
        note = "，這是最後一回合，請做結辯" if n == c["max"] else ""
        task = (
            f"你的任務：只寫第 {n} 回合（共 {c['max']} 回合{note}）。"
            "格式固定兩段，正方先講：\n\n**正方**：……\n\n**反方**：……\n\n"
            "不要寫回合標題、前言或說明。"
        )
        body = ask_claude(c, text, task)
        text += f"\n\n## 第 {n} 回合\n\n{body}"
        print(f"打完第 {n} 回合")
    elif action == "verdict":
        task = "你的任務：以主持人身分結算這場辯論，照「主持人結算」的規則寫。不要寫標題或前言。"
        body = ask_claude(c, text, task)
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
