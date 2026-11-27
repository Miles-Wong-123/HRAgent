"""JD 解析节点：读取原文 → 模型提取 → 引用校验。

节点返回状态更新字典，由后续 graph.py 串联。本模块不存数据库、不发布 JD。
文件路径只能由服务端上传目录和 storage_key 解析，不能读取任意本机文件。
"""

import asyncio
import re
import zipfile
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage
from openai import APIConnectionError, APIStatusError, APITimeoutError
from pydantic import ValidationError

from backend.agents.jd.prompts import PROMPT_VERSION, SYSTEM_PROMPT, build_extract_prompt
from backend.agents.jd.state import (
    JDExtraction, JDFileSource, JDParseError, JDParseInput, JDParseState, JDStructured,
    JDTextBlock, JDTextSource, JDValidationIssue,
)
from backend.config import get_settings
from backend.core.logger import get_logger


logger = get_logger(__name__)

# 第一版明确拒绝超限资料，不静默截断。后续长文分段能力可替换此限制。
MAX_TEXT_CHARACTERS   = 60_000
MAX_PROMPT_CHARACTERS = 160_000
MAX_PDF_PAGES         = 50
MAX_DOCX_UNPACKED     = 50 * 1024 * 1024
BLOCK_CHARACTERS      = 2_000
MODEL_TIMEOUT_SECONDS = 120
MODEL_ATTEMPTS        = 2
TERMINAL_STATUSES     = {"failed", "needs_ocr"}


class _ReadError(Exception):
    """仅用于文件读取内部传递可公开的错误，不暴露文件路径或原始异常。"""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _failure(code: str, message: str, *, retryable: bool = False, **updates) -> dict:
    return {
        **updates,
        "status": "failed",
        "structured": None,
        "error": JDParseError(code=code, message=message, retryable=retryable),
    }


def _input(state: JDParseState) -> JDParseInput:
    value = state.get("input")
    if isinstance(value, JDParseInput):
        value = value.model_dump()
    return JDParseInput.model_validate(value)


def _blocks(parts: list[tuple[str, int | None]]) -> list[JDTextBlock]:
    """按原文句末、换行及列表标题划块，让模型能分别选择标题和每条条件。"""
    blocks = []
    boundaries = r"(?<=[。！？；])|[\r\n]+|(?<=(?:必备条件|优先条件|任职要求|岗位职责)[：:])"
    for text, page in parts:
        for sentence in re.split(boundaries, text):
            for start in range(0, len(sentence), BLOCK_CHARACTERS):
                content = sentence[start:start + BLOCK_CHARACTERS].strip()
                if content:
                    blocks.append(JDTextBlock(
                        block_id=f"b{len(blocks) + 1:04d}", text=content, page_number=page
                    ))
    return blocks


def _read_text(path: Path) -> list[tuple[str, None]]:
    data = path.read_bytes()
    if b"\x00" in data and not data.startswith((b"\xff\xfe", b"\xfe\xff")):
        raise _ReadError("invalid_text", "文件包含非文本内容，请上传有效的文本文件。")
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        encodings = ("utf-16",)
    else:
        encodings = ("utf-8-sig", "gb18030")
    for encoding in encodings:
        try:
            return [(data.decode(encoding), None)]
        except UnicodeDecodeError:
            continue
    raise _ReadError("unsupported_encoding", "无法识别文本编码，请另存为 UTF-8 后上传。")


def _read_pdf(path: Path) -> tuple[list[tuple[str, int]], int, bool, list[str]]:
    import fitz

    parts, needs_ocr, warnings = [], False, []
    with fitz.open(path) as document:
        if not document.is_pdf:
            raise _ReadError("invalid_pdf", "文件内容不是有效的 PDF。")
        if document.needs_pass:
            raise _ReadError("encrypted_file", "PDF 已加密，请先解密再上传。")
        if document.page_count > MAX_PDF_PAGES:
            raise _ReadError("too_many_pages", f"JD 文件不能超过 {MAX_PDF_PAGES} 页。")
        for page_number, page in enumerate(document, start=1):
            content = page.get_text("text", sort=True)
            parts.append((content, page_number))
            if not content.strip() and page.get_images():
                needs_ocr = True
                warnings.append(f"第 {page_number} 页只有图片内容，需要 OCR。")
            elif page.get_images():
                # 混合图文可能含有正文截图，不能声明已经完整读取。
                needs_ocr = True
                warnings.append(f"第 {page_number} 页含图片，需核对图片文字后才能完整解析。")
        return parts, document.page_count, needs_ocr, warnings


