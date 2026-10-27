from datetime import datetime, timedelta

import narou
from tests.helpers import (
    TEST_DB_DSN,
    fetch_novels_by_ncode,
    insert_novel,
    make_novel,
)


def test_取り込みに成功すると件数を表示してDBに保存する(app, db_conn, monkeypatch):
    novels = [make_novel("N0001AA"), make_novel("N0002BB")]
    monkeypatch.setattr(narou, "fetch_top_novels", lambda: novels)

    result = app.test_cli_runner().invoke(args=["import-novels"])

    assert result.exit_code == 0
    assert "追加 2 件・更新 0 件・削除 0 件" in result.output
    assert set(fetch_novels_by_ncode(db_conn)) == {"N0001AA", "N0002BB"}


def test_APIの取得に失敗したらエラーを表示してDBは変えない(app, db_conn, monkeypatch):
    # 30 日前の作品は、取り込みが成功していれば削除されるはずのもの
    insert_novel(db_conn, "N0099ZZ", fetched_at=datetime.now() - timedelta(days=30))

    def failing_fetch():
        raise narou.NarouApiError("テスト用の取得失敗")

    monkeypatch.setattr(narou, "fetch_top_novels", failing_fetch)

    result = app.test_cli_runner().invoke(args=["import-novels"])

    assert result.exit_code == 1
    # 例外に渡したメッセージが、そのまま表示されることを確かめる
    assert "テスト用の取得失敗" in result.output
    assert set(fetch_novels_by_ncode(db_conn)) == {"N0099ZZ"}


def test_DBに接続できなければエラーを表示してDBは変えない(app, db_conn, monkeypatch):
    # 30 日前の作品は、取り込みが成功していれば削除されるはずのもの
    insert_novel(db_conn, "N0099ZZ", fetched_at=datetime.now() - timedelta(days=30))
    monkeypatch.setattr(narou, "fetch_top_novels", lambda: [make_novel("N0001AA")])
    # パスワードだけを壊す（ほかの部分はテスト用 DB と同じ）
    wrong_dsn = TEST_DB_DSN.replace("password=narou", "password=wrong")
    assert wrong_dsn != TEST_DB_DSN
    monkeypatch.setitem(app.config, "DB_DSN", wrong_dsn)

    result = app.test_cli_runner().invoke(args=["import-novels"])

    assert result.exit_code == 1
    assert "DB への接続または保存に失敗しました" in result.output
    # テスト用 DB の接続先（localhost:5433）・ユーザー名（narou）が表示されない
    assert "localhost" not in result.output
    assert "5433" not in result.output
    assert "narou" not in result.output
    assert set(fetch_novels_by_ncode(db_conn)) == {"N0099ZZ"}
