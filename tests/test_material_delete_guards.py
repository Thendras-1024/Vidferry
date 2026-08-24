import pytest

from app.backend.runtime import create_backend_module


class _Cursor:
    def __init__(self, download_record, processed_records):
        self.download_record = download_record
        self.processed_records = processed_records
        self.statements = []
        self.params = ()

    def execute(self, sql, params=None):
        self.statements.append((sql, params))
        self.params = params or ()

    def fetchone(self):
        sql = self.statements[-1][0]
        if 'FROM file_records WHERE id = %s' in sql:
            return self.download_record
        return None

    def fetchall(self):
        sql = self.statements[-1][0]
        if self.params[:1] == ('youtube_processed',):
            return self.processed_records
        return []


def test_download_material_cannot_be_deleted_while_processed_material_exists():
    backend = create_backend_module('test_material_delete_guard_backend')
    cursor = _Cursor(
        {
            'id': 11,
            'filename': 'source.mp4',
            'source_type': 'youtube_download',
            'source_video_id': 'video-1',
            'owner_user_id': 1,
            'storage_key': 'videos/source.mp4',
            'file_path': 'videos/source.mp4',
            'metadata': '{}',
        },
        [{'id': 22, 'source_type': 'youtube_processed', 'source_video_id': 'video-1', 'metadata': '{}'}],
    )

    with pytest.raises(backend.WorkflowConflictError, match='不能单独删除原视频') as error:
        backend.delete_material_record(cursor, 11, 1)

    assert error.value.error_code == backend.WORKFLOW_ERROR_DELETE_PROCESSED_EXISTS
    assert not any('DELETE FROM file_records' in sql for sql, _params in cursor.statements)
