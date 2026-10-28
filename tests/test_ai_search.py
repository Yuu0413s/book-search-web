import math

import pytest

import ai_search
from tests.helpers import EMBEDDING_ID


def make_target(novel_id=1, **overrides):
    """db.fetch_embedding_targets が返す 1 件分。"""
    target = {
        "id": novel_id,
        "title": "テスト作品",
        "story": "テストのあらすじ",
        "keyword": "異世界 転生",
        "embedding_model": None,
        "embedding_hash": None,
    }
    target.update(overrides)
    return target


# --- 変換する文章 ---


def test_作品の文章_タイトル_あらすじ_タグを決まった書き方でつなぐ():
    novel = make_target(title="勇者の旅", story="魔王を倒す話", keyword="冒険 魔法")

    assert ai_search.document_text(novel) == (
        "title: 勇者の旅 | text: 魔王を倒す話\n冒険 魔法"
    )


@pytest.mark.parametrize("keyword", [None, ""])
def test_作品の文章_タグが無ければ改行も付けない(keyword):
    novel = make_target(title="勇者の旅", story="魔王を倒す話", keyword=keyword)

    assert ai_search.document_text(novel) == "title: 勇者の旅 | text: 魔王を倒す話"


def test_作品の文章_タイトルが空ならnoneと書く():
    novel = make_target(title="", story="魔王を倒す話", keyword=None)

    assert ai_search.document_text(novel) == "title: none | text: 魔王を倒す話"


def test_検索の文章_決まった書き方で包む():
    assert ai_search.query_text("切ない恋の話") == (
        "task: search result | query: 切ない恋の話"
    )


# --- ハッシュ ---


def test_ハッシュ_UTF8のSHA256を16進数64文字で返す():
    # ASCII の文字だけだと、ほかの文字コードでも同じバイト列になり区別できないので、
    # 日本語で確かめる（Shift_JIS なら 65468d6b… になる）
    assert ai_search.source_hash("小説") == (
        "9432dc178d9798751a2cc9be20705c5d284c1eb206b4381a5d2dd227bb67424b"
    )


def test_ハッシュ_同じ文章なら同じ値_違えば違う値():
    text = "title: 勇者の旅 | text: 魔王を倒す話"

    assert ai_search.source_hash(text) == ai_search.source_hash(text)
    assert ai_search.source_hash(text) != ai_search.source_hash(text + "。")


# --- 変換が必要な作品の選び出し ---


def embedded_target(novel_id, **overrides):
    """今のモデルと次元数・今の内容で変換済みの作品。"""
    target = make_target(novel_id, **overrides)
    target["embedding_model"] = EMBEDDING_ID
    target["embedding_hash"] = ai_search.source_hash(ai_search.document_text(target))
    return target


def test_選び出し_ベクトルが無い作品は変換が必要():
    targets = [make_target(1)]

    assert ai_search.select_novels_to_embed(targets, EMBEDDING_ID) == targets


def test_選び出し_モデルと次元数も内容も同じなら変換しない():
    targets = [embedded_target(1)]

    assert ai_search.select_novels_to_embed(targets, EMBEDDING_ID) == []


def test_選び出し_モデルか次元数が違えば変換が必要():
    target = embedded_target(1)
    target["embedding_model"] = "gemini-embedding-2:3072"

    assert ai_search.select_novels_to_embed([target], EMBEDDING_ID) == [target]


@pytest.mark.parametrize("column", ["title", "story", "keyword"])
def test_選び出し_タイトル_あらすじ_タグのどれかが変われば変換が必要(column):
    target = embedded_target(1)
    target[column] = "書き換えた内容"

    assert ai_search.select_novels_to_embed([target], EMBEDDING_ID) == [target]


def test_選び出し_混ざっていても必要な作品だけを元の順番で返す():
    changed = embedded_target(2)
    changed["story"] = "書き換えたあらすじ"
    targets = [make_target(1), changed, embedded_target(3), make_target(4)]

    result = ai_search.select_novels_to_embed(targets, EMBEDDING_ID)

    assert [target["id"] for target in result] == [1, 2, 4]


def test_選び出し_作品が無ければ空のリスト():
    assert ai_search.select_novels_to_embed([], EMBEDDING_ID) == []


# --- 類似度 ---


def test_類似度_同じ向きなら1():
    assert ai_search.cosine_similarity([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]) == (
        pytest.approx(1.0)
    )


def test_類似度_直交していれば0():
    assert ai_search.cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


def test_類似度_逆向きならマイナス1():
    assert ai_search.cosine_similarity([1.0, 2.0], [-1.0, -2.0]) == (
        pytest.approx(-1.0)
    )


def test_類似度_長さが1でないベクトルでも向きだけで決まる():
    # API の値は長さ 1 で返るが、DB の REAL で丸められるので、長さ 1 を前提にしない
    # [3, 4] と [6, 8] は同じ向き、[3, 4] と [4, 3] は cos = 24 / 25
    assert ai_search.cosine_similarity([3.0, 4.0], [6.0, 8.0]) == pytest.approx(1.0)
    assert ai_search.cosine_similarity([3.0, 4.0], [4.0, 3.0]) == pytest.approx(0.96)


def test_類似度_計算の誤差があっても1を超えない():
    # [1, 1, 1] 同士は、小数の誤差で 1.0000000000000002 になる
    assert ai_search.cosine_similarity([1.0, 1.0, 1.0], [1.0, 1.0, 1.0]) == 1.0


def test_類似度_長さが違うベクトルはValueError():
    with pytest.raises(ValueError):
        ai_search.cosine_similarity([1.0, 2.0], [1.0, 2.0, 3.0])


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ([0.0, 0.0], [1.0, 2.0]),
        ([1.0, 2.0], [0.0, 0.0]),
    ],
)
def test_類似度_長さ0のベクトルはValueError(a, b):
    # 向きが無いので類似度を決められない（そのままだと 0 で割ることになる）
    with pytest.raises(ValueError):
        ai_search.cosine_similarity(a, b)


# --- 上位の選び出し ---


def test_上位_類似度の高い順にlimit件を返す():
    query = [1.0, 0.0]
    candidates = [
        (1, [0.0, 1.0]),  # 0
        (2, [1.0, 0.0]),  # 1
        (3, [1.0, 1.0]),  # 約 0.707
        (4, [-1.0, 0.0]),  # -1
    ]

    result = ai_search.rank_by_similarity(query, candidates, limit=2)

    assert [novel_id for novel_id, _ in result] == [2, 3]
    assert result[0][1] == pytest.approx(1.0)
    assert result[1][1] == pytest.approx(1 / math.sqrt(2))


def test_上位_候補がlimitより少なければ全件を返す():
    candidates = [(1, [0.0, 1.0]), (2, [1.0, 0.0])]

    result = ai_search.rank_by_similarity([1.0, 0.0], candidates, limit=10)

    assert [novel_id for novel_id, _ in result] == [2, 1]


def test_上位_候補が無ければ空のリスト():
    assert ai_search.rank_by_similarity([1.0, 0.0], [], limit=10) == []


def test_上位_類似度が同じならidの小さい順():
    # 結果の順番が毎回変わらないようにする
    candidates = [(5, [1.0, 0.0]), (2, [2.0, 0.0]), (9, [3.0, 0.0])]

    result = ai_search.rank_by_similarity([1.0, 0.0], candidates, limit=3)

    assert [novel_id for novel_id, _ in result] == [2, 5, 9]
