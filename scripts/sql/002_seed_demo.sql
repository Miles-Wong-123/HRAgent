-- 可选的本地开发数据，在 001_schema.sql 建表后执行。
-- admin_test 和 hr_test 的测试密码均为 HrAgent-Test123!。仅限本地开发。
-- 相同公司、账号或部门已存在时保留原记录。
BEGIN;

INSERT INTO public.companies (id, name, short_name, description)
VALUES ('company_demo', '深圳兆珑科技有限公司', '兆珑科技', NULL)
ON CONFLICT (id) DO NOTHING;

INSERT INTO public.users (
    tenant_id, username, email, password_hash, display_name, role, is_active
)
VALUES
    (
        'company_demo',
        'admin_test',
        'admin_test@example.com',
        '$2b$12$4t/i5fP9UkrTIUpjG6dZOOOFfCb/OqfYupJiRFN.X5WNxQ3hyLisy',
        '测试管理员',
        'admin',
        TRUE
    ),
    (
        'company_demo',
        'hr_test',
        'hr_test@example.com',
        '$2b$12$4t/i5fP9UkrTIUpjG6dZOOOFfCb/OqfYupJiRFN.X5WNxQ3hyLisy',
        '测试 HR',
        'hr',
        TRUE
    )
ON CONFLICT (tenant_id, username) DO NOTHING;

INSERT INTO public.departments (tenant_id, name, description)
VALUES
    ('company_demo', '技术部', '负责软件研发与技术维护'),
    ('company_demo', '人力资源部', '负责招聘与人事管理'),
    ('company_demo', '财务部', '负责财务核算与管理')
ON CONFLICT (tenant_id, name) DO NOTHING;

COMMIT;
