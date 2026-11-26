# backend/config.py
# 全项目唯一的「配置中心」：从 .env.local 读取所有配置项，供任何模块取用。

# 导包
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings


# 动态拼接环境文件的路径
PROJECT_ROOT = Path(__file__).resolve().parent.parent
env_local_path = PROJECT_ROOT / ".env.local"


# 配置模型：每个类属性对应 .env.local 里的一项配置（大小写不敏感）
class Settings(BaseSettings):

    # ── 数据库（PostgreSQL）──
    db_host: str = "localhost"   # 主机
    db_port: int = 5432          # 端口
    db_name: str = "hragent"     # 库名
    db_user: str                 # 用户名
    db_password: str             # 密码


    #用 @property 装饰后，可像访问属性一样 settings.database_url 取值，不用加括号调用。
    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )


    # ── Milvus 向量库 ──
    milvus_host: str = "localhost"  #主机
    milvus_port: int = 19530        # 端口号


    # ── 文件上传（JD 与简历共用）──
    # 相对目录以项目根目录为基准；读取配置不会创建目录。
    upload_dir: Path = PROJECT_ROOT / "uploads"
    upload_max_size_mb: int = Field(default=10, gt=0)  # 单个文件大小上限，单位 MiB
    # 环境变量覆盖列表时使用 JSON，如 ALLOWED_JD_EXTENSIONS='[".pdf", ".txt"]'。
    # JD 支持格式是后续上传接口的配置约定，具体解析功能仍需实现。
    allowed_resume_extensions: list[str] = Field(default_factory=lambda: [".pdf"])
    allowed_jd_extensions: list[str] = Field(default_factory=lambda: [".pdf", ".docx", ".txt", ".md"])

    @field_validator("upload_dir")
    @classmethod
    def resolve_upload_dir(cls, value: Path) -> Path:
        value = value.expanduser()
        if not value.is_absolute():
            value = PROJECT_ROOT / value
        return value.resolve()

    @field_validator("allowed_resume_extensions", "allowed_jd_extensions")
    @classmethod
    def normalize_extensions(cls, values: list[str]) -> list[str]:
        if not values:
            raise ValueError("允许上传的文件扩展名列表不能为空")
        extensions = []
        for value in values:
            extension = value.strip().lower()
            extension = extension if extension.startswith(".") else f".{extension}"
            if len(extension) < 2 or not extension[1:].isalnum():
                raise ValueError("文件扩展名必须是 pdf、.pdf 等格式")
            if extension not in extensions:
                extensions.append(extension)
        return extensions

    @property
    def upload_max_size_bytes(self) -> int:
        return self.upload_max_size_mb * 1024 * 1024


    # ── 大模型（DeepSeek）──
    deepseek_api_key: str                                   # 必填：DeepSeek 的 API Key
    deepseek_base_url: str = "https://api.deepseek.com/v1"  # DeepSeek 接口地址
    deepseek_model_chat: str = "deepseek-chat"              # 对话模型名
    deepseek_model_coder: str = "deepseek-coder"            # 代码模型名


    # ── 本地模型权重路径 ──
    reranker_model_path: str = "./models/reranker/bge-reranker-large"    # 精排模型
    classifier_model_path: str = "./models/classifier/all-MiniLM-L6-v2"  # 意图分类模型
    bge_m3_model_path: str = "./models/embedding/bge-m3"                 # 嵌入模型
    finetuned_classifier_path: str="./models/classifier/my_finetuned_model"


    # ── JWT 认证 ──
    jwt_secret_key: str                           # 必填：签发登录令牌用的密钥
    jwt_algorithm: str = "HS256"                  # 签名算法
    jwt_access_token_expire_minutes: int = 10080  # 令牌有效期（分钟）


    # ── MCP Server 地址（第五章用）──
    kb_mcp_server_url:  str = "http://localhost:8000/mcp/kb"
    web_search_mcp_url: str = "http://localhost:8000/mcp/web-search"


    # ── Web 搜索（Tavily 可选；留空则自动用免费的 DuckDuckGo）──
    tavily_api_key: str = ""


    # ── 应用基础配置 ──
    app_env: str = "local"                     # 运行环境标识
    app_debug: bool = False                    # 是否调试模式
    app_host: str = "0.0.0.0"                  # 监听地址
    app_port: int = 8000                       # 监听端口
    log_level: str = "INFO"                    # 日志级别
    default_tenant_id: str = "tenant_default"  # 多租户默认值


    #Pydantic 的元配置：告诉 BaseSettings 该怎么读取配置。
    class Config:
        env_file = env_local_path        # 从这个文件读取配置
        env_file_encoding = "utf-8"      # 文件编码
        case_sensitive = False           # 大小写不敏感：环境变量 DB_HOST 能对应字段 db_host
        extra = "ignore"                 # .env.local 里多出来的、模型没定义的字段一律忽略（不报错）


# 标准库装饰器：缓存函数结果，让函数实际只执行一次
@lru_cache()
def get_settings() -> Settings:
    # 首次调用时创建实例；之后每次都返回同一个缓存对象
    return Settings()
