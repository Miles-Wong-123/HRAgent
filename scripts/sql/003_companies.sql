-- 公司管理：先执行本文件，再执行 004_seed_test_company.sql。
-- 不修改已有用户的 ID、密码或 tenant_id；不自动从用户数据推断公司名称。
BEGIN;

CREATE TABLE public.companies (
    -- 与 users.tenant_id 对应，保留现有 company_demo 等公司标识。
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

-- 暂不检查历史用户，允许下一份脚本先补齐测试公司。
-- 新增/更改用户的公司关联仍受此外键约束。
ALTER TABLE public.users
    ADD CONSTRAINT users_company_fk FOREIGN KEY (tenant_id)
    REFERENCES public.companies (id) ON DELETE RESTRICT NOT VALID;

COMMIT;
