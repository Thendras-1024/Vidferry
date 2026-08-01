from app.db.postgres_compat import normalize_postgres_sql


def test_postgres_sql_escapes_like_percent_and_converts_parameters():
    sql = "SELECT * FROM file_records WHERE lower(filename) LIKE '%.mp4' AND id = ?"

    assert normalize_postgres_sql(sql) == "SELECT * FROM file_records WHERE lower(filename) ILIKE '%%.mp4' AND id = %s"
