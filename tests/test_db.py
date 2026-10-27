from datetime import datetime, timedelta

import psycopg2
import pytest

import db
from tests.helpers import add_novel, fetch_novels_by_ncode, insert_novel, make_novel

NOW = datetime(2026, 10, 27, 12, 0, 0)


def test_空のDBに保存すると全件追加される(db_conn):
    novels = [make_novel("N0001AA"), make_novel("N0002BB", title="二作目")]

    result = db.save_novels(db_conn, novels, NOW)

    assert result == {"added": 2, "updated": 0, "deleted": 0}
    rows = fetch_novels_by_ncode(db_conn)
    assert set(rows) == {"N0001AA", "N0002BB"}
    for novel in novels:
        row = rows[novel["ncode"]]
        for column, value in novel.items():
            assert row[column] == value
        assert row["fetched_at"] == NOW


def test_同じncodeは上書きされ行は増えない(db_conn):
    db.save_novels(db_conn, [make_novel("N0001AA", title="旧タイトル")], NOW)
    created_at_before = fetch_novels_by_ncode(db_conn)["N0001AA"]["created_at"]
    later = NOW + timedelta(days=1)

    result = db.save_novels(
        db_conn,
        [make_novel("N0001AA", title="新タイトル", global_point=9999)],
        later,
    )

    assert result == {"added": 0, "updated": 1, "deleted": 0}
    rows = fetch_novels_by_ncode(db_conn)
    assert len(rows) == 1
    row = rows["N0001AA"]
    assert row["title"] == "新タイトル"
    assert row["global_point"] == 9999
    assert row["fetched_at"] == later
    assert row["created_at"] == created_at_before


def test_新しい作品と既存の作品が混ざっていても正しく数える(db_conn):
    insert_novel(db_conn, "N0001AA", fetched_at=NOW - timedelta(days=1))

    result = db.save_novels(
        db_conn, [make_novel("N0001AA"), make_novel("N0002BB")], NOW
    )

    assert result == {"added": 1, "updated": 1, "deleted": 0}
    assert set(fetch_novels_by_ncode(db_conn)) == {"N0001AA", "N0002BB"}


def test_最終取得から14日を過ぎた作品だけが削除される(db_conn):
    insert_novel(db_conn, "N0015DD", fetched_at=NOW - timedelta(days=15))
    insert_novel(db_conn, "N0014DD", fetched_at=NOW - timedelta(days=14))
    insert_novel(db_conn, "N0013DD", fetched_at=NOW - timedelta(days=13))

    result = db.save_novels(db_conn, [make_novel("N0001AA")], NOW)

    assert result == {"added": 1, "updated": 0, "deleted": 1}
    assert set(fetch_novels_by_ncode(db_conn)) == {"N0014DD", "N0013DD", "N0001AA"}


def test_古い作品でも今回の取得に含まれていれば削除されない(db_conn):
    insert_novel(db_conn, "N0001AA", fetched_at=NOW - timedelta(days=30))

    result = db.save_novels(db_conn, [make_novel("N0001AA")], NOW)

    assert result == {"added": 0, "updated": 1, "deleted": 0}
    assert fetch_novels_by_ncode(db_conn)["N0001AA"]["fetched_at"] == NOW


def test_途中で失敗したら保存も削除も取り消される(db_conn):
    insert_novel(db_conn, "N0099ZZ", fetched_at=NOW - timedelta(days=30))
    assert set(fetch_novels_by_ncode(db_conn)) == {"N0099ZZ"}
    novels = [make_novel("N0001AA"), make_novel("N0002BB", title=None)]

    with pytest.raises(psycopg2.Error):
        db.save_novels(db_conn, novels, NOW)

    # 1 件目の保存も、14 日削除も起きていない
    assert set(fetch_novels_by_ncode(db_conn)) == {"N0099ZZ"}


# --- 検索（search_novels） ---


def search(conn, **conditions):
    """search_novels を、指定しない条件は「絞り込まない」初期値で呼ぶ。"""
    params = {
        "words": [],
        "writer": None,
        "genre": None,
        "sort": "point",
        "limit": 20,
        "offset": 0,
    }
    params.update(conditions)
    return db.search_novels(conn, **params)


def ncodes_of(novels):
    return [novel["ncode"] for novel in novels]


def test_検索_条件なしなら全件を総合ポイント順に返す(db_conn):
    add_novel(db_conn, "N0001AA", global_point=10)
    add_novel(db_conn, "N0002BB", global_point=30)
    add_novel(db_conn, "N0003CC", global_point=20)

    novels, total = search(db_conn)

    assert ncodes_of(novels) == ["N0002BB", "N0003CC", "N0001AA"]
    assert total == 3


def test_検索_ポイントが同じ作品はidの順に並ぶ(db_conn):
    # ncode の順ではなく、DB に入った順（id の順）になることを確かめるため逆順に入れる
    add_novel(db_conn, "N0002BB", global_point=10)
    add_novel(db_conn, "N0001AA", global_point=10)

    novels, _ = search(db_conn)

    assert ncodes_of(novels) == ["N0002BB", "N0001AA"]


