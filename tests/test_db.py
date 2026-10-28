from datetime import datetime, timedelta

import psycopg2
import pytest

import db
from tests.helpers import (
    add_novel,
    fetch_admins_by_username,
    fetch_embeddings_by_novel_id,
    fetch_novels_by_ncode,
    insert_embedding,
    insert_novel,
    make_novel,
    novel_id_of,
)

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


# --- 管理者 ---


def test_管理者_ユーザー名とパスワードのハッシュを保存する(db_conn):
    db.create_admin(db_conn, "admin", "hashed-value")

    admins = fetch_admins_by_username(db_conn)
    assert set(admins) == {"admin"}
    assert admins["admin"]["password_hash"] == "hashed-value"


def test_管理者_同じユーザー名ならUniqueViolationになり既存の行は変わらない(db_conn):
    db.create_admin(db_conn, "admin", "old-hash")

    with pytest.raises(psycopg2.errors.UniqueViolation):
        db.create_admin(db_conn, "admin", "new-hash")

    assert fetch_admins_by_username(db_conn)["admin"]["password_hash"] == "old-hash"


def test_管理者_ユーザー名で1件取得できる(db_conn):
    db.create_admin(db_conn, "admin", "hashed-value")
    db.create_admin(db_conn, "other", "other-hash")

    admin = db.find_admin_by_username(db_conn, "admin")

    assert admin["username"] == "admin"
    assert admin["password_hash"] == "hashed-value"
    assert admin["id"] == fetch_admins_by_username(db_conn)["admin"]["id"]


def test_管理者_いないユーザー名ならNoneを返す(db_conn):
    db.create_admin(db_conn, "admin", "hashed-value")

    assert db.find_admin_by_username(db_conn, "nobody") is None


# --- 取り込みの状況 ---


def test_取り込み状況_作品が無ければ件数0で日時はNone(db_conn):
    assert db.get_import_status(db_conn) == {
        "novel_count": 0,
        "last_fetched_at": None,
    }


def test_取り込み状況_作品の件数と最も新しい取得日時を返す(db_conn):
    insert_novel(db_conn, "N0001AA", fetched_at=NOW - timedelta(days=3))
    insert_novel(db_conn, "N0002BB", fetched_at=NOW)
    insert_novel(db_conn, "N0003CC", fetched_at=NOW - timedelta(days=1))

    assert db.get_import_status(db_conn) == {
        "novel_count": 3,
        "last_fetched_at": NOW,
    }


# --- AI 検索のベクトル ---

MODEL = "gemini-embedding-2"


def make_embedding(novel_id, embedding=(0.1, 0.2, 0.3), **overrides):
    """save_embeddings に渡す 1 件分。"""
    item = {
        "novel_id": novel_id,
        "embedding": list(embedding),
        "model": MODEL,
        "source_hash": "hash",
    }
    item.update(overrides)
    return item


def test_変換対象_ベクトルがある作品はモデル名とハッシュ付きで_無い作品はNoneで返す(
    db_conn,
):
    add_novel(db_conn, "N0001AA", title="一作目", story="あらすじ1", keyword="タグ")
    add_novel(db_conn, "N0002BB", title="二作目", story="あらすじ2", keyword=None)
    first_id = novel_id_of(db_conn, "N0001AA")
    second_id = novel_id_of(db_conn, "N0002BB")
    insert_embedding(db_conn, first_id, [0.1, 0.2], source_hash="abc")

    assert db.fetch_embedding_targets(db_conn) == [
        {
            "id": first_id,
            "title": "一作目",
            "story": "あらすじ1",
            "keyword": "タグ",
            "embedding_model": MODEL,
            "embedding_hash": "abc",
        },
        {
            "id": second_id,
            "title": "二作目",
            "story": "あらすじ2",
            "keyword": None,
            "embedding_model": None,
            "embedding_hash": None,
        },
    ]


def test_変換対象_作品のidの順に返す(db_conn):
    for ncode in ["N0003CC", "N0001AA", "N0002BB"]:
        add_novel(db_conn, ncode)

    ids = [target["id"] for target in db.fetch_embedding_targets(db_conn)]

    assert ids == sorted(ids)
    assert len(ids) == 3


def test_変換対象_作品が無ければ空のリスト(db_conn):
    assert db.fetch_embedding_targets(db_conn) == []


def test_ベクトル保存_保存でき_ほぼ同じ値で読み出せる(db_conn):
    add_novel(db_conn, "N0001AA")
    novel_id = novel_id_of(db_conn, "N0001AA")

    saved = db.save_embeddings(
        db_conn,
        [make_embedding(novel_id, [0.1, -0.2, 0.3], source_hash="abc")],
        NOW,
    )

    assert saved == 1
    row = fetch_embeddings_by_novel_id(db_conn)[novel_id]
    # REAL（4 バイトの小数）で保存するので、丸めの誤差がある
    assert row["embedding"] == pytest.approx([0.1, -0.2, 0.3], rel=1e-6)
    assert row["model"] == MODEL
    assert row["source_hash"] == "abc"
    assert row["updated_at"] == NOW