def _read_docx(path: Path) -> tuple[list[tuple[str, None]], bool, list[str]]:
    from docx import Document
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    with zipfile.ZipFile(path) as archive:
        if sum(item.file_size for item in archive.infolist()) > MAX_DOCX_UNPACKED:
            raise _ReadError("document_too_large", "Word 文档解压后过大，请简化文件后重试。")
        if "word/document.xml" not in archive.namelist():
            raise _ReadError("invalid_docx", "文件内容不是有效的 DOCX 文档。")

    document = Document(path)
    parts = []

    def collect(container):
        # 按文档顺序读取段落、表格和嵌套表格，合并单元格只读取一次。
        for item in container.iter_inner_content():
            if isinstance(item, Paragraph):
                if item.text.strip():
                    parts.append((item.text, None))
            elif isinstance(item, Table):
                seen = set()
                for row in item.rows:
                    for cell in row.cells:
                        if cell._tc not in seen:
                            seen.add(cell._tc)
                            collect(cell)

    collect(document)
    # 页眉页脚不与正文合并推断页码；内容仍纳入可引用文本。
    seen_headers = set()
    xml_parts = [document._element]
    for section in document.sections:
        for container in (section.header, section.first_page_header, section.even_page_header,
                          section.footer, section.first_page_footer, section.even_page_footer):
            if container._element not in seen_headers:
                seen_headers.add(container._element)
                collect(container)
                xml_parts.append(container._element)

    has_images = any(xml.xpath(".//w:drawing | .//w:pict") for xml in xml_parts)
    unsupported = any(xml.xpath(
        ".//w:txbxContent | .//w:altChunk | .//w:del | .//w:ins | .//w:footnoteReference | .//w:endnoteReference"
    ) for xml in xml_parts)
    warnings = []
    if has_images:
        warnings.append("Word 文档含图片或绘图，需要核对其中的文字。")
    if unsupported:
        raise _ReadError("unsupported_word_content", "Word 含文本框、修订、脚注或嵌入内容，请整理为普通正文或文本型 PDF。")
    return parts, has_images, warnings


def _read_file(source: JDFileSource) -> dict:
    settings = get_settings()
    extension = f".{source.file_format}"
    if extension not in settings.allowed_jd_extensions:
        raise _ReadError("unsupported_format", "当前配置不允许上传该格式的 JD 文件。")
    root = Path(settings.upload_dir).resolve()
    key = Path(source.storage_key)
    if key.is_absolute():
        raise _ReadError("invalid_storage_key", "文件存储标识无效。")
    path = (root / key).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise _ReadError("file_unavailable", "上传文件不存在或不在允许的存储目录内。")
    if path.suffix.lower() != extension:
        raise _ReadError("format_mismatch", "文件格式与存储文件扩展名不一致。")
    actual_size = path.stat().st_size
    if actual_size != source.file_size_bytes:
        raise _ReadError("file_changed", "文件大小与上传记录不符，请重新上传。")
    if actual_size > settings.upload_max_size_bytes:
        raise _ReadError("file_too_large", "文件超过配置的上传大小上限。")

    warnings, needs_ocr, pages = [], False, None
    if source.file_format == "pdf":
        parts, pages, needs_ocr, warnings = _read_pdf(path)
    elif source.file_format == "docx":
        parts, needs_ocr, warnings = _read_docx(path)
    else:
        parts = _read_text(path)
    return {"parts": parts, "page_count": pages, "needs_ocr": needs_ocr, "warnings": warnings}


