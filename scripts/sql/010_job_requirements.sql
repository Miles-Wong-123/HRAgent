-- JD 筛选条件表，在 009_job_descriptions.sql 成功执行后执行本文件。
-- 一条记录对应一个可独立判断的条件；不插入任何测试条件。
BEGIN;

CREATE TABLE public.job_requirements (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id           VARCHAR(64) NOT NULL,
    jd_id               UUID NOT NULL,
    sort_order          INTEGER NOT NULL CHECK (sort_order >= 0),
    description         TEXT NOT NULL CHECK (btrim(description) <> ''),
    category            VARCHAR(20) NOT NULL CHECK (category IN (
                            'skill', 'experience', 'education', 'certification', 'language', 'other'
                        )),
    importance          VARCHAR(16) NOT NULL CHECK (importance IN (
                            'required', 'preferred', 'unspecified'
                        )),
    -- 原文引用沿用 Agent 的 [{block_id, quote}]；手动新增的条件允许无原文引用。
    evidence            JSONB NOT NULL DEFAULT '[]'::jsonb
                        CHECK (jsonb_typeof(evidence) = 'array'),
    source              VARCHAR(8) NOT NULL DEFAULT 'ai' CHECK (source IN ('ai', 'manual')),
    clarification       TEXT,
    evaluation_rule     TEXT,
    -- AI 初次提取不赋权重；由 HR 确认。评分使用相对权重，不要求总和为 100。
    weight              NUMERIC(8,2) CHECK (weight > 0 AND weight <= 10000),
    confirmed_by        UUID,
    confirmed_at        TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT requirements_jd_fk FOREIGN KEY (tenant_id, jd_id)
        REFERENCES public.job_descriptions (tenant_id, id) ON DELETE RESTRICT,
    CONSTRAINT requirements_confirmer_fk FOREIGN KEY (tenant_id, confirmed_by)
        REFERENCES public.users (tenant_id, id) ON DELETE RESTRICT,
    CONSTRAINT requirements_tenant_id_key UNIQUE (tenant_id, id),
    CONSTRAINT requirements_order_key UNIQUE (tenant_id, jd_id, sort_order)
        DEFERRABLE INITIALLY IMMEDIATE,
    CONSTRAINT requirements_ai_evidence_check CHECK (
        source <> 'ai' OR jsonb_array_length(evidence) > 0
    ),
    CONSTRAINT requirements_confirmation_check CHECK (
        (confirmed_by IS NULL AND confirmed_at IS NULL)
        OR (confirmed_by IS NOT NULL AND confirmed_at IS NOT NULL
            AND importance <> 'unspecified'
            AND evaluation_rule IS NOT NULL AND btrim(evaluation_rule) <> ''
            AND weight IS NOT NULL)
    )
);

CREATE FUNCTION public.guard_job_requirement_change()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE
    parent_status VARCHAR(16);
    target_tenant VARCHAR(64);
    target_jd UUID;
BEGIN
    IF TG_OP = 'UPDATE' THEN
        IF NEW.id IS DISTINCT FROM OLD.id
            OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
            OR NEW.jd_id IS DISTINCT FROM OLD.jd_id THEN
            RAISE EXCEPTION 'A requirement cannot be moved to another JD'
                USING ERRCODE = '23514';
        END IF;
        -- 已确认条件被编辑时，必须同时清空确认人和时间，重新由 HR 确认。
        IF (NEW.description, NEW.category, NEW.importance, NEW.evidence,
            NEW.source, NEW.clarification, NEW.evaluation_rule, NEW.weight)
            IS DISTINCT FROM
           (OLD.description, OLD.category, OLD.importance, OLD.evidence,
            OLD.source, OLD.clarification, OLD.evaluation_rule, OLD.weight)
            AND NEW.confirmed_by IS NOT NULL THEN
            RAISE EXCEPTION 'Clear requirement confirmation before editing'
                USING ERRCODE = '23514';
        END IF;
    END IF;

    IF TG_OP = 'DELETE' THEN
        target_tenant := OLD.tenant_id;
        target_jd := OLD.jd_id;
    ELSE
        target_tenant := NEW.tenant_id;
        target_jd := NEW.jd_id;
    END IF;

    -- 与发布操作串行，避免发布期间插入/修改条件。
    SELECT publication_status INTO parent_status
    FROM public.job_descriptions
    WHERE tenant_id = target_tenant AND id = target_jd FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Parent JD does not exist in this company'
            USING ERRCODE = '23503';
    END IF;
    IF parent_status <> 'draft' THEN
        RAISE EXCEPTION 'Only draft JD requirements can be edited'
            USING ERRCODE = '23514';
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    NEW.updated_at := NOW();
    RETURN NEW;
END;
$$;

CREATE TRIGGER job_requirements_guard_change
BEFORE INSERT OR UPDATE OR DELETE ON public.job_requirements
FOR EACH ROW EXECUTE FUNCTION public.guard_job_requirement_change();

CREATE FUNCTION public.check_job_description_publication()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.publication_status = 'published' THEN
        IF NOT EXISTS (
            SELECT 1 FROM public.job_requirements
            WHERE tenant_id = NEW.tenant_id AND jd_id = NEW.id
        ) THEN
            RAISE EXCEPTION 'Confirm at least one requirement before publication'
                USING ERRCODE = '23514';
        END IF;
        IF EXISTS (
            SELECT 1 FROM public.job_requirements
            WHERE tenant_id = NEW.tenant_id AND jd_id = NEW.id
                AND (confirmed_by IS NULL OR confirmed_at IS NULL
                    OR importance = 'unspecified'
                    OR evaluation_rule IS NULL OR btrim(evaluation_rule) = ''
                    OR weight IS NULL)
        ) THEN
            RAISE EXCEPTION 'All requirements must be reviewed before publication'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER job_descriptions_check_publication
BEFORE INSERT OR UPDATE ON public.job_descriptions
FOR EACH ROW EXECUTE FUNCTION public.check_job_description_publication();

COMMIT;
