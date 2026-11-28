-- HRAgent · PostgreSQL 15。仅用于在空数据库的 SQL Console 中手动初始化。
BEGIN;

-- 公司

CREATE TABLE public.companies (
    -- 登录账号通过 users.tenant_id 关联公司。
    id              VARCHAR(64) PRIMARY KEY,
    name            VARCHAR(200) NOT NULL,
    short_name      VARCHAR(100),
    address         VARCHAR(500),
    description     TEXT,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT companies_id_not_blank CHECK (btrim(id) <> ''),
    CONSTRAINT companies_name_not_blank CHECK (btrim(name) <> '')
);

CREATE FUNCTION public.set_companies_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at := NOW();
    RETURN NEW;
END;
$$;

CREATE TRIGGER companies_set_updated_at
BEFORE UPDATE ON public.companies
FOR EACH ROW EXECUTE FUNCTION public.set_companies_updated_at();

-- 登录账号

CREATE TABLE public.users (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       VARCHAR(64) NOT NULL,
    username        VARCHAR(64) NOT NULL,
    email           VARCHAR(254),
    password_hash   VARCHAR(256) NOT NULL,
    display_name    VARCHAR(100),
    role            VARCHAR(16) NOT NULL CHECK (role IN ('hr', 'admin')),
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT users_company_fk FOREIGN KEY (tenant_id)
        REFERENCES public.companies (id) ON DELETE RESTRICT,
    CONSTRAINT users_tenant_username_key UNIQUE (tenant_id, username),
    CONSTRAINT users_tenant_id_key UNIQUE (tenant_id, id),
    CONSTRAINT users_tenant_not_blank CHECK (btrim(tenant_id) <> ''),
    CONSTRAINT users_username_not_blank CHECK (btrim(username) <> ''),
    CONSTRAINT users_email_not_blank CHECK (email IS NULL OR btrim(email) <> ''),
    CONSTRAINT users_password_hash_not_blank CHECK (btrim(password_hash) <> '')
);

CREATE UNIQUE INDEX users_tenant_email_key
    ON public.users (tenant_id, email) WHERE email IS NOT NULL;
-- 当前登录入口通过用户名或邮箱查找；多个账号匹配时由接口拒绝登录。
CREATE INDEX users_username_idx ON public.users (username);
CREATE INDEX users_email_idx ON public.users (email) WHERE email IS NOT NULL;

CREATE FUNCTION public.set_users_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at := NOW();
    RETURN NEW;
END;
$$;

CREATE TRIGGER users_set_updated_at
BEFORE UPDATE ON public.users
FOR EACH ROW EXECUTE FUNCTION public.set_users_updated_at();

-- 部门

CREATE TABLE public.departments (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       VARCHAR(64) NOT NULL,
    name            VARCHAR(100) NOT NULL,
    description     TEXT,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT departments_company_fk FOREIGN KEY (tenant_id)
        REFERENCES public.companies (id) ON DELETE RESTRICT,
    CONSTRAINT departments_tenant_name_key UNIQUE (tenant_id, name),
    -- 岗位通过公司和部门的组合外键关联本公司部门。
    CONSTRAINT departments_tenant_id_key UNIQUE (tenant_id, id),
    CONSTRAINT departments_name_not_blank
        CHECK (name = btrim(name) AND name <> '')
);

CREATE INDEX departments_tenant_active_idx ON public.departments (tenant_id, is_active);

CREATE FUNCTION public.set_departments_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at := NOW();
    RETURN NEW;
END;
$$;

CREATE TRIGGER departments_set_updated_at
BEFORE UPDATE ON public.departments
FOR EACH ROW EXECUTE FUNCTION public.set_departments_updated_at();

-- 岗位

CREATE TABLE public.positions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id VARCHAR(64) NOT NULL,
    department_id UUID NOT NULL,
    title VARCHAR(200) NOT NULL CHECK (title = btrim(title) AND title <> ''),
    location VARCHAR(100),
    description TEXT,
    target_headcount INTEGER NOT NULL DEFAULT 1 CHECK (target_headcount BETWEEN 1 AND 100000),
    hired_headcount INTEGER NOT NULL DEFAULT 0 CHECK (hired_headcount >= 0 AND hired_headcount <= target_headcount),
    recruitment_status VARCHAR(16) NOT NULL DEFAULT 'open' CHECK (recruitment_status IN ('open', 'paused', 'closed')),
    created_by UUID NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT positions_department_fk FOREIGN KEY (tenant_id, department_id)
        REFERENCES public.departments (tenant_id, id) ON DELETE RESTRICT,
    CONSTRAINT positions_creator_fk FOREIGN KEY (tenant_id, created_by)
        REFERENCES public.users (tenant_id, id) ON DELETE RESTRICT,
    CONSTRAINT positions_tenant_department_title_key UNIQUE (tenant_id, department_id, title),
    CONSTRAINT positions_tenant_id_key UNIQUE (tenant_id, id)
);