def test_検索_キーワードはタイトル_あらすじ_タグのどれかに部分一致すればヒットする(
    db_conn,
):
    add_novel(db_conn, "N0001AA", title="異世界食堂")
    add_novel(db_conn, "N0002BB", story="ある日、異世界に転移した")
    add_novel(db_conn, "N0003CC", keyword="異世界 転生")
    add_novel(db_conn, "N0004DD", title="現代劇", story="日常", keyword="現代")

    novels, total = search(db_conn, words=["異世界"])

    assert set(ncodes_of(novels)) == {"N0001AA", "N0002BB", "N0003CC"}
    assert total == 3


def test_検索_キーワードは英字の大文字小文字を区別しない(db_conn):
    add_novel(db_conn, "N0001AA", title="VRMMOの世界")

    novels, _ = search(db_conn, words=["vrmmo"])

    assert ncodes_of(novels) == ["N0001AA"]


def test_検索_複数の語はすべてを含む作品だけがヒットし_語は別の項目にあってもよい(
    db_conn,
):
    add_novel(db_conn, "N0001AA", title="異世界の物語", story="転生して冒険する")
    add_novel(db_conn, "N0002BB", title="異世界の物語", story="冒険する")

    novels, total = search(db_conn, words=["異世界", "転生"])

    assert ncodes_of(novels) == ["N0001AA"]
    assert total == 1


def test_検索_作者は部分一致(db_conn):
    add_novel(db_conn, "N0001AA", writer="山田太郎")
    add_novel(db_conn, "N0002BB", writer="佐藤花子")

    novels, _ = search(db_conn, writer="山田")

    assert ncodes_of(novels) == ["N0001AA"]


def test_検索_ジャンルを指定するとそのジャンルだけ(db_conn):
    add_novel(db_conn, "N0001AA", genre=201)
    add_novel(db_conn, "N0002BB", genre=101)

    novels, _ = search(db_conn, genre=201)

    assert ncodes_of(novels) == ["N0001AA"]


def test_検索_キーワード_作者_ジャンルはすべてを満たす作品だけ(db_conn):
    add_novel(db_conn, "N0001AA", title="異世界", writer="山田", genre=201)
    add_novel(db_conn, "N0002BB", title="異世界", writer="山田", genre=101)
    add_novel(db_conn, "N0003CC", title="異世界", writer="佐藤", genre=201)
    add_novel(db_conn, "N0004DD", title="現代", writer="山田", genre=201)

    novels, total = search(db_conn, words=["異世界"], writer="山田", genre=201)

    assert ncodes_of(novels) == ["N0001AA"]
    assert total == 1


def test_検索_ブックマーク数順に並べ替えられる(db_conn):
    add_novel(db_conn, "N0001AA", global_point=100, fav_novel_cnt=10)
    add_novel(db_conn, "N0002BB", global_point=1, fav_novel_cnt=30)
    add_novel(db_conn, "N0003CC", global_point=50, fav_novel_cnt=20)

    novels, _ = search(db_conn, sort="fav")

    assert ncodes_of(novels) == ["N0002BB", "N0003CC", "N0001AA"]


def test_検索_最終更新日の新しい順に並べ替えられる(db_conn):
    add_novel(db_conn, "N0001AA", general_lastup=datetime(2024, 1, 1))
    add_novel(db_conn, "N0002BB", general_lastup=datetime(2026, 1, 1))
    add_novel(db_conn, "N0003CC", general_lastup=datetime(2025, 1, 1))

    novels, _ = search(db_conn, sort="lastup")

    assert ncodes_of(novels) == ["N0002BB", "N0003CC", "N0001AA"]


def test_検索_limitとoffsetでページ分けし_総件数は全体の件数(db_conn):
    # global_point を 25, 24, ..., 1 にして、並び順を決める
    for i in range(25):
        add_novel(db_conn, f"N{i:04d}AA", global_point=25 - i)

    novels, total = search(db_conn, limit=20, offset=20)

    assert ncodes_of(novels) == [f"N{i:04d}AA" for i in range(20, 25)]
    assert total == 25


@pytest.mark.parametrize("offset", [3, 10**20])
def test_検索_offsetが総件数以上なら空のリストを返す(db_conn, offset):
    for i in range(3):
        add_novel(db_conn, f"N{i:04d}AA")

    novels, total = search(db_conn, offset=offset)

    assert novels == []
    assert total == 3


@pytest.mark.parametrize(
    ("word", "hit_title", "miss_title"),
    [
        # 特別扱いされると、% は「何文字でもよい」、_ は「任意の 1 文字」になってしまう
        ("100%", "100%達成", "1000達成"),
        ("a_b", "a_bの話", "axbの話"),
        ("a\\b", "a\\bの話", "abの話"),
    ],
)
def test_検索_記号は普通の文字として検索される(db_conn, word, hit_title, miss_title):
    add_novel(db_conn, "N0001AA", title=hit_title)
    add_novel(db_conn, "N0002BB", title=miss_title)

    novels, _ = search(db_conn, words=[word])

    assert ncodes_of(novels) == ["N0001AA"]


def test_検索_並び順に未知の値を渡すとValueError(db_conn):
    with pytest.raises(ValueError):
        search(db_conn, sort="title; DROP TABLE novels")