async def extract_text_node(state: JDParseState) -> dict:
    """校验输入并提取原文；同步文件读取放在线程中。"""
    reset = {"raw_text": "", "text_blocks": [], "page_count": None,
             "extraction_complete": False, "structured": None, "validation_issues": [],
             "warnings": [], "error": None, "model_name": None, "prompt_version": None}
    try:
        request = _input(state)
        if isinstance(request.source, JDTextSource):
            result = {"parts": [(request.source.text, None)], "page_count": None,
                      "needs_ocr": False, "warnings": []}
        else:
            result = await asyncio.to_thread(_read_file, request.source)
        raw_text = "\n\n".join(part for part, _ in result["parts"])
        if len(raw_text) > MAX_TEXT_CHARACTERS:
            return _failure("text_too_long", f"JD 正文超过 {MAX_TEXT_CHARACTERS} 字符，请拆分为单个岗位的文件。", **reset)
        blocks = _blocks(result["parts"])
        output = {**reset, "input": request, "raw_text": raw_text, "text_blocks": blocks,
                  "page_count": result["page_count"], "warnings": result["warnings"]}
        if result["needs_ocr"]:
            return {**output, "status": "needs_ocr", "error": JDParseError(
                code="needs_ocr", message="文件包含未识别的图片内容，当前阶段未接入 OCR。"
            )}
        if not blocks:
            return _failure("empty_text", "没有提取到有效的 JD 正文。", **output)
        return {**output, "status": "analyzing", "extraction_complete": True}
    except ValidationError:
        return _failure("invalid_input", "JD 解析输入不完整或格式无效。", **reset)
    except _ReadError as exc:
        return _failure(exc.code, exc.message, **reset)
    except Exception as exc:
        logger.warning("jd.extract_text_failed", error_type=type(exc).__name__)
        return _failure("file_parse_failed", "无法读取文件，请确认文件完整且格式正确。", **reset)


def _resolve_evidence(extraction: JDExtraction, blocks: list[JDTextBlock]) -> tuple[JDStructured | None, list[JDValidationIssue]]:
    """仅从本次读取的原文取证；无效编号带字段路径返回，阻止保存草稿。"""
    source = {block.block_id: block.text for block in blocks}
    data = extraction.model_dump()
    issues = []
    for field, value in data.items():
        items = value if isinstance(value, list) else [value]
        for index, item in enumerate(items):
            if not isinstance(item, dict) or "evidence" not in item:
                continue
            path = f"{field}.{index}" if isinstance(value, list) else field
            citations = []
            for number, block_id in enumerate(item["evidence"]):
                if block_id not in source:
                    issues.append(JDValidationIssue(
                        code="missing_block", field_path=f"{path}.evidence.{number}",
                        message=f"引用编号 {block_id[:80]} 不在本次 JD 的原文块中。",
                    ))
                else:
                    citations.append({"block_id": block_id, "quote": source[block_id]})
            item["evidence"] = citations
    if issues:
        return None, issues
    return JDStructured.model_validate(data), []


