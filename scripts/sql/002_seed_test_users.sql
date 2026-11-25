-- 仅用于本地登录测试，在 001_users.sql 成功后手动执行。
-- 账号：admin_test、hr_test；两者测试密码均为 HrAgent-Test123!
-- 数据库只保存 bcrypt 哈希；请勿将这些公开的测试账号用于正式环境。
-- 重复执行按公司和用户名跳过，不重置已有账号的密码、角色或停用状态。
BEGIN;

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

COMMIT;
