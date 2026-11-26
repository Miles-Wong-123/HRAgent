"""JD 解析 Agent 的输入、输出与图状态，不包含模型调用或数据库操作。

公司、岗位、发起人由业务层鉴权后传入，不由大模型提取或改写。
解析完成只代表生成了待确认草稿，不代表 HR 已确认或 JD 已发布。
"""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from typing_extensions import NotRequired, TypedDict


class JDBaseModel(BaseModel):
    """拒绝未定义的字段，防止模型输出混入公司或权限信息。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class JDTextSource(JDBaseModel):
    """HR 直接粘贴的 JD 原文。"""

    kind:  Literal["text"] = "text"
    text:  str             = Field(min_length=1, description="HR 粘贴的完整原文")


class JDFileSource(JDBaseModel):
    """业务层完成上传校验后提供的文件信息。"""

    kind:               Literal["file"] = "file"
    storage_key:        str             = Field(min_length=1, description="服务端生成的存储标识，不是客户端任意文件路径")
    original_filename:  str             = Field(min_length=1, description="上传时的文件名称")
    file_format:        Literal["pdf", "docx", "txt", "md"]
    file_size_bytes:    int             = Field(gt=0, strict=True)


class JDParseInput(JDBaseModel):
    """图的统一输入：文本和文件二选一，岗位必须已通过权限检查。"""

    parse_id:      UUID = Field(description="本次解析任务 ID，由业务层生成")
    tenant_id:     str  = Field(min_length=1, description="当前账号所属公司")
    position_id:   UUID = Field(description="HR 选中的岗位 ID")
    requested_by:  UUID = Field(description="当前登录用户 ID")
    source:        Annotated[JDTextSource | JDFileSource, Field(discriminator="kind")]


class JDTextBlock(JDBaseModel):
    """文件读取节点生成的原文块，用于定位和校验引用。"""

    block_id:     str        = Field(min_length=1, description="解析程序生成的唯一块标识")
    text:         str        = Field(min_length=1, description="完整原文片段，不由大模型改写")
    page_number:  int | None = Field(default=None, ge=1, strict=True, description="PDF 页码从 1 开始；文本等无页码来源留空")


class JDEvidence(JDBaseModel):
    """模型引用原文块，后续校验节点检查块是否存在、引用是否与原文匹配。"""

    block_id:  str = Field(min_length=1, description="来自输入原文块的 block_id，不得虚构")
    quote:     str = Field(min_length=1, description="直接引用原文，不能改写")


class JDSourcedText(JDBaseModel):
    """一项有原文支持的内容；无法提取时上层字段用 null 或空列表。"""

    value:     str              = Field(min_length=1, description="依据原文提取的内容，不补充推测")
    evidence:  list[JDEvidence] = Field(min_length=1, description="支持该内容的原文引用")


RequirementCategory = Literal[
    "skill", "experience", "education", "certification", "language", "other"
]
RequirementImportance = Literal["required", "preferred", "unspecified"]


class JDRequirement(JDBaseModel):
    """单条候选人要求，尽量拆分为可独立评估的条件。"""

    description:    str                   = Field(min_length=1, description="条件描述；保留原文中的范围、程度和限定词")
    category:       RequirementCategory
    importance:     RequirementImportance = Field(description="明确必备为 required；优先或加分为 preferred；无法确定为 unspecified，交由 HR 确认")
    evidence:       list[JDEvidence]      = Field(min_length=1, description="条件及其重要程度的原文依据")
    clarification:  str | None            = Field(default=None, min_length=1, description="条件存在歧义时记录需要 HR 确认的问题，否则 null")

    # 不让模型生成正式条件 ID 或评分权重，留给业务层与 HR 确认流程。


class JDStructured(JDBaseModel):
    """大模型结构化提取目标；所有内容均为待 HR 确认的草稿。"""

    source_position_title:    JDSourcedText | None = Field(default=None, description="原文岗位名称；不覆盖 HR 已选择的岗位")
    summary:                  JDSourcedText | None = Field(default=None, description="有原文支持的岗位概述")
    responsibilities:         list[JDSourcedText]  = Field(default_factory=list, description="工作职责")
    location:                 JDSourcedText | None = Field(default=None, description="原文工作地点")
    employment_type:          JDSourcedText | None = Field(default=None, description="原文用工类型，例如全职、实习")
    salary:                   JDSourcedText | None = Field(default=None, description="保留薪资原文及币种、周期等限定，不推测或自动换算")
    experience:               JDSourcedText | None = Field(default=None, description="原文经验要求，细项同时归入 requirements")
    education:                JDSourcedText | None = Field(default=None, description="原文学历要求，细项同时归入 requirements")
    requirements:             list[JDRequirement]  = Field(default_factory=list)
    missing_information:      list[str]            = Field(default_factory=list, description="原文未提供且需要 HR 补充的信息")
    clarification_questions:  list[str]            = Field(default_factory=list, description="歧义、矛盾或岗位名称不一致等需确认的问题")


JDParseStatus = Literal[
    "pending", "extracting", "analyzing", "validating", "completed", "needs_ocr", "failed"
]


class JDValidationIssue(JDBaseModel):
    """由程序校验产生，不由模型声明其自身输出已经通过校验。"""

    code:        str = Field(min_length=1, description="例如 missing_block、quote_mismatch、no_requirements")
    field_path:  str = Field(min_length=1, description="例如 requirements.0.evidence.0")
    message:     str = Field(min_length=1)


class JDParseError(JDBaseModel):
    code:       str  = Field(min_length=1, description="例如 unsupported_format、empty_text、model_timeout")
    message:    str  = Field(min_length=1, description="可返回给用户的说明，不含密钥或内部异常堆栈")
    retryable:  bool = Field(default=False, description="是否允许重新尝试此任务")


class JDParseState(TypedDict):
    """LangGraph 状态：输入必填，其余字段由各节点逐步写入。

    后续节点必须验证引用，并处理职责/条件缺失、岗位名称冲突等情况。
    TypedDict 本身不执行运行时校验；图入口应使用 JDParseInput.model_validate。
    原文读取不完整或校验失败时不得将 status 设置为 completed。
    """

    input:                    JDParseInput
    selected_position_title:  NotRequired[str | None]  # 业务层提供，仅用于比对，不覆盖岗位关联
    status:                   NotRequired[JDParseStatus]
    raw_text:                 NotRequired[str]
    text_blocks:              NotRequired[list[JDTextBlock]]
    page_count:               NotRequired[int | None]
    extraction_complete:      NotRequired[bool]
    structured:               NotRequired[JDStructured | None]
    validation_issues:        NotRequired[list[JDValidationIssue]]
    warnings:                 NotRequired[list[str]]
    error:                    NotRequired[JDParseError | None]
    model_name:               NotRequired[str | None]
    prompt_version:           NotRequired[str | None]
