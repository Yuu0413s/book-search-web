from datetime import datetime, timedelta

import pytest

import gemini
import narou
from tests.helpers import (
    TEST_DB_DSN,
    FakeEmbedTexts,
    add_novel,
    fetch_embeddings_by_novel_id,
    fetch_novels_by_ncode,
    insert_novel,
    make_novel,
)


@pytest.fixture
def fake_embed(monkeypatch):
    """Gemini でのベクトル化を差し替える（実際の API は呼ばない）。"""
    fake = FakeEmbedTexts()
    monkeypatch.setattr(gemini, "embed_texts", fake)
    return fake


def use_embed_errors(monkeypatch, errors):
    """指定した回の呼び出しで例外を投げる、ベクトル化の差し替えを入れる。"""
    fake = FakeEmbedTexts(errors=errors)
    monkeypatch.setattr(gemini, "embed_texts", fake)
    return fake


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


# --- 取り込みに続くベクトル化 ---


def test_取り込みコマンドは続けてベクトル化し_両方の結果を表示する(
    app, db_conn, monkeypatch, fake_embed
):
    novels = [make_novel("N0001AA"), make_novel("N0002BB")]
    monkeypatch.setattr(narou, "fetch_top_novels", lambda: novels)

    result = app.test_cli_runner().invoke(args=["import-novels"])

    assert result.exit_code == 0
    assert "追加 2 件・更新 0 件・削除 0 件" in result.output
    assert "ベクトル化しました（成功 2 件・失敗 0 件）" in result.output
    assert len(fetch_embeddings_by_novel_id(db_conn)) == 2


def test_取り込みコマンドは_ベクトル化に失敗しても終了コード0で理由を表示する(
    app, db_conn, monkeypatch
):
    novels = [make_novel("N0001AA"), make_novel("N0002BB")]
    monkeypatch.setattr(narou, "fetch_top_novels", lambda: novels)
    use_embed_errors(monkeypatch, {1: gemini.GeminiApiError("テスト用の変換失敗")})

    result = app.test_cli_runner().invoke(args=["import-novels"])

    # 取り込みは成功しているので、コマンドとしては成功にする
    assert result.exit_code == 0
    assert "追加 2 件・更新 0 件・削除 0 件" in result.output
    assert "ベクトル化しました（成功 0 件・失敗 2 件）" in result.output
    # コマンドの出力は自分の端末に出るので、理由の詳しい文言も出す
    assert "テスト用の変換失敗" in result.output
    assert set(fetch_novels_by_ncode(db_conn)) == {"N0001AA", "N0002BB"}


# --- ベクトル化だけのコマンド ---


def test_ベクトル化コマンドは_足りない分をベクトル化して件数を表示する(
    app, db_conn, fake_embed
):
    add_novel(db_conn, "N0001AA")

    result = app.test_cli_runner().invoke(args=["embed-novels"])

    assert result.exit_code == 0
    assert "ベクトル化しました（成功 1 件・失敗 0 件）" in result.output
    assert len(fetch_embeddings_by_novel_id(db_conn)) == 1


def test_ベクトル化コマンドは_回数制限なら案内を表示して終了コード1(
    app, db_conn, monkeypatch
):
    add_novel(db_conn, "N0001AA")
    use_embed_errors(monkeypatch, {1: gemini.GeminiQuotaError("テスト用の回数制限")})

    result = app.test_cli_runner().invoke(args=["embed-novels"])

    assert result.exit_code == 1
    assert "ベクトル化しました（成功 0 件・失敗 1 件）" in result.output
    assert "回数制限に達しました" in result.output


def test_ベクトル化コマンドは_回数制限以外の失敗なら理由を表示して終了コード1(
    app, db_conn, monkeypatch
):
    add_novel(db_conn, "N0001AA")
    use_embed_errors(monkeypatch, {1: gemini.GeminiApiError("テスト用の変換失敗")})

    result = app.test_cli_runner().invoke(args=["embed-novels"])

    assert result.exit_code == 1
    assert "ベクトル化しました（成功 0 件・失敗 1 件）" in result.output
    assert "テスト用の変換失敗" in result.output


def test_ベクトル化コマンドは_DBに接続できなければ接続先を出さずに終了コード1(
    app, db_conn, monkeypatch, fake_embed
):
    wrong_dsn = TEST_DB_DSN.replace("password=narou", "password=wrong")
    assert wrong_dsn != TEST_DB_DSN
    monkeypatch.setitem(app.config, "DB_DSN", wrong_dsn)

    result = app.test_cli_runner().invoke(args=["embed-novels"])

    assert result.exit_code == 1
    assert "DB への接続または保存に失敗しました" in result.output
    assert "localhost" not in result.output
    assert "5433" not in result.output
    assert "narou" not in result.output
    assert fake_embed.calls == []