CREATE INDEX positions_tenant_status_idx ON public.positions (tenant_id, recruitment_status, created_at);

CREATE FUNCTION public.set_positions_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at := NOW();
    RETURN NEW;
END;
$$;

CREATE TRIGGER positions_set_updated_at BEFORE UPDATE ON public.positions
FOR EACH ROW EXECUTE FUNCTION public.set_positions_updated_at();

-- JD 版本与发布状态

CREATE TABLE public.job_descriptions (
    -- 本次解析任务的 parse_id 同时用作 JD 版本 ID。
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id               VARCHAR(64) NOT NULL,
    position_id             UUID NOT NULL,
    version                 INTEGER NOT NULL CHECK (version > 0),
    -- 保存创建该版本时 HR 选择的岗位名称，用于原文名称比对及历史追溯。
    position_title_snapshot VARCHAR(200) NOT NULL
                            CHECK (btrim(position_title_snapshot) <> ''),

    -- 两种输入：粘贴文本保留 source_text；文件保留服务端生成的存储信息。
    source_type             VARCHAR(8) NOT NULL CHECK (source_type IN ('text', 'file')),
    source_text             TEXT,
    storage_key             TEXT,
    original_filename       VARCHAR(255),
    file_format             VARCHAR(8),
    file_size_bytes         BIGINT,
    file_sha256             VARCHAR(64),

    -- 完整解析原文及可引用文本块，对应 JDParseState。
    raw_text                TEXT,
    text_blocks             JSONB NOT NULL DEFAULT '[]'::jsonb
                            CHECK (jsonb_typeof(text_blocks) = 'array'),
    page_count              INTEGER CHECK (page_count > 0),
    extraction_complete     BOOLEAN NOT NULL DEFAULT FALSE,
    -- structured_data 保留模型原始草稿，不用 HR 的后续编辑覆盖。
    structured_data         JSONB CHECK (jsonb_typeof(structured_data) = 'object'),
    -- reviewed_data 保存 HR 确认的岗位概述、职责、地点等字段。
    -- 可编辑的筛选标准只以 job_requirements 为准，不在此重复存 requirements。
    reviewed_data           JSONB CHECK (
                                jsonb_typeof(reviewed_data) = 'object'
                                AND NOT (reviewed_data ? 'requirements')
                            ),
    parse_status            VARCHAR(16) NOT NULL DEFAULT 'pending'
                            CHECK (parse_status IN (
                                'pending', 'extracting', 'analyzing', 'validating',
                                'completed', 'needs_ocr', 'failed'
                            )),
    warnings                JSONB NOT NULL DEFAULT '[]'::jsonb
                            CHECK (jsonb_typeof(warnings) = 'array'),
    validation_issues       JSONB NOT NULL DEFAULT '[]'::jsonb
                            CHECK (jsonb_typeof(validation_issues) = 'array'),
    error                   JSONB CHECK (jsonb_typeof(error) = 'object'),
    model_name              VARCHAR(200),
    prompt_version          VARCHAR(64),
    parse_started_at        TIMESTAMPTZ,
    parse_finished_at       TIMESTAMPTZ,

    publication_status      VARCHAR(16) NOT NULL DEFAULT 'draft'
                            CHECK (publication_status IN ('draft', 'published', 'archived')),
    created_by              UUID NOT NULL,
    published_by            UUID,
    published_at            TIMESTAMPTZ,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT jd_position_fk FOREIGN KEY (tenant_id, position_id)
        REFERENCES public.positions (tenant_id, id) ON DELETE RESTRICT,
    CONSTRAINT jd_creator_fk FOREIGN KEY (tenant_id, created_by)
        REFERENCES public.users (tenant_id, id) ON DELETE RESTRICT,
    CONSTRAINT jd_publisher_fk FOREIGN KEY (tenant_id, published_by)
        REFERENCES public.users (tenant_id, id) ON DELETE RESTRICT,
    CONSTRAINT jd_tenant_id_key UNIQUE (tenant_id, id),
    CONSTRAINT jd_review_position_key UNIQUE (tenant_id, position_id, id),
    CONSTRAINT jd_position_version_key UNIQUE (tenant_id, position_id, version),

    CONSTRAINT jd_source_check CHECK (
        (source_type = 'text'
            AND source_text IS NOT NULL AND btrim(source_text) <> ''
            AND storage_key IS NULL AND original_filename IS NULL
            AND file_format IS NULL AND file_size_bytes IS NULL AND file_sha256 IS NULL)
        OR
        (source_type = 'file' AND source_text IS NULL
            AND storage_key IS NOT NULL AND btrim(storage_key) <> ''
            AND original_filename IS NOT NULL AND btrim(original_filename) <> ''
            AND file_format IS NOT NULL AND file_format IN ('pdf', 'docx', 'txt', 'md')
            AND file_size_bytes IS NOT NULL AND file_size_bytes > 0
            AND file_sha256 IS NOT NULL AND file_sha256 ~ '^[0-9a-f]{64}$')
    ),
    CONSTRAINT jd_completed_check CHECK (
        parse_status <> 'completed'
        OR (extraction_complete AND raw_text IS NOT NULL AND btrim(raw_text) <> ''
            AND jsonb_array_length(text_blocks) > 0
            AND structured_data IS NOT NULL
            AND jsonb_array_length(validation_issues) = 0 AND error IS NULL
            AND parse_finished_at IS NOT NULL)
    ),
    CONSTRAINT jd_publication_check CHECK (
        publication_status = 'draft'
        OR (parse_status = 'completed' AND reviewed_data IS NOT NULL
            AND published_by IS NOT NULL AND published_at IS NOT NULL)
    ),
    CONSTRAINT jd_draft_publication_check CHECK (
        publication_status <> 'draft' OR (published_by IS NULL AND published_at IS NULL)
    ),
    CONSTRAINT jd_parse_time_check CHECK (
        parse_started_at IS NULL OR parse_finished_at IS NULL
        OR parse_finished_at >= parse_started_at
    )
);

