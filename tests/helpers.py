"""複数のテストファイルで使う、テストデータの組み立て・
テスト用 DB の接続文字列・DB への投入と読み出し。"""

from datetime import datetime

import psycopg2.extras
from werkzeug.security import generate_password_hash

# compose.yaml の PostgreSQL 内にあるテスト専用 DB（開発用とは別）
TEST_DB_DSN = (
    "host=localhost port=5433 dbname=narou_search_test user=narou password=narou"
)


def make_raw_novel(ncode="N0001AA", **overrides):
    """なろう API が返す 1 件分（of=n-t-w-s-bg-g-k-gp-f-gl を指定したときの形）。"""
    raw = {
        "title": "テスト作品",
        "ncode": ncode,
        "writer": "テスト作者",
        "story": "テストのあらすじ",
        "biggenre": 2,
        "genre": 201,
        "keyword": "異世界 転生",
        "general_lastup": "2026-03-22 23:00:25",
        "global_point": 1000,
        "fav_novel_cnt": 200,
    }
    raw.update(overrides)
    return raw


def make_novel(ncode="N0001AA", **overrides):
    """DB に保存する 1 件分（to_novel が返す形）。"""
    novel = {
        "ncode": ncode,
        "title": "テスト作品",
        "writer": "テスト作者",
        "story": "テストのあらすじ",
        "biggenre": 2,
        "genre": 201,
        "keyword": "異世界 転生",
        "global_point": 1000,
        "fav_novel_cnt": 200,
        "general_lastup": datetime(2026, 3, 22, 23, 0, 25),
    }
    novel.update(overrides)
    return novel


def insert_novel(conn, ncode, fetched_at, **overrides):
    """テストの前提となる作品を、save_novels を通さずに直接 DB に入れる。"""
    novel = make_novel(ncode, **overrides)
    with conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO novels (ncode, title, writer, story, biggenre, genre,
                                keyword, global_point, fav_novel_cnt,
                                general_lastup, fetched_at)
            VALUES (%(ncode)s, %(title)s, %(writer)s, %(story)s, %(biggenre)s,
                    %(genre)s, %(keyword)s, %(global_point)s, %(fav_novel_cnt)s,
                    %(general_lastup)s, %(fetched_at)s)
            """,
            {**novel, "fetched_at": fetched_at},
        )


def add_novel(conn, ncode, **overrides):
    """検索・画面のテスト用に作品を入れる。指定しない項目は、どの検索語にも当たらない値にする。"""
    values = {
        "title": f"作品{ncode}",
        "writer": "作者",
        "story": "あらすじ",
        "keyword": None,
        **overrides,
    }
    # 検索は取得日時を見ないので、固定の値でよい
    insert_novel(conn, ncode, fetched_at=datetime(2026, 10, 27, 12, 0, 0), **values)


def fetch_novels_by_ncode(conn):
    """novels の全行を {ncode: 行の dict} の形で返す。"""
    with conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT * FROM novels;")
        return {row["ncode"]: row for row in cur.fetchall()}


def add_admin(conn, username, password):
    """テストの前提となる管理者を、create_admin.py を通さずに直接 DB に入れる。"""
    with conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO admins (username, password_hash) VALUES (%s, %s);",
            (username, generate_password_hash(password, method="scrypt")),
        )


def fetch_admins_by_username(conn):
    """admins の全行を {username: 行の dict} の形で返す。"""
    with conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT * FROM admins;")
        return {row["username"]: row for row in cur.fetchall()}


def novel_id_of(conn, ncode):
    """作品の id を返す（ベクトルは ncode ではなく id で結び付けるため）。"""
    with conn, conn.cursor() as cur:
        cur.execute("SELECT id FROM novels WHERE ncode = %s;", (ncode,))
        return cur.fetchone()[0]


def insert_embedding(
    conn, novel_id, embedding, model="gemini-embedding-2", source_hash="hash"
):
    """テストの前提となるベクトルを、save_embeddings を通さずに直接 DB に入れる。"""
    with conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO novel_embeddings
                (novel_id, embedding, model, source_hash, updated_at)
            VALUES (%s, %s, %s, %s, %s);
            """,
            (novel_id, embedding, model, source_hash, datetime(2026, 10, 28, 9, 0)),
        )


def fetch_embeddings_by_novel_id(conn):
    """novel_embeddings の全行を {novel_id: 行の dict} の形で返す。"""
    with conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT * FROM novel_embeddings;")
        return {row["novel_id"]: row for row in cur.fetchall()}
