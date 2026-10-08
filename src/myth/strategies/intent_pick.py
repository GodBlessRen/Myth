"""保守 Intent Pick 的纯规则策略。
仅严格有界算术与明确资料意图走确定路径，歧义回退 Agent；关键词命中不作为能力授权或通用语义证明。"""

from __future__ import annotations

import re
from typing import Any

from ..domains.information import IntentPick, IntentRoute


# _PREFIX：算术请求的明确文本入口；后续仍需 AST 安全求值。
_PREFIX = re.compile(
    r"^\s*(?:计算|算一下|算|calculate|calc)\s*[:：]?\s*", re.IGNORECASE
)
# _ALLOWED：当前策略/求值允许项；不引入额外执行权限。
_ALLOWED = re.compile(r"^[0-9eE+\-*/%().\s]+$")
# _BIN：有界算术允许的二元运算映射；拒绝任意函数、属性和执行代码。
_BIN = re.compile(r"[\d)]\s*(?:\*\*|[+\-*/%])\s*[\d(.+\-]")

# _STRONG_KNOWLEDGE_CUE：明确本地知识需求的规则线索；来源仍需固定。
_STRONG_KNOWLEDGE_CUE = re.compile(
    r"(?:知识库|附件|原文|出处|"
    r"根据.{0,16}(?:资料|文档|附件|知识库|原文)|"
    r"according\s+to.{0,16}(?:docs?|document|attachment|source)|"
    r"knowledge\s*base|attached\s+(?:file|document)|attachment)",
    re.IGNORECASE,
)
# _WEAK_KNOWLEDGE_CUE：模糊知识词线索；必须结合实际召回，不能单凭词碰撞改路由。
_WEAK_KNOWLEDGE_CUE = re.compile(
    r"(?:资料|文档|docs?|document|source|evidence|查(?:一下)?|搜索|检索)",
    re.IGNORECASE,
)

# 极保守的通识入口：仅无附件、无本地资料指向的简短介绍/定义问题。
# 这只是减少工具暴露的路由提案，不代表模型知识已经核实。
_GENERAL_QA = re.compile(
    r"^\s*(?:介绍(?:一下|下)?|简(?:单)?述|什么是|解释(?:一下)?|"
    r"introduce|what\s+is|explain)\s*[:：]?\s*[^\n]{2,100}[?？。.!！]?\s*$",
    re.IGNORECASE,
)
_LOCAL_REFERENCE = re.compile(
    r"(?:我(?:的|们的)|这个|这份|上述|上面|刚才|之前|文件|代码|仓库|项目|"
    r"附件|网页|链接|最新|今天|现在|昨天|目录|截图|文档|资料|"
    r"https?://|\.(?:pdf|docx?|xlsx?|md|py|js)\b)", re.IGNORECASE,
)


# 词面阈值由 foundation-v4 固定反例约束；改规则先提供评测证据，不能凭直觉调参。
# _WEAK_CUE_SCORE_THRESHOLD：词面召回阈值；这是规则尺度，不是任务价值或模型概率。
_WEAK_CUE_SCORE_THRESHOLD = 1.25


# 识别严格算术形状并排除日期/版本/百分比碰撞；识别通过仍须有界 AST 求值。
def _arithmetic_candidate(text: str) -> tuple[bool, str]:
    prefixed = bool(_PREFIX.match(text))
    candidate = _PREFIX.sub("", text, count=1).strip()
    if not (
        candidate
        and len(candidate) <= 200
        and _ALLOWED.fullmatch(candidate)
        and _BIN.search(candidate)
    ):
        return False, candidate

    # 缺少明确算术前缀时，斜杠/减号/百分号会与日期、版本、号码碰撞；加号、乘号和括号仅是更强形状线索，仍须 AST 求值。
    if not prefixed and not re.search(r"[+*(]", candidate):
        return False, candidate
    if candidate.rstrip().endswith("%"):
        return False, candidate
    return True, candidate


# 保守规则路由；严格算术可本地求值，明确本地资料走检索，否则回退通用循环。
class RuleIntentPicker:
    # strategy_id：组织策略身份；策略可替换而 Core 事实保持稳定。
    strategy_id = "intent_pick"

    # 从输入与已给上下文选择处理路径；输出是路由提案，具体准入与效果仍由 Runtime 控制。
    def pick(self, value: str, context: dict[str, Any]) -> IntentPick:
        text = str(value or "")
        arithmetic, candidate = _arithmetic_candidate(text)
        if arithmetic:
            return IntentPick(
                route=IntentRoute.DETERMINISTIC,
                objective="evaluate bounded arithmetic locally",
                confidence=1.0,
                reason="input satisfies the conservative arithmetic grammar",
                metadata={"kind": "bounded_arithmetic", "expression": candidate},
            )

        sources = tuple(context.get("sources") or ())
        attached = tuple(context.get("attached_document_ids") or ())
        top_score = max(
            (
                float(item.get("score") or 0.0)
                for item in sources
                if isinstance(item, dict)
            ),
            default=0.0,
        )
        strong = bool(attached) or bool(_STRONG_KNOWLEDGE_CUE.search(text))
        weak = bool(_WEAK_KNOWLEDGE_CUE.search(text))

        local_evidence = bool(sources) and (
            strong
            or top_score >= _WEAK_CUE_SCORE_THRESHOLD
            or (weak and top_score >= _WEAK_CUE_SCORE_THRESHOLD)
        )
        if not attached and not strong and not sources and _GENERAL_QA.fullmatch(text) and not _LOCAL_REFERENCE.search(text):
            return IntentPick(
                route=IntentRoute.DIRECT,
                objective="answer short general-knowledge question without tool discovery",
                reason="conservative standalone general-QA wording with no source-dependent cues",
                metadata={"kind": "general_qa"},
            )

        if local_evidence:
            return IntentPick(
                route=IntentRoute.LOCAL_RETRIEVAL,
                objective="ground the response in admitted local knowledge before general reasoning",
                confidence=(1.0 if strong else min(0.99, top_score / 2.0)),
                reason=(
                    "user explicitly requested admitted local/source evidence"
                    if strong
                    else "local lexical retrieval produced a strong source match"
                ),
                metadata={
                    "kind": "local_knowledge",
                    "source_count": len(sources),
                    "top_score": round(top_score, 3),
                    "strong_source_request": strong,
                    "weak_source_cue": weak,
                    "score_threshold": _WEAK_CUE_SCORE_THRESHOLD,
                },
            )

        return IntentPick(
            route=IntentRoute.AGENT,
            objective="continue through the general conversation agent",
            reason="no conservative deterministic or local-retrieval route matched",
        )
