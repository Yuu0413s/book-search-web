from pathlib import Path

import psycopg2
import pytest

from myapp import app as flask_app

# compose.yaml の PostgreSQL 内にあるテスト専用 DB（開発用とは別）
TEST_DB_DSN = (
    "host=localhost port=5433 dbname=narou_search_test user=narou password=narou"
)
SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schema.sql"


@pytest.fixture(scope="session")
def test_db():
    """テスト開始時に 1 回だけ、テスト用 DB のテーブルを作り直す。"""
    conn = psycopg2.connect(TEST_DB_DSN)
    with conn, conn.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS novels, admins;")
        cur.execute(SCHEMA_PATH.read_text(encoding="utf-8"))
    conn.close()
    return TEST_DB_DSN


@pytest.fixture
def app(test_db):
    flask_app.config.update(TESTING=True, DB_DSN=test_db)
    return flask_app


@pytest.fixture
def client(app):
    return app.test_client()