def test_ベクトル保存_同じ作品なら上書きされ行は増えない(db_conn):
    add_novel(db_conn, "N0001AA")
    novel_id = novel_id_of(db_conn, "N0001AA")
    insert_embedding(db_conn, novel_id, [0.1, 0.2], model="old-model")
    later = NOW + timedelta(days=1)

    saved = db.save_embeddings(
        db_conn,
        [make_embedding(novel_id, [0.5, 0.6], source_hash="new-hash")],
        later,
    )

    assert saved == 1
    rows = fetch_embeddings_by_novel_id(db_conn)
    assert list(rows) == [novel_id]
    assert rows[novel_id]["embedding"] == pytest.approx([0.5, 0.6], rel=1e-6)
    assert rows[novel_id]["model"] == MODEL
    assert rows[novel_id]["source_hash"] == "new-hash"
    assert rows[novel_id]["updated_at"] == later


def test_ベクトル保存_すでに消えた作品は飛ばし_件数に数えない(db_conn):
    # 作品の一覧を取ってから保存するまでの間に、取り込みで作品が消された場合
    add_novel(db_conn, "N0001AA")
    add_novel(db_conn, "N0002BB")
    kept_id = novel_id_of(db_conn, "N0001AA")
    deleted_id = novel_id_of(db_conn, "N0002BB")
    with db_conn, db_conn.cursor() as cur:
        cur.execute("DELETE FROM novels WHERE id = %s;", (deleted_id,))

    saved = db.save_embeddings(
        db_conn, [make_embedding(kept_id), make_embedding(deleted_id)], NOW
    )

    assert saved == 1
    assert list(fetch_embeddings_by_novel_id(db_conn)) == [kept_id]


def test_ベクトル保存_同じ作品が2回あればValueErrorで何も保存しない(db_conn):
    add_novel(db_conn, "N0001AA")
    add_novel(db_conn, "N0002BB")
    first_id = novel_id_of(db_conn, "N0001AA")
    second_id = novel_id_of(db_conn, "N0002BB")

    with pytest.raises(ValueError):
        db.save_embeddings(
            db_conn,
            [
                make_embedding(first_id),
                make_embedding(second_id),
                make_embedding(first_id, [0.9, 0.9, 0.9]),
            ],
            NOW,
        )

    assert fetch_embeddings_by_novel_id(db_conn) == {}


def test_ベクトル保存_空のリストなら0件(db_conn):
    assert db.save_embeddings(db_conn, [], NOW) == 0


def test_ベクトル読み出し_指定したモデルのものだけを作品のid順に返す(db_conn):
    for ncode in ["N0001AA", "N0002BB", "N0003CC"]:
        add_novel(db_conn, ncode)
    first_id, second_id, third_id = (
        novel_id_of(db_conn, ncode) for ncode in ["N0001AA", "N0002BB", "N0003CC"]
    )
    # わざと id の逆順に入れる
    insert_embedding(db_conn, third_id, [0.3, 0.3])
    insert_embedding(db_conn, second_id, [0.2, 0.2], model="old-model")
    insert_embedding(db_conn, first_id, [0.1, 0.1])

    result = db.fetch_embeddings(db_conn, MODEL)

    assert [novel_id for novel_id, _ in result] == [first_id, third_id]
    assert result[0][1] == pytest.approx([0.1, 0.1], rel=1e-6)
    assert result[1][1] == pytest.approx([0.3, 0.3], rel=1e-6)


def test_ベクトル読み出し_無ければ空のリスト(db_conn):
    assert db.fetch_embeddings(db_conn, MODEL) == []


def test_作品を消すとベクトルも消える(db_conn):
    add_novel(db_conn, "N0001AA")
    novel_id = novel_id_of(db_conn, "N0001AA")
    insert_embedding(db_conn, novel_id, [0.1, 0.2])

    with db_conn, db_conn.cursor() as cur:
        cur.execute("DELETE FROM novels WHERE id = %s;", (novel_id,))

    assert fetch_embeddings_by_novel_id(db_conn) == {}


def test_取り込みで14日を過ぎた作品が消えると_そのベクトルも消える(db_conn):
    insert_novel(db_conn, "N0001AA", fetched_at=NOW - timedelta(days=15))
    insert_novel(db_conn, "N0002BB", fetched_at=NOW - timedelta(days=15))
    stale_id = novel_id_of(db_conn, "N0001AA")
    kept_id = novel_id_of(db_conn, "N0002BB")
    insert_embedding(db_conn, stale_id, [0.1, 0.2])
    insert_embedding(db_conn, kept_id, [0.3, 0.4])

    # N0002BB だけ今回も取得できたので残り、N0001AA は消える
    db.save_novels(db_conn, [make_novel("N0002BB")], NOW)

    assert list(fetch_embeddings_by_novel_id(db_conn)) == [kept_id]
