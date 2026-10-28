from datetime import datetime

import pytest

import ai_search
import db
import embedding
import gemini
from tests.helpers import (
    EMBEDDED_AT,
    EMBEDDING_DIMENSIONS,
    EMBEDDING_ID,
    FakeEmbedTexts,
    add_embedded_novel,
    add_novel,
    add_novel_with_vector,
    fetch_embeddings_by_novel_id,
    fetch_novels_by_ncode,
    insert_embedding,
    novel_id_of,
    use_fake_embed,
    use_fake_embed_text,
)

API_KEY = "test-api-key"
NOW = datetime(2026, 10, 28, 15, 0, 0)
# 今のモデル（EMBEDDING_ID）とは別のモデル・次元数で変換したことを表す
OTHER_MODEL = "gemini-embedding-001:768"


def document_text_of(conn, ncode):
    return ai_search.document_text(fetch_novels_by_ncode(conn)[ncode])


def add_novels(conn, count):
    """ベクトルの無い作品を count 件入れ、ncode を id 順に返す。"""
    ncodes = [f"N{number:04d}AA" for number in range(1, count + 1)]
    for ncode in ncodes:
        add_novel(conn, ncode)
    return ncodes


def add_novels_in_each_state(conn):
    """ベクトル化の状態が違う作品を 1 件ずつ入れる。

    変換が必要な作品の ncode を id 順に返す。
    """
    add_novel(conn, "N0001AA")  # ベクトルが無い
    add_embedded_novel(conn, "N0002BB")  # 今の内容で変換済み
    add_novel(conn, "N0003CC")  # 変換した後に内容が変わった
    insert_embedding(
        conn,
        novel_id_of(conn, "N0003CC"),
        [0.1] * EMBEDDING_DIMENSIONS,
        source_hash="old",
    )
    add_embedded_novel(conn, "N0004DD", model=OTHER_MODEL)  # 別のモデル
    return ["N0001AA", "N0003CC", "N0004DD"]


# --- ベクトル化 ---


def test_変換が必要な作品だけをid順に送り_ベクトルとハッシュを保存する(
    db_conn, fake_embed
):
    targets = add_novels_in_each_state(db_conn)
    texts = [document_text_of(db_conn, ncode) for ncode in targets]

    result = embedding.embed_novels(db_conn, API_KEY, NOW)

    assert result == {"embedded": 3, "failed": 0, "error": None}
    assert fake_embed.calls == [texts]
    assert fake_embed.api_keys == [API_KEY]
    saved = fetch_embeddings_by_novel_id(db_conn)
    for ncode, text in zip(targets, texts, strict=True):
        row = saved[novel_id_of(db_conn, ncode)]
        assert row["embedding"] == fake_embed.vectors_by_text[text]
        assert row["model"] == EMBEDDING_ID
        assert row["source_hash"] == ai_search.source_hash(text)
        assert row["updated_at"] == NOW
    # 変換済みの作品は送らず、保存し直してもいない（前提の更新日時は NOW と違う）
    assert EMBEDDED_AT != NOW
    assert saved[novel_id_of(db_conn, "N0002BB")]["updated_at"] != NOW


@pytest.mark.parametrize("has_novels", [False, True])
def test_変換が必要な作品が無ければ_APIを呼ばずに0件を返す(
    db_conn, fake_embed, has_novels
):
    if has_novels:
        add_embedded_novel(db_conn, "N0001AA")

    result = embedding.embed_novels(db_conn, API_KEY, NOW)

    assert result == {"embedded": 0, "failed": 0, "error": None}
    assert fake_embed.calls == []


def test_まとめて送れる件数ずつに分けて送る(db_conn, fake_embed, monkeypatch):
    monkeypatch.setattr(gemini, "MAX_BATCH_SIZE", 2)
    ncodes = add_novels(db_conn, 5)

    result = embedding.embed_novels(db_conn, API_KEY, NOW)

    assert result == {"embedded": 5, "failed": 0, "error": None}
    assert [len(texts) for texts in fake_embed.calls] == [2, 2, 1]
    assert set(fetch_embeddings_by_novel_id(db_conn)) == {
        novel_id_of(db_conn, ncode) for ncode in ncodes
    }


