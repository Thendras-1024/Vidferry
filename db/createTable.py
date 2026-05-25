import sqlite3
import json
import os

# 数据库文件路径（如果不存在会自动创建）
db_file = './database.db'

# 如果数据库已存在，则删除旧的表（可选）
# if os.path.exists(db_file):
#     os.remove(db_file)

# 连接到SQLite数据库（如果文件不存在则会自动创建）
conn = sqlite3.connect(db_file)
cursor = conn.cursor()

# 创建账号记录表
cursor.execute('''
CREATE TABLE IF NOT EXISTS user_info (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type INTEGER NOT NULL,
    filePath TEXT NOT NULL,  -- 存储文件路径
    userName TEXT NOT NULL,
    status INTEGER DEFAULT 0
)
''')

# 创建文件记录表
cursor.execute('''CREATE TABLE IF NOT EXISTS file_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT, -- 唯一标识每条记录
    asset_id TEXT,                        -- 对外素材ID
    filename TEXT NOT NULL,               -- 文件名
    original_filename TEXT,               -- 原始文件名
    filesize REAL,                     -- 文件大小（单位：MB）
    upload_time DATETIME DEFAULT CURRENT_TIMESTAMP, -- 上传时间，默认当前时间
    file_path TEXT,                       -- 兼容旧接口的文件路径
    storage_key TEXT,                     -- 存储键，未来可映射到对象存储
    storage_backend TEXT DEFAULT 'local', -- local / oss / s3 等
    source_type TEXT DEFAULT 'manual_upload',
    source_video_id TEXT,
    status TEXT DEFAULT 'ready',
    metadata TEXT DEFAULT '{}'
)
''')

cursor.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_file_records_asset_id ON file_records(asset_id)')
cursor.execute('CREATE INDEX IF NOT EXISTS idx_file_records_source_video_id ON file_records(source_video_id)')
cursor.execute('CREATE INDEX IF NOT EXISTS idx_file_records_source_type ON file_records(source_type)')

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
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
)
''')

cursor.execute('CREATE INDEX IF NOT EXISTS idx_youtube_videos_download_status ON youtube_videos(download_status)')
cursor.execute('CREATE INDEX IF NOT EXISTS idx_youtube_videos_publish_status ON youtube_videos(publish_status)')
cursor.execute('CREATE INDEX IF NOT EXISTS idx_youtube_videos_translate_status ON youtube_videos(translate_status)')

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

cursor.execute('CREATE INDEX IF NOT EXISTS idx_youtube_workflow_jobs_video_id ON youtube_workflow_jobs(video_id)')
cursor.execute('CREATE INDEX IF NOT EXISTS idx_youtube_workflow_jobs_status ON youtube_workflow_jobs(status)')


# 提交更改
conn.commit()
print("✅ 表创建成功")
# 关闭连接
conn.close()
