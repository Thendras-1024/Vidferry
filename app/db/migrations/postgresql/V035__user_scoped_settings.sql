-- 将历史全局处理配置归属最早的有效管理员，后续配置按用户命名空间保存。
DO $$
DECLARE
    administrator_id BIGINT;
BEGIN
    SELECT id INTO administrator_id
    FROM auth_users
    WHERE role = 'admin' AND status = 'active'
    ORDER BY created_at, id
    LIMIT 1;

    IF administrator_id IS NOT NULL THEN
        INSERT INTO app_settings (key, value, updated_at)
        SELECT 'youtube_workflow_settings:' || administrator_id::TEXT, value, CURRENT_TIMESTAMP
        FROM app_settings
        WHERE key = 'youtube_workflow_settings'
        ON CONFLICT (key) DO NOTHING;

        DELETE FROM app_settings WHERE key = 'youtube_workflow_settings';
    END IF;
END $$;
