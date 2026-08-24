from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_workspace_isolation_migration_repairs_global_group_index_and_orphan_sessions():
    migration = (ROOT / "app/db/migrations/postgresql/V034__repair_multi_user_workspace_isolation.sql").read_text(encoding="utf-8")

    assert "DROP INDEX IF EXISTS idx_youtube_video_groups_name_ci" in migration
    assert "youtube_video_groups (owner_user_id, LOWER(name))" in migration
    assert "WHERE role = 'admin' AND status = 'active'" in migration
    assert "UPDATE agent_sessions" in migration
    assert "WHERE owner_user_id IS NULL" in migration
    assert "ALTER COLUMN owner_user_id SET NOT NULL" in migration


def test_frontend_user_scopes_agent_and_publish_drafts_and_clears_legacy_keys():
    storage = (ROOT / "sau_frontend/src/utils/userWorkspaceStorage.js").read_text(encoding="utf-8")
    agent = (ROOT / "sau_frontend/src/composables/useAgentWorkspace.js").read_text(encoding="utf-8")
    publish = (ROOT / "sau_frontend/src/views/PublishCenter.vue").read_text(encoding="utf-8")
    app = (ROOT / "sau_frontend/src/App.vue").read_text(encoding="utf-8")

    assert "vidferry:user:${ownerId}:${name}" in storage
    assert "removeLegacyWorkspaceStorage" in storage
    assert "const agentStorageKey = name => userWorkspaceStorageKey(activeUserId.value, name)" in agent
    assert "localStorage.getItem('vidferry:agent-session-id')" not in agent
    assert "userWorkspaceStorageKey(userStore.userInfo?.id, PUBLISH_DRAFT_STORAGE_NAME)" in publish
    assert "activateAgentWorkspace(userStore.userInfo?.id)" in app
    assert "clearAgentWorkspace()" in app


def test_user_scoped_settings_and_agent_routes_are_not_global():
    migration = (ROOT / "app/db/migrations/postgresql/V035__user_scoped_settings.sql").read_text(encoding="utf-8")
    settings = (ROOT / "app/core/settings_service.py").read_text(encoding="utf-8")
    agent_settings = (ROOT / "app/core/agent_settings_service.py").read_text(encoding="utf-8")
    prompts = (ROOT / "app/core/llm_prompts.py").read_text(encoding="utf-8")
    agent_api = (ROOT / "app/api/agent_soul.py").read_text(encoding="utf-8")
    youtube_api = (ROOT / "app/api/youtube.py").read_text(encoding="utf-8")

    assert "youtube_workflow_settings:<owner_user_id>" not in settings
    assert "WORKFLOW_SETTINGS_KEY_PREFIX = \"youtube_workflow_settings:\"" in settings
    assert "agent_soul:" in agent_settings
    assert "youtube_workflow_settings:" in migration
    assert "get_agent_soul(owner_user_id)" in prompts or "get_agent_soul(owner_user_id)" in agent_settings
    assert "@app.route(\"/agent/soul\", methods=[\"GET\"])" in agent_api
    assert "@app.route(\"/agent/soul\", methods=[\"PUT\"])" in agent_api
    assert "/admin/agent-soul" not in agent_api
    assert "get_workflow_settings(_current_account_owner_id())" in youtube_api
    assert "update_workflow_settings(_current_account_owner_id(), payload)" in youtube_api


def test_subtitle_audit_routes_are_user_scoped():
    api = (ROOT / "app/api/subtitle_audit.py").read_text(encoding="utf-8")
    service = (ROOT / "app/core/subtitle_audit_service.py").read_text(encoding="utf-8")
    frontend = (ROOT / "sau_frontend/src/api/subtitleAudit.js").read_text(encoding="utf-8")

    assert "@app.route('/subtitle-audits', methods=['GET'])" in api
    assert "@app.route('/subtitle-audits/<job_id>', methods=['GET'])" in api
    assert "/admin/subtitle-audits" not in api
    assert "j.owner_user_id = %s" in service
    assert "owner_user_id = %s AND id IN" in service
    assert "/admin/subtitle-audits" not in frontend


def test_frontend_permission_contract_keeps_only_global_admin_pages_locked():
    router = (ROOT / "sau_frontend/src/router/index.js").read_text(encoding="utf-8")
    agent_api = (ROOT / "sau_frontend/src/api/agent.js").read_text(encoding="utf-8")
    youtube_api = (ROOT / "sau_frontend/src/api/youtube.js").read_text(encoding="utf-8")

    assert router.count("meta: { requiresAdmin: true }") == 2
    assert "return request.get('/agent/soul')" in agent_api
    assert "return request.put('/agent/soul', { content })" in agent_api
    assert "'/youtube/title-translations/backfill'" in youtube_api
    assert "'/admin/youtube/title-translations/backfill'" not in youtube_api


def test_agent_runs_are_user_scoped_and_migrated_to_non_null_owner():
    migration = (ROOT / "app/db/migrations/postgresql/V037__agent_run_ownership.sql").read_text(encoding="utf-8")
    runs = (ROOT / "app/core/agent_memory_runs.py").read_text(encoding="utf-8")
    summaries = (ROOT / "app/core/agent_memory_summaries.py").read_text(encoding="utf-8")
    sessions = (ROOT / "app/core/agent_memory_sessions.py").read_text(encoding="utf-8")

    assert "ADD COLUMN IF NOT EXISTS owner_user_id BIGINT" in migration
    assert "ALTER COLUMN owner_user_id SET NOT NULL" in migration
    assert "session_id" in migration and "file_records" in migration
    assert "idx_agent_runs_owner_created" in migration
    assert "r.owner_user_id = %s" in runs
    assert "r.run_type != 'chat'" not in runs
    assert "owner_user_id" in summaries
    assert "DELETE FROM agent_runs WHERE session_id = %s AND owner_user_id = %s" in sessions
    assert "if owner_user_id is None:\n                return False" in sessions


def test_default_group_index_repair_is_user_scoped():
    migration = (ROOT / "app/db/migrations/postgresql/V036__repair_video_group_default_index.sql").read_text(encoding="utf-8")

    assert "DROP INDEX IF EXISTS idx_youtube_video_groups_default" in migration
    assert "ON youtube_video_groups (owner_user_id)" in migration
    assert "WHERE is_default = 1" in migration


def test_subtitle_cleanup_preserves_published_identity_and_reports_counts():
    service = (ROOT / "app/core/subtitle_audit_service.py").read_text(encoding="utf-8")
    frontend = (ROOT / "sau_frontend/src/views/SubtitleAudit.vue").read_text(encoding="utf-8")

    assert "waiting_publish" in service
    assert "scheduled_publish_tasks" in service
    assert "unknown', 'pending', 'running'" in service
    assert "confirmed', 'reused'" in service
    assert "deletedJobCount" in service
    assert "deletedMaterialCount" in service
    assert "retainedPublishedPlatformCount" in service
    assert "视频线索和已发布平台记录会保留" in frontend
    assert "deletedCount" in frontend
