-- JD 版本表。在 hragent 数据库中执行，前提是 007_positions.sql 已完成。
-- 本文件只创建表、索引和触发器；不调用 Agent，不插入示例数据。
-- 一次性结构脚本：重复执行会报错，不覆盖已有表。
BEGIN;

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

COMMIT;
