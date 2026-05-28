def init_database_tables():
    Path(BASE_DIR / "db").mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(_db_path()) as conn:
        cursor = conn.cursor()
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_info (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type INTEGER NOT NULL,
            filePath TEXT NOT NULL,
            userName TEXT NOT NULL,
            status INTEGER DEFAULT 0
        )
        ''')
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
        cursor.execute("PRAGMA table_info(file_records)")
        existing_columns = {row[1] for row in cursor.fetchall()}
        material_columns = {
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
        }
        for column, definition in material_columns.items():
            if column not in existing_columns:
                cursor.execute(f"ALTER TABLE file_records ADD COLUMN {column} {definition}")
        cursor.execute("UPDATE file_records SET asset_id = lower(hex(randomblob(16))) WHERE asset_id IS NULL OR asset_id = ''")
        cursor.execute("UPDATE file_records SET original_filename = filename WHERE original_filename IS NULL OR original_filename = ''")
        cursor.execute("UPDATE file_records SET storage_key = file_path WHERE storage_key IS NULL OR storage_key = ''")
        cursor.execute("UPDATE file_records SET storage_backend = 'local' WHERE storage_backend IS NULL OR storage_backend = ''")
        cursor.execute("UPDATE file_records SET source_type = 'manual_upload' WHERE source_type IS NULL OR source_type = ''")
        cursor.execute("UPDATE file_records SET status = 'ready' WHERE status IS NULL OR status = ''")
        cursor.execute("UPDATE file_records SET metadata = '{}' WHERE metadata IS NULL OR metadata = ''")
        cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_file_records_asset_id ON file_records(asset_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_file_records_source_video_id ON file_records(source_video_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_file_records_source_type ON file_records(source_type)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_file_records_source_type_upload ON file_records(source_type, upload_time, id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_file_records_video_type ON file_records(source_video_id, source_type)")
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS app_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        ''')
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
        cursor.execute("PRAGMA table_info(youtube_workflow_events)")
        existing_event_columns = {row[1] for row in cursor.fetchall()}
        event_columns = {
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
        }
        for column, definition in event_columns.items():
            if column not in existing_event_columns:
                cursor.execute(f"ALTER TABLE youtube_workflow_events ADD COLUMN {column} {definition}")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_youtube_workflow_events_job_id ON youtube_workflow_events(job_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_youtube_workflow_events_video_id ON youtube_workflow_events(video_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_youtube_workflow_events_stage ON youtube_workflow_events(stage)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_youtube_workflow_events_started ON youtube_workflow_events(started_at, id)")
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
        cursor.execute("PRAGMA table_info(published_youtube_materials)")
        existing_published_columns = {row[1] for row in cursor.fetchall()}
        published_columns = {
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
        }
        for column, definition in published_columns.items():
            if column not in existing_published_columns:
                cursor.execute(f"ALTER TABLE published_youtube_materials ADD COLUMN {column} {definition}")
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
        for row in cursor.fetchall():
            row_id, platform = row
            inferred_platform_type = platform_type_from_name(platform)
            if inferred_platform_type:
                cursor.execute(
                    "UPDATE published_youtube_materials SET platform_type = ? WHERE id = ?",
                    (inferred_platform_type, row_id),
                )
        cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_published_youtube_materials_video_platform
        ON published_youtube_materials(video_id, platform_type)
        WHERE video_id IS NOT NULL AND video_id != '' AND platform_type IS NOT NULL AND platform_type != 0
        ''')
        conn.commit()


def init_youtube_video_table():
    init_database_tables()
    with sqlite3.connect(_db_path()) as conn:
        cursor = conn.cursor()
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
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        ''')
        cursor.execute("PRAGMA table_info(youtube_videos)")
        existing_columns = {row[1] for row in cursor.fetchall()}
        video_columns = {
            "translate_status": "INTEGER DEFAULT 0",
            "processed_file_path": "TEXT",
            "transcript_status": "INTEGER DEFAULT 0",
            "transcript_file_path": "TEXT",
            "transcript_language": "TEXT",
            "analysis_status": "INTEGER DEFAULT 0",
            "analysis_result": "TEXT",
            "publish_draft": "TEXT",
            "analysis_updated_at": "DATETIME",
        }
        for column, definition in video_columns.items():
            if column not in existing_columns:
                cursor.execute(f"ALTER TABLE youtube_videos ADD COLUMN {column} {definition}")
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_youtube_videos_download_status ON youtube_videos(download_status)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_youtube_videos_publish_status ON youtube_videos(publish_status)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_youtube_videos_translate_status ON youtube_videos(translate_status)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_youtube_videos_analysis_status ON youtube_videos(analysis_status)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_youtube_videos_created ON youtube_videos(created_at, id)')
        conn.commit()


def init_youtube_workflow_table():
    init_youtube_video_table()
    with sqlite3.connect(_db_path()) as conn:
        cursor = conn.cursor()
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
            publish_to_douyin INTEGER DEFAULT 1,
            publish_to_bilibili INTEGER DEFAULT 0,
            process_version TEXT DEFAULT 'translation_v1',
            subtitle_language TEXT DEFAULT 'zh-CN',
            burn_profile TEXT DEFAULT 'stable',
            subtitle_size TEXT DEFAULT 'douyin',
            translator_label TEXT DEFAULT 'AI中文字幕',
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
            progress REAL DEFAULT 0,
            speed TEXT,
            eta TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        ''')
        cursor.execute("PRAGMA table_info(youtube_workflow_jobs)")
        existing_columns = {row[1] for row in cursor.fetchall()}
        if "progress" not in existing_columns:
            cursor.execute("ALTER TABLE youtube_workflow_jobs ADD COLUMN progress REAL DEFAULT 0")
        if "speed" not in existing_columns:
            cursor.execute("ALTER TABLE youtube_workflow_jobs ADD COLUMN speed TEXT")
        if "eta" not in existing_columns:
            cursor.execute("ALTER TABLE youtube_workflow_jobs ADD COLUMN eta TEXT")
        if "channel" not in existing_columns:
            cursor.execute("ALTER TABLE youtube_workflow_jobs ADD COLUMN channel TEXT")
        if "subscribers" not in existing_columns:
            cursor.execute("ALTER TABLE youtube_workflow_jobs ADD COLUMN subscribers TEXT")
        if "published_at" not in existing_columns:
            cursor.execute("ALTER TABLE youtube_workflow_jobs ADD COLUMN published_at TEXT")
        if "bilibili_account" not in existing_columns:
            cursor.execute("ALTER TABLE youtube_workflow_jobs ADD COLUMN bilibili_account TEXT")
        if "bilibili_tid" not in existing_columns:
            cursor.execute("ALTER TABLE youtube_workflow_jobs ADD COLUMN bilibili_tid INTEGER DEFAULT 249")
        if "publish_to_douyin" not in existing_columns:
            cursor.execute("ALTER TABLE youtube_workflow_jobs ADD COLUMN publish_to_douyin INTEGER DEFAULT 1")
        if "publish_to_bilibili" not in existing_columns:
            cursor.execute("ALTER TABLE youtube_workflow_jobs ADD COLUMN publish_to_bilibili INTEGER DEFAULT 0")
        if "process_version" not in existing_columns:
            cursor.execute("ALTER TABLE youtube_workflow_jobs ADD COLUMN process_version TEXT DEFAULT 'translation_v1'")
        if "subtitle_language" not in existing_columns:
            cursor.execute("ALTER TABLE youtube_workflow_jobs ADD COLUMN subtitle_language TEXT DEFAULT 'zh-CN'")
        if "burn_profile" not in existing_columns:
            cursor.execute("ALTER TABLE youtube_workflow_jobs ADD COLUMN burn_profile TEXT DEFAULT 'stable'")
        if "subtitle_size" not in existing_columns:
            cursor.execute("ALTER TABLE youtube_workflow_jobs ADD COLUMN subtitle_size TEXT DEFAULT 'douyin'")
        if "translator_label" not in existing_columns:
            cursor.execute("ALTER TABLE youtube_workflow_jobs ADD COLUMN translator_label TEXT DEFAULT 'AI中文字幕'")
        workflow_error_columns = {
            "error_code": "TEXT",
            "error_type": "TEXT",
            "error_reason": "TEXT",
            "error_detail": "TEXT",
            "interrupted_at": "DATETIME",
        }
        for column, definition in workflow_error_columns.items():
            if column not in existing_columns:
                cursor.execute(f"ALTER TABLE youtube_workflow_jobs ADD COLUMN {column} {definition}")
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_youtube_workflow_jobs_video_id ON youtube_workflow_jobs(video_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_youtube_workflow_jobs_status ON youtube_workflow_jobs(status)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_youtube_workflow_jobs_status_updated ON youtube_workflow_jobs(status, updated_at, created_at)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_youtube_workflow_jobs_video_updated ON youtube_workflow_jobs(video_id, updated_at, created_at)')
        conn.commit()