async def extract_structured_node(state: JDParseState) -> dict:
    """调用公共模型工厂提取 JD，最多重试一次临时网络或服务错误。"""
    if state.get("status") in TERMINAL_STATUSES:
        return {}
    if not state.get("extraction_complete"):
        return _failure("incomplete_extraction", "原文尚未完整读取，不能继续模型解析。")
    try:
        blocks = [JDTextBlock.model_validate(b) for b in state.get("text_blocks", [])]
        prompt = build_extract_prompt(blocks, selected_position_title=state.get("selected_position_title"))
    except (ValidationError, ValueError):
        return _failure("invalid_text_blocks", "原文块缺失、重复或格式无效。")
    if len(prompt) + len(SYSTEM_PROMPT) > MAX_PROMPT_CHARACTERS:
        return _failure("prompt_too_long", "JD 超过本阶段的完整解析限制，请拆分后重试。")

    # 延迟导入：只读取文件、校验引用时不初始化模型工厂的网络客户端。
    from backend.core.llm_factory import get_llm, get_structured_llm

    metadata = {"prompt_version": PROMPT_VERSION, "structured": None,
                "validation_issues": [], "error": None}
    for attempt in range(MODEL_ATTEMPTS):
        try:
            model = get_llm("jd_parser")
            metadata["model_name"] = getattr(model, "model_name", None) or getattr(model, "model", None)
            structured_model = get_structured_llm("jd_parser", JDExtraction)
            result = await asyncio.wait_for(structured_model.ainvoke([
                SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=prompt),
            ]), timeout=MODEL_TIMEOUT_SECONDS)
            if result is None:
                return _failure("empty_model_output", "模型未返回结构化内容，请重新解析。", retryable=True, **metadata)
            extraction = JDExtraction.model_validate(result)
            structured, issues = _resolve_evidence(extraction, blocks)
            if issues:
                metadata["validation_issues"] = issues
                return _failure("evidence_validation_failed", "模型引用了不存在的原文块，请查看 validation_issues。",
                                retryable=True, **metadata)
            return {**metadata, "structured": structured, "status": "validating"}
        except (TimeoutError, APIConnectionError, APITimeoutError, APIStatusError) as exc:
            temporary = not isinstance(exc, APIStatusError) or exc.status_code in {408, 409, 429} or exc.status_code >= 500
            if temporary and attempt + 1 < MODEL_ATTEMPTS:
                logger.warning("jd.model_retry", attempt=attempt + 1, error_type=type(exc).__name__)
                await asyncio.sleep(1)
                continue
            return _failure("model_unavailable", "模型服务暂时不可用，请稍后重试。", retryable=temporary, **metadata)
        except ValidationError:
            return _failure("invalid_model_output", "模型返回的字段不符合 JD 结构，请重新解析。", retryable=True, **metadata)
        except Exception as exc:
            logger.warning("jd.model_failed", error_type=type(exc).__name__)
            return _failure("model_failed", "模型解析未完成，请检查服务配置或重新解析。", **metadata)


def validate_result_node(state: JDParseState) -> dict:
    """校验输出结构及所有引用；成功仍只是待 HR 确认的草稿。"""
    if state.get("status") in TERMINAL_STATUSES:
        return {}
    if not state.get("extraction_complete"):
        return _failure("incomplete_extraction", "原文尚未完整读取，不能确认解析完成。")
    try:
        value = state.get("structured")
        structured = JDStructured.model_validate(value.model_dump() if isinstance(value, JDStructured) else value)
        blocks = [JDTextBlock.model_validate(b) for b in state.get("text_blocks", [])]
    except ValidationError:
        return _failure("invalid_result", "解析结果或原文结构无效。")

    issues = []
    block_map = {block.block_id: block.text for block in blocks}

    def issue(code, path, message):
        issues.append(JDValidationIssue(code=code, field_path=path, message=message))

    if not blocks or len(block_map) != len(blocks):
        issue("invalid_blocks", "text_blocks", "原文块为空或存在重复标识。")

    def walk(value, path):
        if isinstance(value, dict):
            if "block_id" in value and "quote" in value:
                source = block_map.get(value["block_id"])
                if source is None:
                    issue("missing_block", path, "引用的原文块不存在。")
                elif value["quote"] not in source:
                    issue("quote_mismatch", path, "引用文字与对应原文不匹配。")
            for key, child in value.items():
                walk(child, f"{path}.{key}" if path else key)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                walk(child, f"{path}.{index}")

    walk(structured.model_dump(), "")
    if issues:
        return _failure("evidence_validation_failed", "原文引用校验未通过，请重新解析。",
                        retryable=True, validation_issues=issues)

    warnings = list(state.get("warnings", []))
    if not structured.requirements:
        warnings.append("未提取到任职条件，需要 HR 补充后才能用于筛选。")
    if not structured.responsibilities:
        warnings.append("未提取到岗位职责，请 HR 确认原文是否完整。")
    for requirement in structured.requirements:
        if requirement.importance == "unspecified" and not requirement.clarification:
            requirement.clarification = "请 HR 确认此条件属于必备还是加分项。"
    selected = state.get("selected_position_title")
    extracted = structured.source_position_title
    if selected and extracted and selected.strip().casefold() != extracted.value.strip().casefold():
        warnings.append("原文岗位名称与所选岗位不一致，请 HR 核对后再确认。")
    return {"status": "completed", "structured": structured, "error": None,
            "validation_issues": [], "warnings": list(dict.fromkeys(warnings))}
