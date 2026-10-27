"""複数のテストファイルで使う、テストデータの組み立て・
テスト用 DB の接続文字列・DB への投入と読み出し。"""

from datetime import datetime

import psycopg2.extras

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


def fetch_novels_by_ncode(conn):
    """novels の全行を {ncode: 行の dict} の形で返す。"""
    with conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT * FROM novels;")
        return {row["ncode"]: row for row in cur.fetchall()}
