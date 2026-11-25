-- 在 003_companies.sql 之后执行；仅插入本地测试公司。
-- 如存在其他 tenant_id，先手动插入这些标识对应的公司，再执行本文件。
-- 验证失败则整个事务回滚，不删除或更改已有账号。
BEGIN;

INSERT INTO public.companies (id, name, short_name, description)
VALUES ('company_demo', 'HR 系统测试公司', '测试公司', '仅用于本地开发和接口验证')
ON CONFLICT (id) DO NOTHING;

ALTER TABLE public.users VALIDATE CONSTRAINT users_company_fk;

COMMIT;
