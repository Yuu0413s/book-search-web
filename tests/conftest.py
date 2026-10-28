from pathlib import Path

import psycopg2
import pytest
import requests

import gemini
from myapp import app as flask_app
from tests.helpers import TEST_DB_DSN, use_embed_errors

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schema.sql"


@pytest.fixture(scope="session")
def test_db():
    """テスト開始時に 1 回だけ、テスト用 DB のテーブルを作り直す。"""
    conn = psycopg2.connect(TEST_DB_DSN)
    with conn, conn.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS novel_embeddings, novels, admins;")
        cur.execute(SCHEMA_PATH.read_text(encoding="utf-8"))
    conn.close()
    return TEST_DB_DSN


@pytest.fixture
def db_conn(test_db):
    """テスト用 DB への接続。各テストの前に行を全部消して、空の状態から始める。"""
    conn = psycopg2.connect(test_db)
    with conn, conn.cursor() as cur:
        cur.execute("DELETE FROM novel_embeddings;")
        cur.execute("DELETE FROM novels;")
        cur.execute("DELETE FROM admins;")
    yield conn
    conn.close()


@pytest.fixture(autouse=True)
def block_gemini_requests(monkeypatch):
    """すべてのテストで、Gemini API への通信を必ず失敗させる。

    取り込みのテストもベクトル化まで走るので、gemini.embed_texts の差し替えを
    忘れても、本物の API を呼んで無料枠を使ったり、キーを送ったりしないようにする。
    gemini.requests は requests そのものなので、requests.post 全体が対象になる
    （このアプリで post を使うのは gemini.py だけ）。通信を確かめるテストは、
    この後に自分で差し替え直す
    """

    def refuse(*args, **kwargs):
        raise requests.ConnectionError("テストでは実際の Gemini API を呼ばない")

    monkeypatch.setattr(gemini.requests, "post", refuse)


@pytest.fixture
def fake_embed(monkeypatch):
    """Gemini でのベクトル化を、常に成功する差し替えにする（実際の API は呼ばない）。"""
    return use_embed_errors(monkeypatch, {})


@pytest.fixture
def app(test_db):
    # ローカルの instance/config.py の値に左右されないよう、テストに必要な設定は
    # ここで決める（https への切り替えを確かめるテストは個別に True にする）
    flask_app.config.update(
        TESTING=True,
        DB_DSN=test_db,
        SECRET_KEY="test-secret-key",
        GEMINI_API_KEY="test-gemini-key",
        SESSION_COOKIE_SECURE=False,
        # テストクライアントは Cookie の Path を守るので、"/s2422016/" だと
        # /admin/... に session が届かない
        SESSION_COOKIE_PATH="/",
    )
    return flask_app


@pytest.fixture
def client(app):
    return app.test_client()
