"""按任务固定的 JD 版本运行六维度评审，并在一个事务中保存整份结果。"""
import asyncio
import json
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.agents.resume.graph import build_resume_graph
from backend.agents.resume.nodes import ResumeError
from backend.agents.resume.state import ResumeReport, ResumeState
from backend.core.logger import get_logger
from backend.dependencies import AsyncSessionLocal

logger = get_logger(__name__)
MATCH_TIMEOUT_SECONDS = 180
MATCH_LEASE_SECONDS = 300


async def read_match(db: AsyncSession, tenant: str, review_id: UUID, *, lock: bool = False) -> dict:
    params = {"tenant": tenant, "id": review_id, "lease": MATCH_LEASE_SECONDS}
    # 进程退出后，轮询或重试都会使过期任务恢复成可重试的失败状态。
    await db.execute(text("""
        UPDATE public.resume_reviews SET status='failed', match_finished_at=now(),
            match_error='评审任务中断，请重新发起评审。'
        WHERE tenant_id=:tenant AND id=:id AND status='processing'
          AND match_started_at < now() - make_interval(secs => :lease)
    """), params)
    query = """
        SELECT r.id AS review_id, r.jd_id, j.version AS jd_version, r.resume_id, r.status,
               r.match_started_at, r.match_finished_at, r.match_error, r.requirement_results, r.six_dimension_report
        FROM public.resume_reviews r
        JOIN public.job_descriptions j ON j.tenant_id=r.tenant_id AND j.id=r.jd_id
        WHERE r.tenant_id=:tenant AND r.id=:id
    """
    if lock:
        query += " FOR UPDATE OF r"
    row = (await db.execute(text(query), params)).mappings().one_or_none()
    if row is None:
        raise HTTPException(404, "审查任务不存在")
    return dict(row)


async def claim_match(db: AsyncSession, tenant: str, review_id: UUID) -> tuple[dict, UUID | None]:
    detail = await read_match(db, tenant, review_id, lock=True)
    if detail["status"] == "processing" or detail["six_dimension_report"] is not None:
        await db.commit()
        return detail, None

    attempt = uuid4()
    started = (await db.execute(text("""
        UPDATE public.resume_reviews SET status='processing', match_attempt=:attempt, match_started_at=now(),
            match_finished_at=NULL, match_error=NULL
        WHERE tenant_id=:tenant AND id=:id RETURNING match_started_at
    """), {"tenant": tenant, "id": review_id, "attempt": attempt})).scalar_one()
    await db.commit()
    detail.update(status="processing", match_started_at=started, match_finished_at=None, match_error=None)
    return detail, attempt


async def _load_input(tenant: str, review_id: UUID, attempt: UUID) -> ResumeState | None:
    async with AsyncSessionLocal() as db:
        source = (await db.execute(text("""
            SELECT r.jd_id, s.storage_key, s.file_sha256, j.position_title_snapshot, j.reviewed_data
            FROM public.resume_reviews r
            JOIN public.job_descriptions j ON j.tenant_id=r.tenant_id AND j.id=r.jd_id
            JOIN public.resumes s ON s.tenant_id=r.tenant_id AND s.id=r.resume_id
            WHERE r.tenant_id=:tenant AND r.id=:id AND r.match_attempt=:attempt AND r.status='processing'
        """), {"tenant": tenant, "id": review_id, "attempt": attempt})).mappings().one_or_none()
        if source is None:
            return None
        rows = (await db.execute(text("""
            SELECT description, importance, evaluation_rule
            FROM public.job_requirements WHERE tenant_id=:tenant AND jd_id=:jd
            ORDER BY sort_order
        """), {"tenant": tenant, "jd": source["jd_id"]})).mappings().all()
    if not rows:
        raise ResumeError("任务缺少已确认的岗位条件，请核对绑定的 JD。")
    context = {"岗位名称": source["position_title_snapshot"], "岗位说明": source["reviewed_data"],
               "任职条件": [dict(row) for row in rows]}
    return {"storage_key": source["storage_key"], "file_sha256": source["file_sha256"],
            "jd_context": json.dumps(context, ensure_ascii=False)}


async def run_match(tenant: str, review_id: UUID, attempt: UUID) -> None:
    report = error = None
    try:
        async with asyncio.timeout(MATCH_TIMEOUT_SECONDS):
            inputs = await _load_input(tenant, review_id, attempt)
            if inputs is None:
                return
            output = await build_resume_graph().ainvoke(inputs)
            report = ResumeReport.model_validate(output).model_dump_json()
    except ResumeError as exc:
        error = str(exc)
    except TimeoutError:
        error = "六维度评审超时，请稍后重试。"
    except Exception as exc:
        logger.warning("resume.match_failed", review_id=str(review_id), error_type=type(exc).__name__)
        error = "六维度评审失败，请检查模型服务配置或稍后重试。"

    async with AsyncSessionLocal() as db, db.begin():
        await db.execute(text("""
            UPDATE public.resume_reviews SET status=:status, match_finished_at=now(), match_error=:error,
                six_dimension_report=CAST(:report AS jsonb)
            WHERE tenant_id=:tenant AND id=:id AND match_attempt=:attempt AND status='processing'
        """), {"status": "failed" if error else "completed", "error": error, "report": report,
               "tenant": tenant, "id": review_id, "attempt": attempt})
