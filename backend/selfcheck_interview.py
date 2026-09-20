"""面试模块自检：题量计划推进、已问题目提取、风格常量、复盘约束文案。

离线运行，不调用模型、不花钱。
用法（backend 目录）：.\.venv\Scripts\python.exe selfcheck_interview.py
"""
import io
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from app.ai import (  # noqa: E402
    INTERVIEW_PERSONAS, INTERVIEW_PLAN, INTERVIEW_STAGE_LABELS, INTERVIEW_STYLES,
    ChatMessage, InterviewReviewRequest, InterviewTurnRequest, _asked_questions,
    _interview_advance, _interview_progress, _interview_system,
)

ok_all = True


def check(name: str, cond: bool, detail: str = "") -> None:
    global ok_all
    ok_all &= cond
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f" → {detail}" if detail else ""))


def main() -> int:
    # ① 12 题计划推进：从第 1 题一路走到 done
    stage, rnd = "intro", 1
    seq = []
    for _ in range(20):
        seq.append((stage, rnd))
        stage, rnd = _interview_advance(stage, rnd)
        if stage == "done":
            break
    total = sum(c for _, c in INTERVIEW_PLAN)
    check("题量计划总数=12", total == 12, f"{INTERVIEW_PLAN} → {total}")
    check("推进不重复不跳阶", len(seq) == total and seq[0] == ("intro", 1), f"共 {len(seq)} 步，末题 {seq[-1]}")
    check("走完进入 done", stage == "done")
    stages_in_order = [s for s, _ in seq]
    order_ok = stages_in_order == sorted(stages_in_order, key=lambda s: [k for k, _ in INTERVIEW_PLAN].index(s))
    check("阶段顺序正确", order_ok, " → ".join(dict.fromkeys(stages_in_order)))

    # ② 进度字符串
    check("进度格式 N / 12", _interview_progress("intro", 1) == "1 / 12", _interview_progress("intro", 1))
    check("进度末尾=12 / 12", _interview_progress("ask", 1) == "12 / 12", _interview_progress("ask", 1))

    # ③ 已问题目提取（用于硬性禁止重复提问）
    history = [
        ChatMessage(role="assistant", content="【点评】不错。\n【提问】500 万增量具体拆到哪几块？"),
        ChatMessage(role="user", content="……"),
        ChatMessage(role="assistant", content="【提问】7 家百万门店挑一家讲动作。"),
        ChatMessage(role="assistant", content="【点评】再补一层。\n【提问】7 家百万门店选店、动作、周期？"),
    ]
    asked = _asked_questions(history)
    check("提取已问问题 3 条", len(asked) == 3, " ｜ ".join(asked))
    check("多选题也能提取到最后一条", "周期" in asked[-1], asked[-1])

    # ④ 风格常量与提示词注入
    check("三种面试官风格", set(INTERVIEW_STYLES) == {"standard", "pragmatic", "stress"})
    req = InterviewTurnRequest(provider_id="x", history=history, style="pragmatic", role_persona="region_director")
    sys_prompt = _interview_system(req)
    for kw, label in [
        ("追问配额", "追问配额规则"),
        ("最多**连续追问 2 次**", "配额数值"),
        ("口径", "口径优先规则"),
        ("不纠缠数字口径", "务实风格生效"),
        ("已经问过的问题", "已问清单注入"),
        ("严禁重复问同样的角度", "禁止重复"),
        ("跳过", "情绪/暂停处理"),
    ]:
        check(f"提示词含「{label}」", kw in sys_prompt)
    ask_req = InterviewTurnRequest(provider_id="x", stage="ask", style="standard")
    check("反问环节有作答边界规则", "可以直接回答" in _interview_system(ask_req))

    # ⑤ 复盘约束：不得人格评判 + 未进行不计分 + 面试官评估节
    from app.ai import INTERVIEW_REVIEW_SYSTEM  # noqa: E402
    for kw, label in [
        ("人格评判", "禁止人格评判"),
        ("面试官的提问是否专业", "评估面试官"),
        ("让人泄气", "禁止丧气结论"),
    ]:
        check(f"复盘系统提示词含「{label}」", kw in INTERVIEW_REVIEW_SYSTEM)
    check("复盘请求可带风格", "style" in InterviewReviewRequest.model_fields)
    check("回合请求可带风格", "style" in InterviewTurnRequest.model_fields)

    # ⑥ 四个人格齐全
    check("四种面试官人格", set(INTERVIEW_PERSONAS) == {"hr", "region_director", "boss", "stress"})
    check("阶段中文标签齐全", set(INTERVIEW_STAGE_LABELS) >= {s for s, _ in INTERVIEW_PLAN} | {"done"})

    print(f"\n结果：{'全部通过' if ok_all else '存在失败项'}")
    return 0 if ok_all else 1


if __name__ == "__main__":
    raise SystemExit(main())
