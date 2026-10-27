from datetime import datetime, timedelta

import narou
from tests.helpers import fetch_novels_by_ncode, insert_novel, make_novel


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
        raise narou.NarouApiError("なろう API への接続に失敗しました")

    monkeypatch.setattr(narou, "fetch_top_novels", failing_fetch)

    result = app.test_cli_runner().invoke(args=["import-novels"])

    assert result.exit_code == 1
    assert "なろう API への接続に失敗しました" in result.output
    assert set(fetch_novels_by_ncode(db_conn)) == {"N0099ZZ"}


def test_DBに接続できなければエラーを表示する(app, db_conn, monkeypatch):
    monkeypatch.setattr(narou, "fetch_top_novels", lambda: [make_novel("N0001AA")])
    monkeypatch.setitem(
        app.config,
        "DB_DSN",
        "host=localhost port=5433 dbname=narou_search_test user=narou password=wrong",
    )

    result = app.test_cli_runner().invoke(args=["import-novels"])

    assert result.exit_code == 1
    assert "DB" in result.output
    assert fetch_novels_by_ncode(db_conn) == {}