def test_途中で回数制限になったら止め_それまでに保存した分は残す(db_conn, monkeypatch):
    monkeypatch.setattr(gemini, "MAX_BATCH_SIZE", 2)
    ncodes = add_novels(db_conn, 5)
    quota_error = gemini.GeminiQuotaError("テスト用の回数制限")
    fake = use_fake_embed(monkeypatch, {2: quota_error})

    result = embedding.embed_novels(db_conn, API_KEY, NOW)

    # 3 回目は送らず、送れなかった 3 件を失敗として数える
    assert result == {"embedded": 2, "failed": 3, "error": quota_error}
    assert len(fake.calls) == 2
    assert set(fetch_embeddings_by_novel_id(db_conn)) == {
        novel_id_of(db_conn, ncode) for ncode in ncodes[:2]
    }


def test_回数制限以外の失敗でも止める(db_conn, monkeypatch):
    monkeypatch.setattr(gemini, "MAX_BATCH_SIZE", 2)
    add_novels(db_conn, 3)
    api_error = gemini.GeminiApiError("テスト用の変換失敗")
    fake = use_fake_embed(monkeypatch, {1: api_error})

    result = embedding.embed_novels(db_conn, API_KEY, NOW)

    assert result == {"embedded": 0, "failed": 3, "error": api_error}
    assert len(fake.calls) == 1
    assert fetch_embeddings_by_novel_id(db_conn) == {}


def test_変換している間に消えた作品は_成功にも失敗にも数えない(db_conn, monkeypatch):
    add_novels(db_conn, 2)
    fake = FakeEmbedTexts()

    def embed_while_deleting(texts, api_key):
        # 一覧を取った後、保存する前に、取り込みで作品が消えた場合を再現する
        with db_conn, db_conn.cursor() as cur:
            cur.execute("DELETE FROM novels WHERE ncode = 'N0002AA';")
        return fake(texts, api_key)

    monkeypatch.setattr(gemini, "embed_texts", embed_while_deleting)

    result = embedding.embed_novels(db_conn, API_KEY, NOW)

    assert result == {"embedded": 1, "failed": 0, "error": None}
    assert set(fetch_embeddings_by_novel_id(db_conn)) == {
        novel_id_of(db_conn, "N0001AA")
    }


# --- 状況 ---


def test_状況_作品数と_今のモデルと内容でベクトルがある件数を返す(db_conn):
    add_novels_in_each_state(db_conn)

    assert embedding.get_embedding_status(db_conn) == {
        "novel_count": 4,
        "embedded_count": 1,
    }


def test_状況_作品が無ければどちらも0(db_conn):
    assert embedding.get_embedding_status(db_conn) == {
        "novel_count": 0,
        "embedded_count": 0,
    }


# --- 文章で探す ---


def test_文章で探す_類似度の高い順にlimit件を_作品と類似度の組で返す(
    db_conn, monkeypatch
):
    add_novel_with_vector(db_conn, "N0001AA", 0.5)
    add_novel_with_vector(db_conn, "N0002BB", 0.9)
    add_novel_with_vector(db_conn, "N0003CC", 0.7)
    # 別のモデルのベクトルは、どれだけ近くても比べない
    add_novel_with_vector(db_conn, "N0004DD", 0.99, model=OTHER_MODEL)
    fake = use_fake_embed_text(monkeypatch)

    results = embedding.search_by_text(db_conn, "切ない恋の話", API_KEY, limit=2)

    assert [novel["ncode"] for novel, _ in results] == ["N0002BB", "N0003CC"]
    assert [score for _, score in results] == pytest.approx([0.9, 0.7], abs=1e-6)
    assert fake.calls == [("task: search result | query: 切ない恋の話", API_KEY)]


