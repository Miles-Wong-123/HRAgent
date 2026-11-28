# backend/agents/resume/nodes.py

#  0 导包
import asyncio
import hashlib
from pathlib import Path

import fitz

from langchain_core.messages import HumanMessage, SystemMessage
from backend.config import get_settings

from backend.agents.resume.state import (
    ResumeState, ResumeStructured, DimensionScore, IssueList, ResumeSummary,
)
from backend.agents.resume.prompts import (
    SYSTEM_PROMPT, EXTRACT_STRUCTURED_PROMPT, DIMENSION_REVIEW_PROMPT,
    DIAGNOSE_ISSUES_PROMPT, GENERATE_SUMMARY_PROMPT, DIAGNOSE_THINK_PROMPT,
)
from backend.core.llm_factory import get_structured_llm, get_llm
from backend.core.logger import get_logger

#  1 准备工作
logger = get_logger(__name__)

# 六维度定义（名称 / 权重 / 评分侧重）。权重之和 = 1.0
SIX_DIMENSIONS = [
    {
        "key":    "project_depth",
        "name":   "项目深度",
        "weight":  0.30,
        "focus":  "项目描述是否有量化数据、方案选择理由、个人贡献、难点解决"
    },
    {
        "key":    "tech_match",
        "name":   "技术匹配度",
        "weight":  0.25,
        "focus":  "按选定 JD 的必备与优先条件核对专业技能、工具与实际应用；适用于技术及非技术岗位"
    },
    {
        "key":     "expression",
        "name":    "表达规范性",
        "weight":  0.15,
        "focus":   "动词开头、STAR 结构、无错别字、无主语省略歧义"
    },
    {
        "key":    "structure",
        "name":   "简历结构",
        "weight":  0.15,
        "focus":  "模块完整性、排版逻辑、信息密度、重要内容是否放前面"
    },
    {
        "key":    "quantification",
        "name":   "量化程度",
        "weight":  0.10,
        "focus":  "与岗位相关的规模、数量、转化率、成本或效果指标的使用情况"},
    {
        "key":    "authenticity",
        "name":   "真实可信度",
        "weight":  0.05,
        "focus":  "核对时间线、职责、成果和数字的内部一致性，指出有原文依据的矛盾与待核实处；不得据此推断诚信或认定造假"},
]

class ResumeError(Exception):
    """返回给 HR 的业务错误。"""


async def extract_text_node(state: ResumeState) -> dict:
    return await asyncio.to_thread(_sync_extract_text, state["storage_key"], state["file_sha256"])


def _sync_extract_text(storage_key: str, file_sha256: str) -> dict:
    root = get_settings().upload_dir
    path = (root / storage_key).resolve()
    if Path(storage_key).is_absolute() or not path.is_relative_to(root / "resumes"):
        raise ResumeError("简历存储位置无效。")
    try:
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != file_sha256:
            raise ResumeError("简历原件与上传记录不一致，请重新上传。")
        parts = []
        with fitz.open(stream=data, filetype="pdf") as doc:
            for page in doc:
                split = page.rect.width / 2 - 20
                blocks = [b for b in page.get_text("blocks", sort=True) if b[6] == 0 and b[4].strip()]
                left = [b for b in blocks if b[0] < split]
                right = [b for b in blocks if b[0] >= split]
                if len(left) >= 2 and len(right) >= 2 and len(right) > 0.3 * len(blocks):
                    blocks = left + right
                parts.append("\n".join(b[4].strip() for b in blocks))
    except (OSError, RuntimeError, ValueError) as exc:
        raise ResumeError("简历原件无法读取，请核对上传目录。") from exc
    if not any(parts):
        raise ResumeError("简历没有可读取的文字。")
    raw = "\n\n".join(f"第 {i} 页\n{text}" for i, text in enumerate(parts, 1))
    if len(raw) > 60000:
        raise ResumeError("简历文字超过单次审查上限，请拆分后上传。")
    return {"raw_text": raw, "page_count": len(parts)}


