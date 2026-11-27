"""擂台的一步：讀某一場的控制檔和戰況，決定下一步，或什麼都不做。

賽制（參考華語辯論常見的奧瑞岡式）：
  1. 立論：正方、反方
  2. 質詢：反方提問、正方回答、正方提問、反方回答
  3. 駁論：正方、反方
  4. 自由辯論：正方、反方一來一回，共 max 來回（max 為 0 就一直打到按結束）
  5. 結辯：反方先、正方最後
  6. 評審判決：勝負、理由、逐字引用關鍵發言
  每個階段講完，評審打一次分（各 1～10 分）；自由辯論每 5 來回也打一次。
  按「結束」：目前階段還沒打分就先打分，接著雙方結辯，最後判決。

每一場有自己的控制檔 controls/<id>.json，只由網頁寫入：
  {"id": "2026-11-26_153000-1", "topic": "辯題", "cmd": "run|pause|end|stop", "max": 3}
  stop 是放棄：不再打、不判決，網頁顯示「中斷」。

用法：
  python3 scripts/step.py plan <id>   印出下一步的種類：speech / score / verdict / close / none
  python3 scripts/step.py run <id>    執行這一步（speech、score、verdict 會呼叫 claude）

每一場只寫自己的檔案（debates/<id>.md、quota/<id>.json），很多場同時打也不會互相蓋掉。
"""
import datetime
import json
import os
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
CONTROLS = ROOT / "controls"
DEBATES = ROOT / "debates"
PROMPT = ROOT / "prompt.md"
QUOTAS = ROOT / "quota"

MAX_CAP = 30            # 自由辯論來回數上限（有上限時）
UNLIMITED_SAFETY = 200  # 無限模式的保險：自由辯論打到 200 來回就自動進結辯
SCORE_EVERY = 5         # 自由辯論每幾來回打一次分
ID_RE = re.compile(r"^\d{4}-\d{2}-\d{2}_\d{4,6}(-\d{1,2})?$")

STAGES = ["立論", "質詢", "駁論", "自由辯論", "結辯"]
# 各階段固定的發言順序（自由辯論另外處理）
ORDER = {
    "立論": [("正方", "立論"), ("反方", "立論")],
    "質詢": [("反方", "提問"), ("正方", "回答"), ("正方", "提問"), ("反方", "回答")],
    "駁論": [("正方", "駁論"), ("反方", "駁論")],
    "結辯": [("反方", "結辯"), ("正方", "結辯")],
}
STAGE_RE = re.compile(r"^## (立論|質詢|駁論|自由辯論|結辯|評審判決)\s*$")
SPEECH_RE = re.compile(r"^\*\*(正方|反方)｜([^*]+)\*\*：")
SCORE_RE = re.compile(r"^### 評審打分")


