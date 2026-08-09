"""数据库表定义与迁移。"""

import json

from app.config import YOUTUBE_DEFAULT_GROUP_NAME
from app.publishing import platform_type_from_name


def _existing_columns(cursor, table_name):
    cursor.execute(f"PRAGMA table_info({table_name})")
    return {row[1] for row in cursor.fetchall()}


def _add_missing_columns(cursor, table_name, columns):
    existing_columns = _existing_columns(cursor, table_name)
    for column, definition in columns.items():
        if column not in existing_columns:
            cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {column} {definition}")


def ensure_core_tables(cursor):
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS user_info (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        type INTEGER NOT NULL,
        filePath TEXT NOT NULL,
        userName TEXT NOT NULL,
        status INTEGER DEFAULT 0,
        owner_user_id INTEGER
    )
    ''')
    _add_missing_columns(cursor, "user_info", {"owner_user_id": "INTEGER"})
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_user_info_owner_type ON user_info(owner_user_id, type, id)")
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS app_settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS publish_account_groups (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        owner_user_id INTEGER,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    _add_missing_columns(cursor, "publish_account_groups", {"owner_user_id": "INTEGER"})
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_publish_account_groups_owner ON publish_account_groups(owner_user_id, id)")
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS publish_account_group_members (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        group_id INTEGER NOT NULL,
        account_id INTEGER NOT NULL,
        platform_type INTEGER NOT NULL,
        UNIQUE(group_id, platform_type),
        UNIQUE(group_id, account_id)
    )
    ''')
    cursor.execute('DROP INDEX IF EXISTS idx_publish_account_groups_name_lower')
    cursor.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_publish_account_groups_owner_name_lower ON publish_account_groups(owner_user_id, LOWER(name))')