#  extract_structured LLM 结构化提取
async def extract_structured_node(state: ResumeState) -> dict:
    """用 LLM Function Calling 把文本提取成结构化简历。"""
    raw_text = state["raw_text"]
    prompt = EXTRACT_STRUCTURED_PROMPT.format(resume_text=raw_text)

    structured_llm = get_structured_llm("resume", ResumeStructured)
    structured_dict = None

    for attempt in range(2): # 结构化输出偶发返回 None → 判空+重试
        try:
            result = await structured_llm.ainvoke([
                SystemMessage(content=SYSTEM_PROMPT),
                HumanMessage(content=prompt),
            ])
            if result is None:
                raise ValueError("structured output returned None")
            structured_dict = result.model_dump()
            break
        except Exception as e:
            if attempt == 0:
                logger.warning("extract_structured.retry", error_type=type(e).__name__)
                await asyncio.sleep(1)
            else:
                logger.warning("extract_structured.failed", error_type=type(e).__name__)

    if structured_dict is None:
        raise ResumeError("简历字段提取失败，请重新评审。")

    logger.info("extract_structured.done",
                projects_count=len(structured_dict.get("projects", [])))

    return {"structured": structured_dict}



#  进行六维度评审
async def run_six_dimensions_node(state: ResumeState) -> dict:
    """六维度并行评审：asyncio.gather 同时评，算加权综合分。"""
    raw_text           =    state["raw_text"]
    structured         =    state.get("structured") or {}
    structured_summary =    _build_structured_summary(structured)

    async def review_one_dimension(dim: dict) -> dict:
        prompt = DIMENSION_REVIEW_PROMPT.format(
            dimension=dim["name"], focus=dim["focus"], jd=state["jd_context"],
            resume_text=raw_text, structured_summary=structured_summary,
        )
        for attempt in range(2):                      # 最多 2 次尝试
            try:
                structured_llm = get_structured_llm("resume", DimensionScore)
                result: DimensionScore = await structured_llm.ainvoke([
                    SystemMessage(content=SYSTEM_PROMPT),
                    HumanMessage(content=prompt),
                ])
                d = result.model_dump()
                d["dimension"], d["weight"], d["key"] = dim["name"], dim["weight"], dim["key"]
                return d
            except Exception as e:
                if attempt == 0:
                    logger.warning("six_dimensions.dimension_retry", dimension=dim["name"], error_type=type(e).__name__)
                    await asyncio.sleep(1)
                else:
                    logger.warning("six_dimensions.dimension_failed", dimension=dim["name"], error_type=type(e).__name__)
                    raise ResumeError(f"{dim['name']}评分失败，请重新评审。") from e

    tasks = [review_one_dimension(dim) for dim in SIX_DIMENSIONS]
    dimension_scores = await asyncio.gather(*tasks)              # 并行
    weighted_score = sum(d["score"] * d["weight"] for d in dimension_scores)
    logger.info("six_dimensions.done", weighted_score=round(weighted_score, 2),
                scores={d["key"]: d["score"] for d in dimension_scores})

    return {"dimension_scores": list(dimension_scores), "weighted_score": round(weighted_score, 2)}



def _build_structured_summary(structured: dict) -> str:
    """把结构化数据浓缩成几行摘要，供评审使用（省 token）。"""
    lines = []
    if structured.get("name"):
        lines.append(f"姓名：{structured['name']}")
    if structured.get("target_position"):
        lines.append(f"求职意向：{structured['target_position']}")
    if structured.get("education"):
        edu = structured["education"][0]
        lines.append(f"教育经历：{edu.get('school','')} {edu.get('major','')} {edu.get('degree','')}")
    if structured.get("skills_list"):
        lines.append(f"技术栈：{', '.join(structured['skills_list'][:10])}")
    if structured.get("projects"):
        proj_names = [p.get("name", "") for p in structured["projects"]]
        lines.append(f"项目数量：{len(structured['projects'])} 个（{', '.join(proj_names[:3])}）")
    if structured.get("work_experience"):
        lines.append(f"工作经历：{len(structured['work_experience'])} 段")
    return "\n".join(lines) if lines else "（结构化提取失败，请基于原文评审）"