def load_control(cid):
    """讀 controls/<id>.json，id 或格式不對就當作沒有。"""
    if not ID_RE.match(str(cid or "")):
        return None
    try:
        c = json.loads((CONTROLS / f"{cid}.json").read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return None
    if not isinstance(c, dict) or c.get("id") != cid:
        return None
    topic = " ".join(str(c.get("topic", "")).split())[:200]
    if not topic:
        return None
    # stop：放棄這場，不再打也不判決（卡住時用，不花額度）
    cmd = c.get("cmd") if c.get("cmd") in ("run", "pause", "end", "stop") else "pause"
    try:
        mx = int(c.get("max", 3))
    except (TypeError, ValueError):
        mx = 3
    mx = 0 if mx <= 0 else min(MAX_CAP, mx)
    return {"id": c["id"], "topic": topic, "cmd": cmd, "max": mx}


def debate_path(c):
    return DEBATES / f"{c['id']}.md"


def read_log(path):
    """把戰況檔讀成事件清單：[(stage, kind, who, role)]，kind 是 speech 或 score。"""
    log, stage, ended, legacy = [], None, False, False
    if not path.exists():
        return log, ended, legacy
    for line in path.read_text(encoding="utf-8").splitlines():
        m = STAGE_RE.match(line)
        if m:
            stage = m[1]
            ended = ended or stage == "評審判決"
            continue
        if line.startswith("## 主持人結算"):  # 舊版格式
            ended = True
        if line.startswith("## 第 "):
            legacy = True
        m = SPEECH_RE.match(line)
        if m and stage:
            log.append((stage, "speech", m[1], m[2].strip()))
        elif SCORE_RE.match(line) and stage:
            log.append((stage, "score", None, None))
    return log, ended, legacy


def summarize(log):
    """目前階段、這階段講了幾段、最後一次打分後講了幾段、自由辯論完成幾來回。"""
    stage = log[-1][0] if log else None
    in_stage = [e for e in log if e[0] == stage]
    speeches = [e for e in in_stage if e[1] == "speech"]
    since = 0
    for e in in_stage:
        since = 0 if e[1] == "score" else since + 1
    return stage, speeches, since


def next_step(c, log):
    """回傳下一步 dict，或 None。"""
    stage, speeches, unscored = summarize(log)
    limit = c["max"] or UNLIMITED_SAFETY

    def speech(st, who, role, n=None):
        return {"kind": "speech", "stage": st, "who": who, "role": role, "n": n}

    def first_of(st):
        if st == "自由辯論":
            return speech("自由辯論", "正方", "第 1 來回", 1)
        who, role = ORDER[st][0]
        return speech(st, who, role)

    if c["cmd"] == "end" and stage != "結辯":
        if not log:
            return {"kind": "close"}
        if unscored:
            return {"kind": "score", "stage": stage}
        return first_of("結辯")

    if not log:
        return first_of("立論")

    if stage == "自由辯論":
        done = sum(1 for e in speeches if e[2] == "反方")
        if speeches[-1][2] == "正方":
            return speech("自由辯論", "反方", f"第 {done + 1} 來回", done + 1)
        if unscored and (done % SCORE_EVERY == 0 or done >= limit):
            return {"kind": "score", "stage": stage}
        if done < limit:
            return speech("自由辯論", "正方", f"第 {done + 1} 來回", done + 1)
        return first_of("結辯")

    order = ORDER[stage]
    if len(speeches) < len(order):
        who, role = order[len(speeches)]
        return speech(stage, who, role)
    if unscored:
        return {"kind": "score", "stage": stage}
    if stage == "結辯":
        return {"kind": "verdict"}
    return first_of(STAGES[STAGES.index(stage) + 1])


def plan_step(c):
    if not c:
        return None
    log, ended, legacy = read_log(debate_path(c))
    if ended or legacy:
        return None
    if c["cmd"] in ("pause", "stop"):
        return None
    return next_step(c, log)


def plan(c):
    s = plan_step(c)
    return s["kind"] if s else "none"


def progress(path):
    """給網頁看的進度。"""
    log, ended, legacy = read_log(path)
    stage, _, _ = summarize(log)
    free = sum(1 for e in log if e[0] == "自由辯論" and e[1] == "speech" and e[2] == "反方")
    return {"ended": ended, "stage": stage, "free": free,
            "speeches": sum(1 for e in log if e[1] == "speech")}


# ---------- 給 Claude 看的內容 ----------

def blocks(text):
    """把戰況切成段落（每段發言、每次打分各一塊），保留所屬階段。"""
    out, stage, cur = [], None, None
    for line in text.splitlines():
        m = STAGE_RE.match(line)
        if m:
            stage, cur = m[1], None
            continue
        if SPEECH_RE.match(line) or SCORE_RE.match(line):
            cur = {"stage": stage, "lines": [line]}
            out.append(cur)
        elif cur is not None:
            cur["lines"].append(line)
    return out


def render_blocks(bs):
    out, stage = [], None
    for b in bs:
        if b["stage"] != stage:
            stage = b["stage"]
            out.append(f"## {stage}")
        out.append("\n".join(b["lines"]).strip())
    return "\n\n".join(out)


def context_for_speech(text, keep=10):
    """立論全文（雙方記得自己的立場）＋最近幾段。"""
    bs = [b for b in blocks(text) if not SCORE_RE.match(b["lines"][0])]
    head = [b for b in bs if b["stage"] == "立論"]
    tail = [b for b in bs[len(head):]][-keep:]
    skipped = len(bs) - len(head) - len(tail)
    mid = f"\n\n（中間省略 {skipped} 段）\n\n" if skipped > 0 else "\n\n"
    return render_blocks(head) + mid + render_blocks(tail)


def context_for_score(text, stage):
    bs = blocks(text)
    # 這個階段最後一次打分之後的發言
    last = [i for i, b in enumerate(bs) if b["stage"] == stage and SCORE_RE.match(b["lines"][0])]
    start = last[-1] + 1 if last else 0
    part = [b for b in bs[start:] if b["stage"] == stage]
    return render_blocks(part)


def context_for_verdict(text, limit=60000):
    if len(text) <= limit:
        return text
    return text[:6000] + "\n\n（中間省略）\n\n" + text[-(limit - 6000):]


def totals(text):
    pro = con = 0
    for m in re.finditer(r"^### 評審打分.*?正方 (\d+)｜反方 (\d+)", text, re.M):
        pro += int(m[1])
        con += int(m[2])
    return pro, con


# ---------- 呼叫 Claude ----------

def save_quota(c, info):
    """把 Claude 回報的額度狀態存在這一場自己的檔案，網頁取最新的一份顯示。"""
    if not info:
        return
    now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8)))
    QUOTAS.mkdir(exist_ok=True)
    (QUOTAS / f"{c['id']}.json").write_text(
        json.dumps({"at": now.strftime("%Y-%m-%d %H:%M:%S"), "info": info}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")


def ask_claude(c, context, task):
    prompt = (
        f"{PROMPT.read_text(encoding='utf-8').strip()}\n\n---\n\n"
        f"辯題：{c['topic']}\n"
        f"自由辯論來回數：{c['max'] or '無限（站長按結束才停）'}\n\n"
        f"目前戰況：\n\n{context or '（還沒開始）'}\n\n---\n\n{task}"
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
    save_quota(c, info)
    out = (result or {}).get("result")
    if r.returncode != 0 or not result or result.get("is_error") or not isinstance(out, str) or not out.strip():
        print("Claude 回報錯誤：", file=sys.stderr)
        detail = {k: (result or {}).get(k) for k in ("subtype", "result", "errors")}
        print(json.dumps(detail, ensure_ascii=False)[:2000] if result else r.stderr[-2000:], file=sys.stderr)
        sys.exit(1)
    # 標題由程式寫，Claude 如果自己加了就拿掉
    lines = [s for s in out.strip().splitlines() if not re.match(r"^#{1,6}\s", s)]
    return "\n".join(lines).strip()


def clean_speech(body):
    # 名字由程式寫，Claude 如果自己加了「正方：」就拿掉
    return re.sub(r"^\**(正方|反方|評審|主持人)[^：:\n]{0,8}\**\s*[：:]\s*", "", body).strip()


def parse_score(body):
    """評審打分固定格式：正方：8／反方：7／講評：……"""
    pro = re.search(r"正方[^0-9\n]{0,6}(\d{1,2})", body)
    con = re.search(r"反方[^0-9\n]{0,6}(\d{1,2})", body)
    note = re.search(r"講評\s*[：:]\s*(.+)", body, re.S)
    if not (pro and con):
        return None
    clamp = lambda v: max(1, min(10, int(v)))
    return clamp(pro[1]), clamp(con[1]), (note[1].strip() if note else "")


STAGE_HINT = {
    ("立論", "立論"): "完整申論你的立場：定義關鍵詞、提出兩到三個主要論點。",
    ("質詢", "提問"): "向對方提出兩到三個尖銳、具體的問題，每題一行，用「問：」開頭。不要自己回答。",
    ("質詢", "回答"): "逐一回答對方剛才的提問，每題用「答：」開頭，簡潔直接，可以順勢反將一軍。",
    ("駁論", "駁論"): "針對對方立論和質詢中的漏洞逐點反駁，並補強自己的論點。",
    ("結辯", "結辯"): "總結全場：指出雙方真正的分歧、你方為何勝出，最後一句要有力。不能提出全新論點。",
}


def run(c):
    s = plan_step(c)
    if not s:
        print("沒有要做的事")
        return
    DEBATES.mkdir(exist_ok=True)
    path = debate_path(c)
    if not path.exists():
        path.write_text(f"# {c['topic']}\n", encoding="utf-8")
    text = path.read_text(encoding="utf-8").rstrip()
    log, _, _ = read_log(path)
    cur_stage = log[-1][0] if log else None

    if s["kind"] == "speech":
        hint = STAGE_HINT.get((s["stage"], s["role"]),
                              "快速交鋒：先正面回應對方剛才那段，再補一刀。100 字以內。")
        task = (f"你的任務：以「{s['who']}」身分，在「{s['stage']}」階段發言（{s['role']}）。{hint}"
                f"只寫{s['who']}這一段話本身，不要寫名字、標題、前言或說明。")
        body = clean_speech(ask_claude(c, context_for_speech(text), task))
        head = f"\n\n## {s['stage']}" if s["stage"] != cur_stage else ""
        text += f"{head}\n\n**{s['who']}｜{s['role']}**：{body}"
        print(f"{s['stage']} {s['who']}（{s['role']}）發言完畢")

    elif s["kind"] == "score":
        task = (f"你的任務：以評審身分，為剛才「{s['stage']}」階段（只看上面這段）的雙方表現打分，各 1 到 10 分。"
                "只輸出下面三行，不要其他文字：\n正方：分數\n反方：分數\n講評：一到兩句，點出這階段誰的哪一招最有效")
        got = parse_score(ask_claude(c, context_for_score(text, s["stage"]), task))
        if got:
            pro, con, note = got
            text += f"\n\n### 評審打分：正方 {pro}｜反方 {con}\n\n{note}".rstrip()
        else:
            text += "\n\n### 評審打分\n\n（評審這次沒有照格式給分）"
        print(f"{s['stage']} 打分完畢")

    elif s["kind"] == "verdict":
        pro, con = totals(text)
        task = (f"你的任務：以評審身分做最後判決。各階段打分加總：正方 {pro} 分、反方 {con} 分。"
                "照「評審判決」的規則寫，引用的句子必須從上面發言裡一字不差地複製。")
        body = ask_claude(c, context_for_verdict(text), task)
        text += f"\n\n## 評審判決\n\n{body}"
        print("判決完成")

    else:  # close：還沒開打就按結束
        text += "\n\n## 評審判決\n\n還沒開打就結束了，不判勝負。"
        print("沒開打就結束")

    path.write_text(text + "\n", encoding="utf-8")


def main():
    what = sys.argv[1] if len(sys.argv) > 1 else ""
    c = load_control(sys.argv[2] if len(sys.argv) > 2 else "")
    if what == "plan":
        print(plan(c))
    elif what == "run":
        run(c)
    else:
        print(__doc__)
        sys.exit(2)


if __name__ == "__main__":
    main()
