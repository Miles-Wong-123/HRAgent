-- 登录测试所需的第一张业务表，适用于 PostgreSQL 15。
-- 在 hragent 数据库的 SQL Console 中手动执行，不在应用启动时执行。
-- 如果 public.users 已存在，本脚本报错并回滚，不覆盖或迁移旧表。
-- tenant_id 暂时保存公司标识；公司表及其外键在后续公司管理步骤补充。
BEGIN;

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

COMMIT;