#  diagnose_issues 逐条问题诊断
async def diagnose_issues_node(state: ResumeState) -> dict:
    """汇总维度问题 → Think 前置推理 → 结构化生成问题清单 → 按优先级排序。"""
    dimension_scores = state.get("dimension_scores", [])
    raw_text         = state["raw_text"]
    structured       = state.get("structured") or {}

    all_raw_issues = []
    for dim in dimension_scores:
        for issue_text in dim.get("issues", []):
            all_raw_issues.append(f"[{dim['dimension']}] {issue_text}")
    raw_issues_text = "\n".join(f"- {i}" for i in all_raw_issues) or "（暂无）"

    reasoning_trace = ""                              # Think 前置推理（可失败）
    try:
        dimension_scores_summary = "\n".join(
            f"- {d['dimension']}：{d['score']}分 — 问题：{', '.join(d.get('issues', [])[:2])}"
            for d in dimension_scores
        )
        think_prompt = DIAGNOSE_THINK_PROMPT.format(
            dimension_scores_summary=dimension_scores_summary, raw_issues=raw_issues_text)
        think_llm = get_llm("resume", temperature=0)
        think_resp = await think_llm.ainvoke([HumanMessage(content=think_prompt)])
        reasoning_trace = (
            think_resp.text if hasattr(think_resp, "text") and not callable(think_resp.text)
            else str(think_resp.content)
        ).strip()
    except Exception as e:
        logger.warning("diagnose_think.failed", error_type=type(e).__name__)

    think_context = f"\n\n【诊断前宏观分析】\n{reasoning_trace}" if reasoning_trace else ""

    prompt = DIAGNOSE_ISSUES_PROMPT.format(
        resume_text=raw_text,
        structured_summary=_build_structured_summary(structured),
        raw_issues=raw_issues_text, jd=state["jd_context"],
    ) + think_context

    try:
        structured_llm = get_structured_llm("resume", IssueList)
        result: IssueList = await structured_llm.ainvoke([
            SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=prompt)])
        issues = [item.model_dump() for item in result.items]
    except Exception as e:
        logger.warning("diagnose_issues.failed", error_type=type(e).__name__)
        issues = [                                    # 降级：用维度问题，统一 medium
            {"priority": "medium", "dimension": dim["dimension"], "description": issue,
             "location": "简历全文", "suggestion": "请参考评审建议修改"}
            for dim in dimension_scores for issue in dim.get("issues", [])
        ]

    priority_order = {"high": 0, "medium": 1, "low": 2}          # 按优先级排序
    issues.sort(key=lambda x: priority_order.get(x.get("priority", "low"), 2))
    logger.info("diagnose_issues.done", total=len(issues),
                high=sum(1 for i in issues if i.get("priority") == "high"))
    return {"issues": issues}


#  generate_summary  整体评价
async def generate_summary_node(state: ResumeState) -> dict:
    """综合结构化信息、评分、问题，生成面向 HR的整体评价。"""
    structured       = state.get("structured") or {}
    dimension_scores = state.get("dimension_scores", [])
    issues           = state.get("issues", [])
    weighted_score   = state.get("weighted_score", 0.0)

    high_issues = [i["description"] for i in issues if i.get("priority") == "high"][:5]
    high_issues_text = "\n".join(f"- {i}" for i in high_issues) or "（无高优先级问题）"
    scores_text = "\n".join(
        f"- {d['dimension']}：{d['score']}分（权重{int(d['weight'] * 100)}%）" for d in dimension_scores)

    prompt = GENERATE_SUMMARY_PROMPT.format(
        structured_summary=_build_structured_summary(structured),
        scores_summary=scores_text, weighted_score=round(weighted_score, 1),
        high_issues=high_issues_text, target_position=state["jd_context"],
    )
    structured_llm = get_structured_llm("resume", ResumeSummary)
    summary_dict = None
    for attempt in range(2):                           # 结构化输出偶发返回 None → 判空+重试
        try:
            result = await structured_llm.ainvoke([
                SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=prompt)])
            if result is None:
                raise ValueError("structured output returned None")
            summary_dict = result.model_dump()
            break
        except Exception as e:
            if attempt == 0:
                logger.warning("generate_summary.retry", error_type=type(e).__name__)
                await asyncio.sleep(1)
            else:
                logger.warning("generate_summary.failed", error_type=type(e).__name__)
    if summary_dict is None:
        summary_dict = {                              # 降级默认评价
            "highlights": ["简历内容已完整提交"],
            "core_improvements": high_issues[:2] if high_issues else ["请参考各维度建议修改"],
            "overall_comment": f"综合评分 {round(weighted_score, 1)} 分，请参考各维度详细反馈。",
            "fit_assessment": "与目标岗位匹配度评估暂不可用",
        }
    logger.info("generate_summary.done", highlights_count=len(summary_dict.get("highlights", [])))
    return {"summary": summary_dict}