-- 每个岗位最多一个当前发布版本，旧版本归档后才能发布新版本。
CREATE UNIQUE INDEX jd_one_published_per_position
    ON public.job_descriptions (tenant_id, position_id)
    WHERE publication_status = 'published';
CREATE INDEX jd_position_history_idx
    ON public.job_descriptions (tenant_id, position_id, version DESC);
CREATE INDEX jd_parse_status_idx
    ON public.job_descriptions (tenant_id, parse_status, created_at);

CREATE FUNCTION public.guard_job_description_update()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    -- 已发布内容只允许归档；归档后也不能回到草稿或改写历史内容。
    IF OLD.publication_status IN ('published', 'archived') THEN
        IF (to_jsonb(NEW) - 'publication_status' - 'updated_at')
            IS DISTINCT FROM (to_jsonb(OLD) - 'publication_status' - 'updated_at')
            OR (OLD.publication_status = 'published'
                AND NEW.publication_status NOT IN ('published', 'archived'))
            OR (OLD.publication_status = 'archived'
                AND NEW.publication_status <> 'archived') THEN
            RAISE EXCEPTION 'Published or archived JD content cannot be modified; create a new version'
                USING ERRCODE = '23514';
        END IF;
    END IF;
    NEW.updated_at := NOW();
    RETURN NEW;
END;
$$;

CREATE TRIGGER job_descriptions_guard_update
BEFORE UPDATE ON public.job_descriptions
FOR EACH ROW EXECUTE FUNCTION public.guard_job_description_update();

-- JD 筛选条件与发布校验

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
            AND evaluation_rule IS NOT NULL AND btrim(evaluation_rule) <> '')
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
            NEW.source, NEW.clarification, NEW.evaluation_rule)
            IS DISTINCT FROM
           (OLD.description, OLD.category, OLD.importance, OLD.evidence,
            OLD.source, OLD.clarification, OLD.evaluation_rule)
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
                    OR evaluation_rule IS NULL OR btrim(evaluation_rule) = '')
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

-- 简历原件与解析记录

CREATE TABLE public.resumes (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id         VARCHAR(64) NOT NULL,
    original_filename VARCHAR(255) NOT NULL CHECK (btrim(original_filename) <> ''),
    storage_key       TEXT NOT NULL UNIQUE CHECK (btrim(storage_key) <> ''),
    file_size_bytes   BIGINT NOT NULL CHECK (file_size_bytes > 0),
    file_sha256       TEXT NOT NULL CHECK (file_sha256 ~ '^[0-9a-f]{64}$'),
    page_count        INTEGER NOT NULL CHECK (page_count > 0),
    uploaded_by       UUID NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- 保留独立解析流程生成的历史数据。
    parse_status      VARCHAR(16) NOT NULL DEFAULT 'pending'
                      CHECK (parse_status IN ('pending', 'processing', 'completed', 'failed')),
    parse_attempt     UUID,
    parse_started_at  TIMESTAMPTZ,
    parse_finished_at TIMESTAMPTZ,
    text_blocks       JSONB,
    structured_data   JSONB,
    parse_error       TEXT,

    CONSTRAINT resume_parse_result_check CHECK (
        (parse_status = 'completed' AND text_blocks IS NOT NULL AND structured_data IS NOT NULL
            AND jsonb_typeof(text_blocks) = 'array' AND jsonb_typeof(structured_data) = 'object')
        OR (parse_status <> 'completed' AND text_blocks IS NULL AND structured_data IS NULL)
    ),
    CONSTRAINT resume_parse_error_check CHECK ((parse_status = 'failed') = (parse_error IS NOT NULL)),
    UNIQUE (tenant_id, id),
    FOREIGN KEY (tenant_id, uploaded_by) REFERENCES public.users (tenant_id, id)
);

