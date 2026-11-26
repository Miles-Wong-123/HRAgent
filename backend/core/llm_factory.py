# backend/core/llm_factory.py
# LLM Factory：统一封装大模型调用，按 Agent 类型路由。
# 规矩：所有 Agent 必须通过此模块获取模型，禁止直接调用 init_chat_model。

from typing import Type, Any                          # 类型注解用：Type 表示「某个类本身」，Any 表示任意类型
from pydantic import BaseModel                        # 结构化输出的 Schema 都是它的子类
import httpx                                          # HTTP 客户端库（用来自定义网络行为）

from langchain.chat_models import init_chat_model         # 2.3 学的：创建聊天模型（1.x 写法）
from langchain_core.language_models import BaseChatModel  # 聊天模型的基类（类型注解用）
from langchain_core.runnables import Runnable             # 「可运行对象」基类，结构化模型属于它

from backend.config import get_settings               # 读配置（API Key、base_url 等）
from backend.core.logger import get_logger            # 结构化日志

logger = get_logger(__name__)                         # 本模块的日志器，name 用当前模块名

# 自定义 httpx 客户端：绕过系统代理
_HTTP_ASYNC_CLIENT = httpx.AsyncClient(                       # 异步客户端（给 ainvoke/astream 用）
    trust_env=False,
    timeout=httpx.Timeout(120.0, connect=15.0),       # 总超时 120 秒，建立连接超时 15 秒
)
_HTTP_SYNC_CLIENT = httpx.Client(                             # 同步客户端（给 invoke 用）
    trust_env=False,
    timeout=httpx.Timeout(120.0, connect=15.0),
)

# Agent 类型 → 模型标识符 的路由表
_AGENT_MODEL_ROUTING: dict[str, str] = {
    "resume":           "deepseek-chat",   # 简历审查
    "jd_parser":        "deepseek-chat",   # JD 结构化解析
}

# 模型标识符（实际模型） → DeepSeek API 实际接受的 model 名称
_MODEL_ID_MAP: dict[str, str] = {
    "deepseek-chat": "deepseek-v4-pro",
}

# 大模型工厂（统一获取模型的唯一入口）
class LLMFactory:

    # 类变量：模型实例缓存（缓存键 → 模型），全类共享
    _instances: dict[str, BaseChatModel] = {}

    # 内置：取配置对象。
    @classmethod
    def _get_settings(cls):
        return get_settings()

    # 内置：组装 init_chat_model 需要的所有参数
    @classmethod
    def _build_model_kwargs(cls, model_key: str) -> dict[str, Any]:

        settings = cls._get_settings()
        model_id = _MODEL_ID_MAP[model_key]        # 把模型标识符转成 API 实际的 model 名

        return {
            "model": model_id,                     # 模型名，如 "deepseek-chat"
            "model_provider": "openai",            # 强制走 langchain-openai（DeepSeek 兼容 OpenAI 接口）
            "temperature": 0,                      # 默认 0：评分/批改要稳定输出
            "api_key": settings.deepseek_api_key,  # 来自 .env.local
            "base_url": settings.deepseek_base_url,# DeepSeek 接口地址
            "max_retries": 0,                      # 模型层不重试；重试统一由 retry.py（3.5）管
            "http_async_client": _HTTP_ASYNC_CLIENT,  # 用上面绕过代理的异步客户端
            "http_client": _HTTP_SYNC_CLIENT,         # 同步客户端
        }

    # 根据 模型名-温度-是否流式输出 获取大模型
    @classmethod
    def get_llm(
        cls,
        agent_type: str,                  # Agent 类型，必须在路由表里
        temperature: float = 0,      # 温度：对话类可传 0.3~0.7，评分类保持 0
        streaming: bool = False,          # 是否流式输出（问答/面试对话用）
        ) -> BaseChatModel:

        # 检查是agent-type是否合规
        if agent_type not in _AGENT_MODEL_ROUTING:
            raise ValueError(
                f"未知 agent_type: '{agent_type}'，"
                f"可用类型：{list(_AGENT_MODEL_ROUTING.keys())}"
            )

        # 查路由表，拿到模型标识符(模型厂商)
        model_key = _AGENT_MODEL_ROUTING[agent_type]

        # 用「模型_温度_是否流式」拼一个缓存键：不同组合各缓存一份
        cache_key = f"{model_key}_{temperature}_{streaming}"

        if cache_key not in cls._instances:  # 缓存里没有才新建
            # 组装基础参数
            kwargs = cls._build_model_kwargs(model_key)

            kwargs["temperature"] = temperature                     # 覆盖温度
            kwargs["streaming"] = streaming                         # 设置是否流式
            kwargs["extra_body"] = {"thinking":{"type":"disabled"}} #思考模式

            # 真正创建模型
            llm = init_chat_model(**kwargs)

            # 存进缓存
            cls._instances[cache_key] = llm

            logger.info(
                "llm_factory.model_initialized",
                agent_type=agent_type, model_key=model_key,
                temperature=temperature, streaming=streaming,
            )

        return cls._instances[cache_key]

    # 获取「绑定了结构化输出 Schema」的模型。
    @classmethod
    def get_structured_llm(
        cls,
        agent_type: str,
        output_schema: Type[BaseModel],   # 期望的输出结构（一个 Pydantic 模型类）
        temperature: float = 0,
        ) -> Runnable:

        # 先拿普通模型
        llm = cls.get_llm(agent_type, temperature=temperature)

        # 绑定 Pydantic 结构；method="function_calling" 是 DeepSeek 必须的（回顾 2.3）
        return llm.with_structured_output(output_schema,
                                          method="function_calling")

    # 清空模型实例缓存（测试时用）
    @classmethod
    def clear_cache(cls) -> None:
        cls._instances.clear()
        logger.info("llm_factory.cache_cleared")


# LLMFactory.get_llm 的便捷入口
# LLMFactory.get_llm(...) ->  from llm_factory import get_llm
def get_llm(agent_type: str,
            temperature: float = 0,
            streaming: bool = False
            ) -> BaseChatModel:

    return LLMFactory.get_llm(agent_type,
                              temperature=temperature,
                              streaming=streaming)

# LLMFactory.get_structured_llm 的便捷入口
def get_structured_llm(agent_type: str,
                       output_schema: Type[BaseModel]
                       ) -> Runnable:

    return LLMFactory.get_structured_llm(agent_type, output_schema)

if __name__ == '__main__':

    import asyncio
    from langchain_core.messages import HumanMessage, SystemMessage
    from pydantic import Field

    async def main():
        class PersonInfo(BaseModel):
            name: str = Field(description="姓名")
            age: int = Field(description="年龄（整数）")

        llm_struct = get_structured_llm("qa", PersonInfo)

        messages = [SystemMessage(content="你负责从文本中抽取任务信息"),
                    HumanMessage(content="我叫王茂宇，今年23岁")]

        result = await llm_struct.ainvoke(messages)

        print(f"{result}")
        print(f"{result.model_dump()}")

    asyncio.run(main())
