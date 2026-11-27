"""JD 模块的两张图：解析生成草稿，人工审核后发布。

失败、超限或需要 OCR 时直接结束，不继续调用后续节点。
解析图返回校验过的草稿；审核图通过业务层提供的回调发布确认后的版本。
"""

from collections.abc import Awaitable, Callable
from functools import lru_cache
from typing import Literal

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.types import interrupt
from langgraph.graph import END, START, StateGraph

from backend.agents.jd.nodes import (
    extract_structured_node,
    extract_text_node,
    validate_result_node,
)
from backend.agents.jd.state import JDParseInput, JDParseState, JDReviewDecision, JDReviewState


def _after_extract_text(state: JDParseState) -> Literal["analyze", "end"]:
    """只有原文读取完整，才允许提交给模型。"""
    if state.get("status") == "analyzing" and state.get("extraction_complete"):
        return "analyze"
    return "end"


def _after_extract_structured(state: JDParseState) -> Literal["validate", "end"]:
    """模型返回结构化草稿后，必须经过引用校验才能结束为 completed。"""
    if state.get("status") == "validating" and state.get("structured") is not None:
        return "validate"
    return "end"


@lru_cache(maxsize=1)
def build_jd_parser_graph():
    """构建并缓存无持久化状态的图；每次调用传入独立任务数据。

    不使用 checkpointer：本阶段是一次性解析，结果由业务层接收。
    调用方可通过 astream(stream_mode="updates") 获取各节点完成后的更新。
    """
    builder = StateGraph(JDParseState)

    builder.add_node("extract_text",       extract_text_node)
    builder.add_node("extract_structured", extract_structured_node)
    builder.add_node("validate_result",    validate_result_node)

    builder.add_edge(START, "extract_text")
    builder.add_conditional_edges(
        "extract_text",
        _after_extract_text,
        {"analyze": "extract_structured", "end": END},
    )
    builder.add_conditional_edges(
        "extract_structured",
        _after_extract_structured,
        {"validate": "validate_result", "end": END},
    )
    builder.add_edge("validate_result", END)

    return builder.compile()


def build_jd_review_graph(
    checkpointer: BaseCheckpointSaver,
    publish: Callable[[JDReviewDecision], Awaitable[None]],
):
    """解析草稿落库后进入审核。新旧草稿共用同一暂停、恢复及发布流程。"""

    def hr_review(state: JDReviewState) -> dict:
        decision = interrupt({"jd_id": state["jd_id"], "action": "review_and_publish"})
        return {"decision": decision}

    async def publish_review(state: JDReviewState) -> dict:
        await publish(JDReviewDecision.model_validate(state["decision"]))
        return {"published": True}

    builder = StateGraph(JDReviewState)
    builder.add_node("hr_review", hr_review)
    builder.add_node("publish_review", publish_review)
    builder.add_edge(START, "hr_review")
    builder.add_edge("hr_review", "publish_review")
    builder.add_edge("publish_review", END)
    return builder.compile(checkpointer=checkpointer)


async def run_jd_parser(
    request: JDParseInput | dict,
    *,
    selected_position_title: str | None = None,
) -> JDParseState:
    """供后续业务层使用的统一异步入口，仅返回本次任务的解析结果。

    request 及岗位名称必须由已经鉴权的业务层提供。公司和岗位归属检查、
    上传文件所有权检查由调用方负责，不能将此函数直接作为公开接口。
    输入不合法时抛出 Pydantic ValidationError，读取或模型失败则返回错误状态。
    每次从空中间结果开始，避免重新解析时携带上一份草稿或失败标记。
    """
    validated = JDParseInput.model_validate(
        request.model_dump() if isinstance(request, JDParseInput) else request
    )
    initial: JDParseState = {
        "input": validated,
        "selected_position_title": selected_position_title,
        "status": "pending",
    }
    return await build_jd_parser_graph().ainvoke(initial)


if __name__ == "__main__":
    # 在项目根目录执行：python -m backend.agents.jd.graph
    # 此入口会调用 .env.local 配置的大模型，只解析下方虚构 JD，不操作数据库。
    import asyncio
    import json
    from time import perf_counter
    from uuid import uuid4

    from pydantic import TypeAdapter

    from backend.core.logger import configure_logging

    DEMO_JD = """岗位名称：Java 后端开发工程师
        所属部门：研发部
        工作地点：深圳
        用工类型：全职
        薪资待遇：税前月薪 18,000—25,000 元人民币，13 薪。
        
        岗位职责：
        1. 负责支付服务的后端接口开发与维护。
        2. 参与数据库设计、接口性能优化和线上问题排查。
        3. 与产品、测试团队协作，完成需求交付和技术文档编写。
        
        任职要求：
        1. 本科及以上学历，计算机或相关专业。
        2. 至少三年 Java 后端开发经验，熟悉 Spring Boot。
        3. 熟悉 MySQL，能够进行 SQL 性能分析和优化。
        4. 掌握 Git，能独立完成代码提交和协作开发。
        5. 有支付系统或账务系统开发经验者优先。
        6. 了解 Docker 或 Kubernetes 至少一种者优先。
        
        补充说明：团队采用代码评审流程，支持技术分享。"""

    async def main() -> int:
        configure_logging()

        # 这些 ID 仅满足输入结构，不对应真实账号或岗位，不会查询数据库。
        request = JDParseInput(
            parse_id=uuid4(),
            tenant_id="demo_local",
            position_id=uuid4(),
            requested_by=uuid4(),
            source={"kind": "text", "text": DEMO_JD},
        )

        print("=== JD 解析图演示（虚构文本）===", flush=True)
        print(DEMO_JD, flush=True)
        print("正在调用配置的大模型，请稍候……", flush=True)

        started = perf_counter()
        result = await run_jd_parser(
            request,
            selected_position_title="Java 后端开发工程师",
        )

        print(f"\n解析状态：{result['status']}，耗时：{perf_counter() - started:.1f} 秒")
        print("=== 完整结果（含字段、原文引用、警告及错误）===")
        # 将嵌套 Pydantic 对象和 UUID 转为普通 JSON，保留中文方便阅读。
        output = TypeAdapter(JDParseState).dump_python(result, mode="json")
        print(json.dumps(output, ensure_ascii=False, indent=2))

        if result["status"] == "completed":
            print("\n已生成待 HR 确认的草稿；未发布或写入数据库。")
            return 0

        print("\n解析未完成，请查看上方 error 和 validation_issues。")
        return 1

    raise SystemExit(asyncio.run(main()))