@pytest.mark.parametrize(
    "state", ["作品が無い", "ベクトルが無い", "別のモデルのベクトルだけ"]
)
def test_文章で探す_比べるベクトルが無ければ_APIを呼ばずにNoneを返す(
    db_conn, monkeypatch, state
):
    if state == "ベクトルが無い":
        add_novel(db_conn, "N0001AA")
    elif state == "別のモデルのベクトルだけ":
        add_novel_with_vector(db_conn, "N0001AA", 0.9, model=OTHER_MODEL)
    fake = use_fake_embed_text(monkeypatch)

    assert embedding.search_by_text(db_conn, "切ない恋の話", API_KEY, limit=20) is None
    assert fake.calls == []


def test_文章で探す_Geminiで失敗したら_その例外をそのまま投げる(db_conn, monkeypatch):
    add_novel_with_vector(db_conn, "N0001AA", 0.9)
    quota_error = gemini.GeminiQuotaError("テスト用の回数制限")
    use_fake_embed_text(monkeypatch, error=quota_error)

    with pytest.raises(gemini.GeminiQuotaError) as excinfo:
        embedding.search_by_text(db_conn, "切ない恋の話", API_KEY, limit=20)
    assert excinfo.value is quota_error


def test_文章で探す_ベクトルを読んだ後に消えた作品は飛ばす(db_conn, monkeypatch):
    add_novel_with_vector(db_conn, "N0001AA", 0.9)
    add_novel_with_vector(db_conn, "N0002BB", 0.7)
    use_fake_embed_text(monkeypatch)
    fetch_novels_by_ids = db.fetch_novels_by_ids

    def fetch_after_deleting(conn, ids):
        # ベクトルを読んだ後、作品を読む前に、取り込みで作品が消えた場合を再現する
        with conn, conn.cursor() as cur:
            cur.execute("DELETE FROM novels WHERE ncode = 'N0001AA';")
        return fetch_novels_by_ids(conn, ids)

    monkeypatch.setattr(db, "fetch_novels_by_ids", fetch_after_deleting)

    results = embedding.search_by_text(db_conn, "切ない恋の話", API_KEY, limit=20)

    assert [novel["ncode"] for novel, _ in results] == ["N0002BB"]


# --- 似ている作品 ---


def test_似ている作品_元の作品を除いて近い順にlimit件を返し_APIは呼ばない(
    db_conn, monkeypatch
):
    add_novel_with_vector(db_conn, "N0001AA", 1.0)  # 元の作品
    add_novel_with_vector(db_conn, "N0002BB", 0.5)
    add_novel_with_vector(db_conn, "N0003CC", 0.9)
    add_novel_with_vector(db_conn, "N0004DD", 0.7)
    add_novel_with_vector(db_conn, "N0005EE", 0.99, model=OTHER_MODEL)
    fake = use_fake_embed_text(monkeypatch)

    results = embedding.find_similar_novels(
        db_conn, novel_id_of(db_conn, "N0001AA"), limit=2
    )

    assert [novel["ncode"] for novel, _ in results] == ["N0003CC", "N0004DD"]
    assert [score for _, score in results] == pytest.approx([0.9, 0.7], abs=1e-6)
    assert fake.calls == []


@pytest.mark.parametrize("state", ["ベクトルが無い", "別のモデルのベクトルだけ"])
def test_似ている作品_元の作品に今のベクトルが無ければNoneを返す(db_conn, state):
    if state == "ベクトルが無い":
        add_novel(db_conn, "N0001AA")
    else:
        add_novel_with_vector(db_conn, "N0001AA", 1.0, model=OTHER_MODEL)
    # ほかの作品にはベクトルがあり、比べれば結果が出る状態にする
    add_novel_with_vector(db_conn, "N0002BB", 0.9)

    result = embedding.find_similar_novels(
        db_conn, novel_id_of(db_conn, "N0001AA"), limit=20
    )

    assert result is None


def test_似ている作品_ほかの作品が無ければ空のリストを返す(db_conn):
    add_novel_with_vector(db_conn, "N0001AA", 1.0)

    result = embedding.find_similar_novels(
        db_conn, novel_id_of(db_conn, "N0001AA"), limit=20
    )

    assert result == []