def ensure_file_record_tables(cursor):
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS file_records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        asset_id TEXT,
        filename TEXT NOT NULL,
        original_filename TEXT,
        filesize REAL,
        upload_time DATETIME DEFAULT CURRENT_TIMESTAMP,
        file_path TEXT,
        storage_key TEXT,
        storage_backend TEXT DEFAULT 'local',
        source_type TEXT DEFAULT 'manual_upload',
        source_video_id TEXT,
        status TEXT DEFAULT 'ready',
        duration TEXT,
        duration_seconds REAL DEFAULT 0,
        metadata TEXT DEFAULT '{}'
    )
    ''')
    _add_missing_columns(cursor, "file_records", {
        "asset_id": "TEXT",
        "original_filename": "TEXT",
        "storage_key": "TEXT",
        "storage_backend": "TEXT DEFAULT 'local'",
        "source_type": "TEXT DEFAULT 'manual_upload'",
        "source_video_id": "TEXT",
        "status": "TEXT DEFAULT 'ready'",
        "duration": "TEXT",
        "duration_seconds": "REAL DEFAULT 0",
        "metadata": "TEXT DEFAULT '{}'",
    })
    cursor.execute("UPDATE file_records SET asset_id = lower(hex(randomblob(16))) WHERE asset_id IS NULL OR asset_id = ''")
    cursor.execute("UPDATE file_records SET original_filename = filename WHERE original_filename IS NULL OR original_filename = ''")
    cursor.execute("UPDATE file_records SET storage_key = file_path WHERE storage_key IS NULL OR storage_key = ''")
    cursor.execute("UPDATE file_records SET storage_backend = 'local' WHERE storage_backend IS NULL OR storage_backend = ''")
    cursor.execute("UPDATE file_records SET source_type = 'manual_upload' WHERE source_type IS NULL OR source_type = ''")
    cursor.execute("UPDATE file_records SET status = 'ready' WHERE status IS NULL OR status = ''")
    cursor.execute("UPDATE file_records SET metadata = '{}' WHERE metadata IS NULL OR metadata = ''")
    cursor.execute("""
    SELECT id, metadata FROM file_records
    WHERE (source_video_id IS NULL OR source_video_id = '')
      AND source_type IN ('youtube_download', 'youtube_processed')
    """)
    for row_id, metadata_text in cursor.fetchall():
        try:
            metadata = json.loads(metadata_text or "{}")
        except (TypeError, ValueError):
            metadata = {}
        video_id = str(metadata.get("videoId") or metadata.get("sourceVideoId") or "").strip()
        if video_id:
            cursor.execute("UPDATE file_records SET source_video_id = ? WHERE id = ?", (video_id, row_id))
    cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_file_records_asset_id ON file_records(asset_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_file_records_source_video_id ON file_records(source_video_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_file_records_source_type ON file_records(source_type)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_file_records_source_type_upload ON file_records(source_type, upload_time, id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_file_records_video_type ON file_records(source_video_id, source_type)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_file_records_upload_order ON file_records(upload_time DESC, id DESC)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_file_records_status_upload ON file_records(status, upload_time DESC, id DESC)")


def ensure_agent_tables(cursor):
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS agent_sessions (
        id TEXT PRIMARY KEY,
        title TEXT,
        source TEXT NOT NULL DEFAULT 'web',
        source_key TEXT DEFAULT '',
        context TEXT DEFAULT '{}',
        summary TEXT DEFAULT '{}',
        summary_through_id INTEGER DEFAULT 0,
        message_count INTEGER DEFAULT 0,
        deleted_at DATETIME,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    _add_missing_columns(cursor, "agent_sessions", {
        "owner_user_id": "INTEGER",
        "source": "TEXT NOT NULL DEFAULT 'web'",
        "source_key": "TEXT DEFAULT ''",
        "summary": "TEXT DEFAULT '{}'",
        "summary_through_id": "INTEGER DEFAULT 0",
        "message_count": "INTEGER DEFAULT 0",
        "deleted_at": "DATETIME",
    })
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_agent_sessions_updated ON agent_sessions(deleted_at, updated_at DESC)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_agent_sessions_source ON agent_sessions(deleted_at, source, updated_at DESC)")
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS agent_session_bindings (
        source TEXT NOT NULL,
        source_key TEXT NOT NULL,
        session_id TEXT NOT NULL,
        owner_user_id INTEGER NOT NULL,
        updated_at DATETIME NOT NULL,
        PRIMARY KEY (source, source_key)
    )
    ''')
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_agent_session_bindings_session ON agent_session_bindings(session_id)")
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS agent_session_locks (
        session_id TEXT PRIMARY KEY,
        owner_id TEXT NOT NULL,
        expires_at REAL NOT NULL
    )
    ''')
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_agent_session_locks_expiry ON agent_session_locks(expires_at)")
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS agent_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT NOT NULL,
        role TEXT NOT NULL,
        content TEXT NOT NULL,
        context TEXT DEFAULT '{}',
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_agent_messages_session ON agent_messages(session_id, id)")
    cursor.execute("UPDATE agent_sessions SET message_count = (SELECT COUNT(*) FROM agent_messages WHERE agent_messages.session_id = agent_sessions.id) WHERE deleted_at IS NULL")
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS agent_runs (
        id TEXT PRIMARY KEY,
        session_id TEXT,
        run_type TEXT NOT NULL,
        subject_type TEXT DEFAULT '',
        subject_id TEXT DEFAULT '',
        status TEXT DEFAULT 'success',
        decision TEXT,
        severity TEXT,
        content_hash TEXT,
        input_summary TEXT DEFAULT '{}',
        output TEXT DEFAULT '{}',
        model TEXT,
        duration_ms INTEGER DEFAULT 0,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    _add_missing_columns(cursor, "agent_runs", {
        "subject_type": "TEXT DEFAULT ''",
        "subject_id": "TEXT DEFAULT ''",
    })
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_agent_runs_session ON agent_runs(session_id, created_at)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_agent_runs_hash ON agent_runs(content_hash, run_type)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_agent_runs_subject ON agent_runs(run_type, subject_type, subject_id, created_at DESC)")
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS agent_rules (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        category TEXT NOT NULL,
        severity TEXT NOT NULL,
        pattern TEXT,
        description TEXT,
        enabled INTEGER DEFAULT 1,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_agent_rules_enabled ON agent_rules(enabled, category)")
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS agent_memory_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        memory_type TEXT NOT NULL,
        title TEXT,
        content TEXT NOT NULL,
        metadata TEXT DEFAULT '{}',
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_agent_memory_type ON agent_memory_items(memory_type, updated_at)")


def ensure_auth_tables(cursor):
    cursor.execute('''CREATE TABLE IF NOT EXISTS auth_users (
        id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL UNIQUE,
        display_name TEXT NOT NULL, password_hash TEXT NOT NULL, role TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'active', must_change_password INTEGER NOT NULL DEFAULT 1,
        password_changed_at DATETIME, created_by INTEGER, failed_login_count INTEGER NOT NULL DEFAULT 0,
        locked_until DATETIME, last_login_at DATETIME, created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL
    )''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS auth_sessions (
        token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL, created_at DATETIME NOT NULL,
        last_seen_at DATETIME NOT NULL, idle_expires_at DATETIME NOT NULL,
        absolute_expires_at DATETIME NOT NULL, ip_address TEXT, user_agent TEXT, revoked_at DATETIME,
        FOREIGN KEY(user_id) REFERENCES auth_users(id) ON DELETE CASCADE
    )''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS auth_audit_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT, actor_user_id INTEGER, action TEXT NOT NULL,
        target_type TEXT, target_id TEXT, result TEXT NOT NULL, ip_address TEXT, user_agent TEXT,
        details TEXT NOT NULL DEFAULT '{}', created_at DATETIME NOT NULL,
        FOREIGN KEY(actor_user_id) REFERENCES auth_users(id) ON DELETE SET NULL
    )''')
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_auth_sessions_user ON auth_sessions(user_id, revoked_at)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_auth_audit_created ON auth_audit_logs(created_at DESC, id DESC)")
    cursor.execute('''CREATE TABLE IF NOT EXISTS task_acknowledgements (
        user_id INTEGER NOT NULL,
        task_key TEXT NOT NULL,
        acknowledged_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (user_id, task_key)
    )''')
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_task_acknowledgements_user_time ON task_acknowledgements(user_id, acknowledged_at DESC)")


def ensure_scheduled_publish_tables(cursor):
    cursor.execute('''CREATE TABLE IF NOT EXISTS scheduled_publish_tasks (
        id TEXT PRIMARY KEY, video_id TEXT NOT NULL, material_id INTEGER NOT NULL, file_path TEXT NOT NULL,
        scheduled_at DATETIME NOT NULL, status TEXT NOT NULL DEFAULT 'pending', overdue INTEGER NOT NULL DEFAULT 0,
        message TEXT, risk_override TEXT DEFAULT '{}', created_at DATETIME NOT NULL, started_at DATETIME,
        finished_at DATETIME, canceled_at DATETIME, updated_at DATETIME NOT NULL
    )''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS scheduled_publish_targets (
        id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL, platform_type INTEGER NOT NULL,
        account_id INTEGER, account_name TEXT, settings TEXT NOT NULL DEFAULT '{}', status TEXT NOT NULL DEFAULT 'pending',
        message TEXT, duration_ms INTEGER NOT NULL DEFAULT 0, started_at DATETIME, finished_at DATETIME,
        updated_at DATETIME NOT NULL, FOREIGN KEY(task_id) REFERENCES scheduled_publish_tasks(id) ON DELETE CASCADE
    )''')
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_scheduled_publish_tasks_due ON scheduled_publish_tasks(status, scheduled_at)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_scheduled_publish_targets_task ON scheduled_publish_targets(task_id, id)")


def ensure_workflow_event_tables(cursor):
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS youtube_workflow_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id TEXT NOT NULL,
        video_id TEXT,
        stage TEXT NOT NULL,
        stage_label TEXT,
        status TEXT DEFAULT 'running',
        message TEXT,
        input_file_path TEXT,
        output_file_path TEXT,
        input_size_mb REAL DEFAULT 0,
        output_size_mb REAL DEFAULT 0,
        started_at DATETIME,
        ended_at DATETIME,
        duration_seconds REAL DEFAULT 0,
        cloud_model TEXT,
        prompt_tokens INTEGER DEFAULT 0,
        completion_tokens INTEGER DEFAULT 0,
        total_tokens INTEGER DEFAULT 0,
        cloud_latency_ms REAL DEFAULT 0,
        metadata TEXT DEFAULT '{}',
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    _add_missing_columns(cursor, "youtube_workflow_events", {
        "video_id": "TEXT",
        "stage_label": "TEXT",
        "status": "TEXT DEFAULT 'running'",
        "message": "TEXT",
        "input_file_path": "TEXT",
        "output_file_path": "TEXT",
        "input_size_mb": "REAL DEFAULT 0",
        "output_size_mb": "REAL DEFAULT 0",
        "started_at": "DATETIME",
        "ended_at": "DATETIME",
        "duration_seconds": "REAL DEFAULT 0",
        "cloud_model": "TEXT",
        "prompt_tokens": "INTEGER DEFAULT 0",
        "completion_tokens": "INTEGER DEFAULT 0",
        "total_tokens": "INTEGER DEFAULT 0",
        "cloud_latency_ms": "REAL DEFAULT 0",
        "metadata": "TEXT DEFAULT '{}'",
        "created_at": "DATETIME DEFAULT CURRENT_TIMESTAMP",
    })
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_youtube_workflow_events_job_id ON youtube_workflow_events(job_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_youtube_workflow_events_video_id ON youtube_workflow_events(video_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_youtube_workflow_events_stage ON youtube_workflow_events(stage)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_youtube_workflow_events_started ON youtube_workflow_events(started_at, id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_youtube_workflow_events_job_started ON youtube_workflow_events(job_id, started_at DESC, id DESC)")


def ensure_workflow_llm_usage_tables(cursor):
    """保存可归属到视频工作流的单次模型请求。"""
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS youtube_workflow_llm_usage_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        workflow_event_id INTEGER,
        job_id TEXT NOT NULL,
        video_id TEXT,
        stage TEXT,
        operation TEXT,
        provider TEXT,
        model TEXT,
        status TEXT NOT NULL DEFAULT 'success',
        attempt INTEGER NOT NULL DEFAULT 1,
        prompt_tokens INTEGER NOT NULL DEFAULT 0,
        completion_tokens INTEGER NOT NULL DEFAULT 0,
        total_tokens INTEGER NOT NULL DEFAULT 0,
        latency_ms REAL NOT NULL DEFAULT 0,
        error_message TEXT,
        error_category TEXT,
        violations TEXT,
        raw_output TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    _add_missing_columns(cursor, "youtube_workflow_llm_usage_events", {
        "error_category": "TEXT",
        "violations": "TEXT",
        "raw_output": "TEXT",
    })
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_workflow_llm_usage_job ON youtube_workflow_llm_usage_events(job_id, created_at DESC, id DESC)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_workflow_llm_usage_event ON youtube_workflow_llm_usage_events(workflow_event_id, id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_workflow_llm_usage_model_time ON youtube_workflow_llm_usage_events(model, created_at, id)")


def ensure_subtitle_audit_tables(cursor):
    """保存每次字幕处理的初译和 LLM 修订审查快照。"""
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS youtube_subtitle_audits (
        job_id TEXT PRIMARY KEY,
        video_id TEXT,
        video_title TEXT,
        target_language TEXT,
        initial_segments TEXT NOT NULL DEFAULT '[]',
        reviewed_segments TEXT NOT NULL DEFAULT '[]',
        review_status TEXT NOT NULL DEFAULT 'unknown',
        fallback_segment_count INTEGER NOT NULL DEFAULT 0,
        review_batches TEXT NOT NULL DEFAULT '[]',
        saved_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    _add_missing_columns(cursor, "youtube_subtitle_audits", {
        "video_id": "TEXT",
        "video_title": "TEXT",
        "target_language": "TEXT",
        "initial_segments": "TEXT NOT NULL DEFAULT '[]'",
        "reviewed_segments": "TEXT NOT NULL DEFAULT '[]'",
        "review_status": "TEXT NOT NULL DEFAULT 'unknown'",
        "fallback_segment_count": "INTEGER NOT NULL DEFAULT 0",
        "review_batches": "TEXT NOT NULL DEFAULT '[]'",
        "saved_at": "DATETIME DEFAULT CURRENT_TIMESTAMP",
    })
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_subtitle_audits_video_saved ON youtube_subtitle_audits(video_id, saved_at DESC)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_subtitle_audits_saved ON youtube_subtitle_audits(saved_at DESC)")


def ensure_published_youtube_material_tables(cursor):
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS published_youtube_materials (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        video_id TEXT,
        source_url TEXT,
        title TEXT,
        platform TEXT,
        platform_type INTEGER DEFAULT 0,
        account_file TEXT,
        account_count INTEGER DEFAULT 0,
        material_id INTEGER,
        filename TEXT,
        file_path TEXT,
        filesize REAL DEFAULT 0,
        thumbnail TEXT,
        channel TEXT,
        subscribers TEXT,
        source_published_at TEXT,
        publish_title TEXT,
        metadata TEXT DEFAULT '{}',
        published_at DATETIME,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    _add_missing_columns(cursor, "published_youtube_materials", {
        "video_id": "TEXT",
        "source_url": "TEXT",
        "title": "TEXT",
        "platform": "TEXT",
        "platform_type": "INTEGER DEFAULT 0",
        "account_file": "TEXT",
        "account_count": "INTEGER DEFAULT 0",
        "material_id": "INTEGER",
        "filename": "TEXT",
        "file_path": "TEXT",
        "filesize": "REAL DEFAULT 0",
        "thumbnail": "TEXT",
        "channel": "TEXT",
        "subscribers": "TEXT",
        "source_published_at": "TEXT",
        "publish_title": "TEXT",
        "metadata": "TEXT DEFAULT '{}'",
        "published_at": "DATETIME",
        "created_at": "DATETIME DEFAULT CURRENT_TIMESTAMP",
        "publish_task_id": "TEXT",
        "status": "TEXT DEFAULT 'success'",
        "message": "TEXT",
        "duration_ms": "INTEGER DEFAULT 0",
        "account_name": "TEXT",
        "deleted_at": "DATETIME",
        "updated_at": "DATETIME",
    })
    cursor.execute("UPDATE published_youtube_materials SET status = 'success' WHERE status IS NULL OR status = ''")
    cursor.execute("""
    UPDATE published_youtube_materials
    SET updated_at = COALESCE(updated_at, published_at, created_at, CURRENT_TIMESTAMP)
    WHERE updated_at IS NULL OR updated_at = ''
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_published_youtube_materials_video_id ON published_youtube_materials(video_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_published_youtube_materials_source_url ON published_youtube_materials(source_url)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_published_youtube_materials_published_at ON published_youtube_materials(published_at)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_published_youtube_materials_task ON published_youtube_materials(publish_task_id, deleted_at)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_published_youtube_materials_status ON published_youtube_materials(status, deleted_at)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_published_youtube_materials_updated ON published_youtube_materials(updated_at, id)")
    cursor.execute("SELECT id, platform FROM published_youtube_materials WHERE COALESCE(platform_type, 0) = 0")
    for row_id, platform in cursor.fetchall():
        inferred_platform_type = platform_type_from_name(platform)
        if inferred_platform_type:
            cursor.execute(
                "UPDATE published_youtube_materials SET platform_type = ? WHERE id = ?",
                (inferred_platform_type, row_id),
            )
    cursor.execute("DROP INDEX IF EXISTS idx_published_youtube_materials_video_platform")
    cursor.execute('''
    CREATE UNIQUE INDEX IF NOT EXISTS idx_published_youtube_materials_video_platform
    ON published_youtube_materials(video_id, platform_type)
    WHERE video_id IS NOT NULL AND video_id != ''
      AND platform_type IS NOT NULL AND platform_type != 0
      AND deleted_at IS NULL
    ''')


def ensure_youtube_video_group_table(cursor):
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS youtube_video_groups (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL COLLATE NOCASE UNIQUE,
        is_default INTEGER NOT NULL DEFAULT 0 CHECK (is_default IN (0, 1)),
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    cursor.execute('''
    CREATE UNIQUE INDEX IF NOT EXISTS idx_youtube_video_groups_default
    ON youtube_video_groups(is_default) WHERE is_default = 1
    ''')
    cursor.execute("SELECT id FROM youtube_video_groups WHERE is_default = 1 LIMIT 1")
    row = cursor.fetchone()
    if not row:
        cursor.execute(
            "INSERT INTO youtube_video_groups (name, is_default) VALUES (?, 1)",
            (YOUTUBE_DEFAULT_GROUP_NAME,),
        )
        return cursor.lastrowid
    return int(row[0])


def ensure_youtube_video_table(cursor):
    default_group_id = ensure_youtube_video_group_table(cursor)
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS youtube_videos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        video_id TEXT UNIQUE NOT NULL,
        title TEXT,
        channel TEXT,
        subscribers TEXT,
        published_at TEXT,
        url TEXT NOT NULL,
        thumbnail TEXT,
        duration TEXT,
        query TEXT,
        download_status INTEGER DEFAULT 0,
        publish_status INTEGER DEFAULT 0,
        translate_status INTEGER DEFAULT 0,
        downloaded_file_path TEXT,
        processed_file_path TEXT,
        transcript_status INTEGER DEFAULT 0,
        transcript_file_path TEXT,
        transcript_language TEXT,
        analysis_status INTEGER DEFAULT 0,
        analysis_result TEXT,
        publish_draft TEXT,
        analysis_updated_at DATETIME,
        group_id INTEGER,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(group_id) REFERENCES youtube_video_groups(id) ON DELETE RESTRICT
    )
    ''')
    _add_missing_columns(cursor, "youtube_videos", {
        "translate_status": "INTEGER DEFAULT 0",
        "processed_file_path": "TEXT",
        "transcript_status": "INTEGER DEFAULT 0",
        "transcript_file_path": "TEXT",
        "transcript_language": "TEXT",
        "analysis_status": "INTEGER DEFAULT 0",
        "analysis_result": "TEXT",
        "publish_draft": "TEXT",
        "analysis_updated_at": "DATETIME",
        "group_id": "INTEGER",
    })
    cursor.execute(
        "UPDATE youtube_videos SET group_id = ? WHERE group_id IS NULL OR group_id NOT IN (SELECT id FROM youtube_video_groups)",
        (default_group_id,),
    )
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_youtube_videos_download_status ON youtube_videos(download_status)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_youtube_videos_publish_status ON youtube_videos(publish_status)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_youtube_videos_translate_status ON youtube_videos(translate_status)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_youtube_videos_analysis_status ON youtube_videos(analysis_status)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_youtube_videos_created ON youtube_videos(created_at, id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_youtube_videos_group_created ON youtube_videos(group_id, created_at DESC, id DESC)')
    ensure_youtube_search_tables(cursor)


def ensure_youtube_search_tables(cursor):
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS youtube_search_jobs (
        id TEXT PRIMARY KEY,
        query TEXT NOT NULL,
        requested INTEGER NOT NULL,
        found INTEGER DEFAULT 0,
        created_count INTEGER DEFAULT 0,
        duplicate_count INTEGER DEFAULT 0,
        skipped_count INTEGER DEFAULT 0,
        failed_count INTEGER DEFAULT 0,
        status TEXT NOT NULL,
        message TEXT,
        source TEXT,
        group_id INTEGER,
        group_name_snapshot TEXT,
        duration_min_seconds INTEGER,
        duration_max_seconds INTEGER,
        duration_filtered_count INTEGER DEFAULT 0,
        started_at DATETIME,
        finished_at DATETIME,
        created_at DATETIME NOT NULL,
        updated_at DATETIME NOT NULL
    )
    ''')
    _add_missing_columns(cursor, "youtube_search_jobs", {
        "group_id": "INTEGER",
        "group_name_snapshot": "TEXT",
        "duration_min_seconds": "INTEGER",
        "duration_max_seconds": "INTEGER",
        "duration_filtered_count": "INTEGER DEFAULT 0",
    })
    cursor.execute("SELECT id, name FROM youtube_video_groups WHERE is_default = 1 LIMIT 1")
    default_group = cursor.fetchone()
    if default_group:
        cursor.execute(
            '''
            UPDATE youtube_search_jobs
            SET group_id = ?
            WHERE (group_id IS NULL AND (group_name_snapshot IS NULL OR group_name_snapshot = ''))
               OR (group_id IS NOT NULL AND group_id NOT IN (SELECT id FROM youtube_video_groups))
            ''',
            (default_group[0],),
        )
        cursor.execute(
            "UPDATE youtube_search_jobs SET group_name_snapshot = ? WHERE group_name_snapshot IS NULL OR group_name_snapshot = ''",
            (default_group[1],),
        )
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS youtube_search_job_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id TEXT NOT NULL,
        ordinal INTEGER NOT NULL,
        video_id TEXT,
        title TEXT,
        decision TEXT NOT NULL,
        error TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(job_id, ordinal),
        FOREIGN KEY(job_id) REFERENCES youtube_search_jobs(id) ON DELETE CASCADE
    )
    ''')
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS youtube_video_deletions (
        video_id TEXT PRIMARY KEY,
        deleted_at DATETIME NOT NULL
    )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_youtube_search_jobs_status ON youtube_search_jobs(status, created_at)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_youtube_search_jobs_group_status ON youtube_search_jobs(group_id, status)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_youtube_search_job_items_job ON youtube_search_job_items(job_id, ordinal)')
    cursor.execute('''
    CREATE UNIQUE INDEX IF NOT EXISTS idx_youtube_search_job_items_video
    ON youtube_search_job_items(job_id, video_id)
    WHERE video_id IS NOT NULL AND video_id != ''
    ''')


