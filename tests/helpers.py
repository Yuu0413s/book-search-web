"""複数のテストファイルで使う、テストデータの組み立て・
テスト用 DB の接続文字列・DB への投入と読み出し。"""

from datetime import datetime

import psycopg2.extras
import requests
from werkzeug.security import generate_password_hash

import ai_search
import gemini

# compose.yaml の PostgreSQL 内にあるテスト専用 DB（開発用とは別）
TEST_DB_DSN = (
    "host=localhost port=5433 dbname=narou_search_test user=narou password=narou"
)

# novel_embeddings.model に入る値（gemini.EMBEDDING_ID）。テストは仕様書なので、
# 実装の定数を参照せずに書く
EMBEDDING_ID = "gemini-embedding-2:768"
EMBEDDING_DIMENSIONS = 768


class FakeResponse:
    """requests.get / requests.post の戻り値の代わり。"""

    def __init__(self, json_data=None, status_code=200, invalid_json=False):
        self.json_data = json_data
        self.status_code = status_code
        self.invalid_json = invalid_json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} Error")

    def json(self):
        if self.invalid_json:
            raise requests.JSONDecodeError("Expecting value", "<html>", 0)
        return self.json_data


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


def insert_embedding(conn, novel_id, embedding, model=EMBEDDING_ID, source_hash="hash"):
    """テストの前提となるベクトルを、save_embeddings を通さずに直接 DB に入れる。"""
    # 更新日時は固定の値にする。test_embedding は、この値が保存時刻（NOW）と違うことで
    # 「変換済みの作品を保存し直していない」を確かめるので、NOW と同じ値にしない
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


def add_embedded_novel(conn, ncode, model=EMBEDDING_ID, **overrides):
    """今の内容でベクトル化済みの作品を入れる。

    model を変えれば、別のモデルで変換済みの作品になる。
    """
    add_novel(conn, ncode, **overrides)
    novel = fetch_novels_by_ncode(conn)[ncode]
    insert_embedding(
        conn,
        novel["id"],
        [0.1] * EMBEDDING_DIMENSIONS,
        model=model,
        source_hash=ai_search.source_hash(ai_search.document_text(novel)),
    )


class FakeEmbedTexts:
    """gemini.embed_texts の代わり（実際の API は呼ばない）。

    呼ばれるたびに、送られた文章のリストを calls に、キーを api_keys に記録する。
    errors は {何回目の呼び出しか（1 から）: 投げる例外}。
    文章ごとに違うベクトルを返し、vectors_by_text でどの文章に何を返したか引ける。
    値は 0.25 刻みにして、DB の REAL（4 バイトの小数）に入れても丸めで
    変わらないようにする。
    """

    def __init__(self, errors=None):
        self.calls = []
        self.api_keys = []
        self.errors = errors or {}
        self.vectors_by_text = {}

    def __call__(self, texts, api_key):
        self.calls.append(list(texts))
        self.api_keys.append(api_key)
        error = self.errors.get(len(self.calls))
        if error is not None:
            raise error
        return [self._vector_for(text) for text in texts]

    def _vector_for(self, text):
        if text not in self.vectors_by_text:
            number = len(self.vectors_by_text) + 1
            self.vectors_by_text[text] = [number * 0.25] * EMBEDDING_DIMENSIONS
        return self.vectors_by_text[text]


def use_embed_errors(monkeypatch, errors):
    """gemini.embed_texts を FakeEmbedTexts に差し替えて返す。

    errors は {何回目の呼び出しか（1 から）: 投げる例外}。空なら常に成功する。
    """
    fake = FakeEmbedTexts(errors=errors)
    monkeypatch.setattr(gemini, "embed_texts", fake)
    return fake
