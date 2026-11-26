-- 部门管理建表脚本，在 003、004 已完成后执行。
-- 不删除或修改已有公司、用户。重复执行会报错，不覆盖已有部门表。
BEGIN;

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
    -- 为后续岗位使用公司 + 部门的组合外键预留唯一约束。
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

COMMIT;
