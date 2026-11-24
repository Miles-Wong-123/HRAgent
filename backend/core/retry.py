# backend/core/retry.py
# 三层兜底机制：自动重试 → Agent 级降级 → 系统级兜底

#  0 导包
import asyncio                                   # 异步：用于超时控制和等待
from functools import wraps                      # @wraps：装饰器里保留原函数的名字/文档
from typing import Callable, Any, Optional       # 类型注解：可调用对象 / 任意 / 可选
# 引入已经定义的异常
from backend.core.exceptions import (
    LLMAPIError,            # 大模型 API 调用失败（超时 / 限流 / 网络错误）
    MilvusConnectionError,  # Milvus 向量库连接失败
    InvalidInputError,      # 无效输入
    AuthenticationError,    # 认证失败
)
from backend.core.logger import get_logger,configure_logging

#  1 定义全局常量
# 获取日志器
logger = get_logger(__name__)
# 异常分类
# 可重试
RETRYABLE_ERRORS = (
    LLMAPIError,            # 大模型 API 调用失败
    MilvusConnectionError,  # Milvus 向量库连接失败
    TimeoutError,           # 超时错误
    ConnectionError,        # 连接错误
)

# 不可重试
NON_RETRYABLE_ERRORS = (
    InvalidInputError,      # 无效输入
    AuthenticationError,    # # 认证失败
)

MAX_RETRIES = 2                  # 最多重试 2 次（加上首次 = 共 3 次尝试）
RETRY_DELAYS = [1.0, 3.0]        # 第 1 次重试前等 1 秒，第 2 次前等 3 秒
TIMEOUT_PER_ATTEMPT = 120.0       # 单次调用最多等 30 秒，超时算失败


