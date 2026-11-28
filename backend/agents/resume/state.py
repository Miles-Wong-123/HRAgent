from typing_extensions import TypedDict

from pydantic import BaseModel, Field

#  单条教育经历
class EducationItem(BaseModel):
    """单条教育经历。"""
    school:   str = Field(              description="学校名称")
    major:    str = Field(              description="专业名称")
    degree:   str = Field(              description="学历：本科/专科/硕士等")
    duration: str = Field(              description="在校时间，如 2020.09 - 2024.06")
    gpa:      str = Field(default="",   description="GPA 或成绩（可选）")

#  单条项目
class ProjectItem(BaseModel):
    """单条项目经历。"""
    name:        str       = Field(                         description="项目名称")
    role:        str       = Field(                         description="担任角色，如：后端开发/全栈/负责人")
    duration:    str       = Field(                         description="项目时间，如 2023.06 - 2023.12")
    tech_stack:  list[str] = Field(                         description="使用的技术栈列表，如 [Spring Boot, MySQL, Redis]")
    description: str       = Field(                         description="项目描述原文（保留原始表述）")
    highlights:  list[str] = Field(default_factory=list,    description="量化亮点句子列表（含数字的句子）")

class WorkItem(BaseModel):
    """单条工作/实习经历。"""
    company:     str       = Field(                         description="公司名称")
    position:    str       = Field(                         description="职位名称")
    duration:    str       = Field(                         description="工作时间")
    tech_stack:  list[str] = Field(default_factory=list,    description="涉及技术栈")
    description: str       = Field(                         description="工作内容原文")

#  结构化提取结果（LLM Function Calling 的输出目标）
class ResumeStructured(BaseModel):
    """简历结构化提取结果（完整 Schema）——extract_structured 节点的输出目标。"""
    # 基本信息
    name:            str                = Field(                      description="姓名")
    phone:           str                = Field(default="",           description="手机号")
    email:           str                = Field(default="",           description="邮箱")
    target_position: str                = Field(default="",           description="求职意向岗位")
    # 教育经历
    education:       list[EducationItem]= Field(default_factory=list)
    # 技能
    skills_raw:      str                = Field(default="",           description="技能栏原始文本")
    skills_list:     list[str]          = Field(default_factory=list, description="解析后的技术标签列表")
    # 项目经历
    projects:        list[ProjectItem]  = Field(default_factory=list)
    # 工作/实习经历
    work_experience: list[WorkItem]     = Field(default_factory=list)
    # 其他
    certificates:    list[str]          = Field(default_factory=list, description="证书列表")
    self_intro:      str                = Field(default="",           description="个人简介/自我评价原文")



#  2 六维度评审结果
class DimensionScore(BaseModel):
    """单个评审维度结果。"""
    # dimension/weight 由代码层填（来自 4.5 的 SIX_DIMENSIONS），LLM 不用管，给默认值即可
    dimension:   str            = Field(default="",           description="维度名称（代码层覆盖，LLM 可留空）")
    score:       int            = Field(ge=0, le=100, description="得分 0-100")               # LLM 真正要给的
    weight:      float     = Field(default=0.0,          description="权重（代码层覆盖，LLM 可填 0）")
    issues:      list[str]      = Field(default_factory=list, description="该维度问题列表")
    suggestions: list[str]      = Field(default_factory=list, description="改进建议列表")


class IssueItem(BaseModel):
    """单条诊断问题。"""
    priority:    str = Field(   description="优先级：high / medium / low")
    dimension:   str = Field(   description="所属维度")
    description: str = Field(   description="问题描述（1句话）")
    location:    str = Field(   description="问题在简历中的定位，如：项目经历-电商系统-第2句")
    suggestion:  str = Field(   description="具体修改建议（可操作）")


class IssueList(BaseModel):
    """IssueItem 列表的包装类。
    为什么要包一层：with_structured_output 要求顶层是「对象」而非「裸列表」，
    所以不能直接让 LLM 返回 list[IssueItem]，要包成 {items: [...]}。"""
    items: list[IssueItem]


class ResumeSummary(BaseModel):
    """简历整体评价——generate_summary 节点的输出目标。"""
    highlights:        list[str] = Field(description="2-3 条核心亮点")
    core_improvements: list[str] = Field(description="2-3 条最重要的改进方向")
    overall_comment:   str       = Field(description="1-2 句综合评语")
    fit_assessment:    str       = Field(description="对目标岗位的匹配度评估（1句话）")


class ScoredDimension(DimensionScore):
    key: str


class ResumeReport(BaseModel):
    structured: ResumeStructured
    dimension_scores: list[ScoredDimension] = Field(min_length=6, max_length=6)
    weighted_score: float = Field(ge=0, le=100)
    issues: list[IssueItem]
    summary: ResumeSummary


class ResumeState(TypedDict, total=False):
    storage_key: str
    file_sha256: str
    jd_context: str
    raw_text: str
    page_count: int
    structured: dict
    dimension_scores: list[dict]
    weighted_score: float
    issues: list[dict]
    summary: dict