def ensure_youtube_workflow_job_table(cursor):
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS youtube_workflow_jobs (
        id TEXT PRIMARY KEY,
        video_id TEXT,
        url TEXT NOT NULL,
        account TEXT,
        channel TEXT,
        subscribers TEXT,
        published_at TEXT,
        bilibili_account TEXT,
        bilibili_tid INTEGER DEFAULT 249,
        xiaohongshu_account TEXT,
        kuaishou_account TEXT,
        tencent_account TEXT,
        publish_to_douyin INTEGER DEFAULT 1,
        publish_to_bilibili INTEGER DEFAULT 0,
        publish_to_xiaohongshu INTEGER DEFAULT 0,
        publish_to_kuaishou INTEGER DEFAULT 0,
        publish_to_tencent INTEGER DEFAULT 0,
        process_version TEXT DEFAULT 'translation_v1',
        subtitle_language TEXT DEFAULT 'zh-CN',
        burn_profile TEXT DEFAULT 'stable',
        subtitle_size TEXT DEFAULT 'large',
        translator_label TEXT DEFAULT 'Vidferry翻译',
        watermark_enabled INTEGER DEFAULT 0,
        watermark_text TEXT DEFAULT '',
        highlight_count INTEGER DEFAULT 3,
        comment_burn_enabled INTEGER DEFAULT 0,
        comment_burn_count INTEGER DEFAULT 30,
        comment_translation_mode TEXT DEFAULT 'google_llm',
        cover_title TEXT DEFAULT '',
        cover_context TEXT DEFAULT '',
        cover_brand_name TEXT DEFAULT '',
        cover_brand_platform TEXT DEFAULT '',
        title TEXT,
        description TEXT,
        tags TEXT,
        schedule TEXT,
        status TEXT NOT NULL,
        step TEXT,
        message TEXT,
        source_file_path TEXT,
        processed_file_path TEXT,
        publish_command TEXT,
        publish_confirmation_required INTEGER DEFAULT 0,
        publish_confirmation_status TEXT DEFAULT '',
        content_risk TEXT DEFAULT '{}',
        progress REAL DEFAULT 0,
        speed TEXT,
        eta TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        started_at DATETIME,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    ''')
    _add_missing_columns(cursor, "youtube_workflow_jobs", {
        "progress": "REAL DEFAULT 0",
        "speed": "TEXT",
        "eta": "TEXT",
        "channel": "TEXT",
        "subscribers": "TEXT",
        "published_at": "TEXT",
        "bilibili_account": "TEXT",
        "bilibili_tid": "INTEGER DEFAULT 249",
        "xiaohongshu_account": "TEXT",
        "kuaishou_account": "TEXT",
        "tencent_account": "TEXT",
        "publish_to_douyin": "INTEGER DEFAULT 1",
        "publish_to_bilibili": "INTEGER DEFAULT 0",
        "publish_to_xiaohongshu": "INTEGER DEFAULT 0",
        "publish_to_kuaishou": "INTEGER DEFAULT 0",
        "publish_to_tencent": "INTEGER DEFAULT 0",
        "process_version": "TEXT DEFAULT 'translation_v1'",
        "subtitle_language": "TEXT DEFAULT 'zh-CN'",
        "burn_profile": "TEXT DEFAULT 'stable'",
        "subtitle_size": "TEXT DEFAULT 'large'",
        "translator_label": "TEXT DEFAULT 'Vidferry翻译'",
        "watermark_enabled": "INTEGER DEFAULT 0",
        "watermark_text": "TEXT DEFAULT ''",
        "highlight_count": "INTEGER DEFAULT 3",
        "comment_burn_enabled": "INTEGER DEFAULT 0",
        "comment_burn_count": "INTEGER DEFAULT 30",
        "comment_translation_mode": "TEXT DEFAULT 'google_llm'",
        "cover_title": "TEXT DEFAULT ''",
        "cover_context": "TEXT DEFAULT ''",
        "cover_brand_name": "TEXT DEFAULT ''",
        "cover_brand_platform": "TEXT DEFAULT ''",
        "error_code": "TEXT",
        "error_type": "TEXT",
        "error_reason": "TEXT",
        "error_detail": "TEXT",
        "interrupted_at": "DATETIME",
        "started_at": "DATETIME",
        "publish_confirmation_required": "INTEGER DEFAULT 0",
        "publish_confirmation_status": "TEXT DEFAULT ''",
        "publish_account_group_id": "INTEGER",
        "owner_user_id": "INTEGER",
        "content_risk": "TEXT DEFAULT '{}'",
    })
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_youtube_workflow_jobs_owner ON youtube_workflow_jobs(owner_user_id, updated_at DESC, created_at DESC)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_youtube_workflow_jobs_video_id ON youtube_workflow_jobs(video_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_youtube_workflow_jobs_status ON youtube_workflow_jobs(status)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_youtube_workflow_jobs_status_updated ON youtube_workflow_jobs(status, updated_at, created_at)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_youtube_workflow_jobs_video_updated ON youtube_workflow_jobs(video_id, updated_at, created_at)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_youtube_workflow_jobs_video_status_updated ON youtube_workflow_jobs(video_id, status, updated_at DESC, created_at DESC)')
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS youtube_workflow_locks (
        video_id TEXT NOT NULL,
        scope TEXT NOT NULL,
        job_id TEXT NOT NULL UNIQUE,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (video_id, scope)
    )
    ''')
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_youtube_workflow_locks_job_id ON youtube_workflow_locks(job_id)")