#  2 重试装饰器
def with_retry(agent_type: str = ""):
    """
    三层兜底装饰器工厂。给异步函数套上「重试 → 降级 → 系统兜底」三层保护。
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs) -> Any:

            # 2.1 第一层：自动重试
            last_error: Optional[Exception] = None   # 记录最后一次的错误，留给后面降级用
            # 尝试执行三次原函数
            for attempt in range(MAX_RETRIES + 1):
                try:
                    # 给单次调用套一个超时；超过 30 秒就抛 TimeoutError
                    result = await asyncio.wait_for(
                        func(*args, **kwargs),
                        timeout=TIMEOUT_PER_ATTEMPT,
                    )
                    # 走到这里说明是成功了
                    if attempt > 0:
                        logger.info("retry.succeeded",
                                    agent_type=agent_type,
                                    attempt=attempt + 1)
                    return result

                # 不可重试异常：立即抛出，不再重试
                except NON_RETRYABLE_ERRORS as e:
                    logger.warning("retry.non_retryable_error",
                                   agent_type=agent_type,
                                   error=str(e))
                    raise

                # 其它（可重试）异常
                except Exception as e:
                    last_error = e                   # 记下来
                    if attempt < MAX_RETRIES:        # 还没到上限：等待后重试
                        delay = RETRY_DELAYS[attempt]
                        logger.warning(
                            "retry.attempt_failed",
                            agent_type=agent_type,
                            attempt=attempt + 1,
                            max_retries=MAX_RETRIES,
                            delay=delay,
                            error=str(e),
                        )
                        await asyncio.sleep(delay)   # 等 1s 或 3s 再重试

                    # 到上限了：记录失败，跳出循环去降级
                    else:
                        logger.error("retry.all_attempts_failed",
                                     agent_type=agent_type,
                                     error=str(e))

            #  2.2 第二层：Agent 级降级
            try:
                fallback_result = await AgentFallbackHandler.handle(  # 按 agent_type 找降级策略
                    agent_type=agent_type,
                    original_error=last_error,
                )

                logger.info("retry.fallback_succeeded", agent_type=agent_type)

                return fallback_result               # 降级成功，返回降级结果

            # 连降级都失败
            except Exception as fallback_error:
                logger.error("retry.fallback_failed",
                             agent_type=agent_type,
                             error=str(fallback_error))

            # 第三层：系统级兜底
            logger.error("retry.system_fallback",
                         agent_type=agent_type,
                         original_error=str(last_error))

            # 最后的保底，永远不会再失败
            return _system_fallback_response(agent_type)

        return wrapper
    return decorator

#  3 第二层：Agent降级 -> 返回一个更新字典
class AgentFallbackHandler:
    """
    第二层降级：各 Agent 的专项降级策略（尽量保留核心功能，退化为更简单的实现）。
    """
    @classmethod
    async def handle(cls, agent_type: str, original_error: Exception) -> Any:
        """根据 agent_type 选择对应的降级策略。"""

        # 类型 → 降级方法 的映射表
        fallback_map = {
            "qa":               cls._qa_fallback,
            "exam_code":        cls._exam_code_fallback,
            "exam_subjective":  cls._exam_subjective_fallback,
            "resume":           cls._resume_fallback,
            "interview":        cls._interview_fallback,
        }

        # 查表
        handler = fallback_map.get(agent_type)

        # 如果有对应的降级策略
        if handler:
            return await handler()

        # 没有对应降级策略，原样抛出（交给系统兜底）
        raise original_error

    @classmethod
    async def _qa_fallback(cls) -> dict:
        """
        问答降级：知识库或模型不可用，返回提示语。
        """
        logger.info("fallback.qa_service_unavailable")
        return {
            "fallback_used": True,
            "content": "⚠️ 知识库检索暂时不可用，请稍后重试或直接联系教师提问。",
            "structured_output": None,
        }

    @classmethod
    async def _exam_code_fallback(cls) -> dict:
        """
        代码批改降级：评分服务不可用，标记需教师人工复核。
        """
        logger.info("fallback.exam_code_basic")
        return {
            "fallback_used": True,
            "needs_teacher_review": True,
            "fallback_note": "代码评分服务暂时不可用，已标记为需教师人工复核。",
        }

    @classmethod
    async def _exam_subjective_fallback(cls) -> dict:
        """
        简答题批改降级：标记需教师复核。
        """
        logger.info("fallback.exam_subjective_basic")
        return {
            "fallback_used": True,
            "needs_teacher_review": True,
            "fallback_note": "AI 评分服务暂时不可用，已标记为需教师人工批改。",
        }

    @classmethod
    async def _resume_fallback(cls) -> dict:
        """
        简历审查降级：提示服务不可用 / 检查文件。
        """
        logger.info("fallback.resume_service_unavailable")
        return {
            "fallback_used": True,
            "content": "简历审查服务暂时不可用，请稍后重试。如持续失败，请检查上传的 PDF 文件是否完整。",
            "structured_output": None,
        }

    @classmethod
    async def _interview_fallback(cls) -> dict:
        """
        面试降级：跳过深度分析，返回基础反馈。
        """
        logger.info("fallback.interview_basic_feedback")
        return {
            "fallback_used": True,
            "content": "面试评估服务暂时不可用，已记录本次面试对话，请稍后查看报告。",
            "structured_output": None,
        }

#  4 第三层：系统级兜底
def _system_fallback_response(agent_type: str) -> dict:
    """
    第三层：系统级兜底。所有降级都失败后返回它，保证用户始终能收到响应。
    """

    # 按 agent_type 给不同的友好提示
    messages = {
        "qa":        "非常抱歉，智能问答服务暂时不可用，请稍后再试，或直接联系教师提问。",
        "exam":      "非常抱歉，试卷批改服务暂时不可用，您的提交已保存，待服务恢复后将自动处理。",
        "resume":    "非常抱歉，简历审查服务暂时不可用，请稍后重新上传。",
        "interview": "非常抱歉，模拟面试服务暂时不可用，请稍后重新开始。",
    }

    # 找不到就用通用提示
    content = messages.get(agent_type, "服务暂时不可用，请稍后再试。")

    return {
        "messages": [],
        "content": content,
        "fallback_used": True,
        "system_fallback": True,                      # 标记：走到了最后一层系统兜底
        "structured_output": None,
    }