-- 岗位简历审查任务

CREATE TABLE public.resume_reviews (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id     VARCHAR(64) NOT NULL,
    resume_id     UUID NOT NULL,
    position_id   UUID NOT NULL,
    jd_id         UUID NOT NULL,
    request_key   UUID NOT NULL,
    status        VARCHAR(16) NOT NULL DEFAULT 'pending'
                  CHECK (status IN ('pending', 'processing', 'completed', 'failed')),
    requested_by  UUID NOT NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    match_attempt UUID,
    match_started_at TIMESTAMPTZ,
    match_finished_at TIMESTAMPTZ,
    match_error TEXT,
    requirement_results JSONB,  -- 历史逐项匹配报告
    six_dimension_report JSONB, -- 当前六维度审查报告

    CONSTRAINT review_match_error_check CHECK ((status = 'failed') = (match_error IS NOT NULL)),
    CONSTRAINT review_six_dimension_result_check CHECK (
        (six_dimension_report IS NULL OR
            (status = 'completed' AND jsonb_typeof(six_dimension_report) = 'object'))
        AND (status <> 'completed' OR six_dimension_report IS NOT NULL OR requirement_results IS NOT NULL)
    ),
    UNIQUE (tenant_id, request_key),
    FOREIGN KEY (tenant_id, resume_id) REFERENCES public.resumes (tenant_id, id),
    FOREIGN KEY (tenant_id, position_id, jd_id)
        REFERENCES public.job_descriptions (tenant_id, position_id, id),
    FOREIGN KEY (tenant_id, requested_by) REFERENCES public.users (tenant_id, id)
);

CREATE INDEX resume_reviews_position_idx
    ON public.resume_reviews (tenant_id, position_id, created_at DESC, id DESC);

CREATE FUNCTION public.keep_resume_review_input() RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    IF (NEW.tenant_id, NEW.position_id, NEW.jd_id, NEW.resume_id, NEW.request_key)
       IS DISTINCT FROM (OLD.tenant_id, OLD.position_id, OLD.jd_id, OLD.resume_id, OLD.request_key) THEN
        RAISE EXCEPTION 'Review inputs are fixed; create a new review' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER resume_review_input_guard BEFORE UPDATE ON public.resume_reviews
FOR EACH ROW EXECUTE FUNCTION public.keep_resume_review_input();

-- JD 人工审核检查点（langgraph-checkpoint-postgres 3.2.1）

CREATE SCHEMA jd_hitl;

SET LOCAL search_path TO jd_hitl;

CREATE TABLE checkpoint_migrations (
    v INTEGER PRIMARY KEY
);

CREATE TABLE checkpoints (
    thread_id TEXT NOT NULL,
    checkpoint_ns TEXT NOT NULL DEFAULT '',
    checkpoint_id TEXT NOT NULL,
    parent_checkpoint_id TEXT,
    type TEXT,
    checkpoint JSONB NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}',
    PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id)
);

CREATE TABLE checkpoint_blobs (
    thread_id TEXT NOT NULL,
    checkpoint_ns TEXT NOT NULL DEFAULT '',
    channel TEXT NOT NULL,
    version TEXT NOT NULL,
    type TEXT NOT NULL,
    blob BYTEA,
    PRIMARY KEY (thread_id, checkpoint_ns, channel, version)
);

CREATE TABLE checkpoint_writes (
    thread_id TEXT NOT NULL,
    checkpoint_ns TEXT NOT NULL DEFAULT '',
    checkpoint_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    idx INTEGER NOT NULL,
    channel TEXT NOT NULL,
    type TEXT,
    blob BYTEA NOT NULL,
    task_path TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id, task_id, idx)
);

CREATE INDEX checkpoints_thread_id_idx ON checkpoints(thread_id);

CREATE INDEX checkpoint_blobs_thread_id_idx ON checkpoint_blobs(thread_id);

CREATE INDEX checkpoint_writes_thread_id_idx ON checkpoint_writes(thread_id);

-- 记录已包含的检查点迁移版本，供 LangGraph 识别。
INSERT INTO checkpoint_migrations (v) SELECT generate_series(0, 9);

COMMIT;
