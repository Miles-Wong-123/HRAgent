-- 岗位表：在公司、用户、部门表建立后手动执行。不会自动执行或删除历史数据。
BEGIN;
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
COMMIT;
