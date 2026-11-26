-- 可选的本地测试数据，在 005_departments.sql 之后执行。
-- 依赖 004 中的 company_demo。重复执行不会覆盖同名部门或重新启用部门。
BEGIN;

INSERT INTO public.departments (tenant_id, name, description)
VALUES
    ('company_demo', '技术部', '负责软件研发与技术维护'),
    ('company_demo', '人力资源部', '负责招聘与人事管理'),
    ('company_demo', '财务部', '负责财务核算与管理')
ON CONFLICT (tenant_id, name) DO NOTHING;

COMMIT;
