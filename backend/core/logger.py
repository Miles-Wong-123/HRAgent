# backend/core/logger.py
# 全项目的日志工具：在标准库 logging 之上做一层包装，
# 支持「事件名 + 键值对」的结构化日志写法。

import logging
import sys
import os
from backend.config import get_settings   # 读取配置（需要里面的 log_level 日志级别）

# 添加项目路径到系统路径中
eduagents_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(eduagents_path)

#  日志包装类
class _Logger:
    '''
    作用：让我们能用 logger.info("事件名", key=value) 这种「结构化」写法，
    而不必每次手动拼字符串。内部仍委托给标准库 logging 真正输出。
    （前缀下划线 _ 表示它是「内部类」，外部应通过下面的 get_logger() 来获取实例)
    '''
    def __init__(self, name: str):
        # 构造方法：name 通常传 __name__（当前模块名），这样日志里能看出是哪个模块打的
        self._log = logging.getLogger(name)   # 拿到标准库的 logger 实例并存起来，后续都用它输出

    #  内部格式化方法：把「事件名 + 关键字参数」格式化成一行可读字符串。
    # 例：_fmt("user.login", user_id="u1") → "user.login | user_id='u1'"
    def _fmt(self, event: str, **kw) -> str:
        if kw:
            return event + " | " + " ".join(f"{k}={v!r}" for k, v in kw.items())
        return event

    #  重写日志方法
    def debug(self, event: str, **kw):
        self._log.debug(self._fmt(event, **kw))
    def info(self, event: str, *args, **kw):
        if args:
            self._log.info(event, *args)
        else:
            self._log.info(self._fmt(event, **kw))
    def warning(self, event: str, *args, **kw):
        if args:
            self._log.warning(event, *args)
        else:
            self._log.warning(self._fmt(event, **kw))
    def error(self, event: str, **kw):
        # 从 kw 中取出 exc_info 参数（没有则默认 False），并移除它
        exc_info = kw.pop("exc_info", False)
        self._log.error(self._fmt(event, **kw), exc_info=exc_info)
    def critical(self, event: str, **kw):
        self._log.critical(self._fmt(event, **kw))

#  全局日志配置函数
def configure_logging() -> None:
    """
    整个应用只在启动时（main.py）调用一次。
    负责设定日志格式、级别，并压低第三方库的噪音日志。
    """

    # 拿到日志的级别
    settings = get_settings()
    level = getattr(logging, settings.log_level.upper(), logging.INFO)

    # 标准库的「一键全局配置」
    logging.basicConfig(
        format  ="%(asctime)s [%(levelname)s] %(name)s: %(message)s",  # 格式：时间 [级别] 模块名: 内容
        stream  =sys.stdout,                                           # 把日志打到标准输出（控制台）
        level   =level,                                                # 全局生效的日志级别
        force   =True,                                                 # 强制覆盖已有的日志配置（否则重复调用 basicConfig 会失效）
    )

    # 下面把几个第三方库的日志级别单独调到 WARNING，屏蔽它们大量的 INFO 噪音，避免刷屏
    logging.getLogger("sqlalchemy.engine"   ).setLevel(logging.WARNING)  # SQLAlchemy 的 SQL 执行日志
    logging.getLogger("sqlalchemy.pool"     ).setLevel(logging.WARNING)    # SQLAlchemy 连接池日志
    logging.getLogger("httpx"               ).setLevel(logging.WARNING)              # httpx HTTP 客户端日志
    logging.getLogger("httpcore"            ).setLevel(logging.WARNING)           # httpcore 底层日志


# 对外的工厂函数
def get_logger(name: str) -> _Logger:
    """
    每个模块用 get_logger(__name__) 拿到自己的日志器。
    """
    return _Logger(name)