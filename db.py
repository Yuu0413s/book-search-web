from datetime import timedelta

import psycopg2.extras

# なろう API の利用ガイドライン「保存したデータは長くても 2 週間以内に更新か削除」に従う
STALE_DAYS = 14

# 並び順。ORDER BY の列名はプレースホルダで渡せず SQL に直接書くことになるので、
# 利用者の入力ではなく、必ずこの決まった文字列から選ぶ
SORT_ORDERS = {
    "point": "global_point DESC",
    "fav": "fav_novel_cnt DESC",
    "lastup": "general_lastup DESC",
}

# ILIKE のエスケープ文字。PostgreSQL の既定も「\」だが、既定に任せず明示する
LIKE_ESCAPE = r"ESCAPE '\'"

# created_at は「初めて DB に入った日時」なので、上書きのときは更新しない
UPSERT_NOVEL_SQL = """
INSERT INTO novels (ncode, title, writer, story, biggenre, genre, keyword,
                    global_point, fav_novel_cnt, general_lastup, fetched_at)
VALUES (%(ncode)s, %(title)s, %(writer)s, %(story)s, %(biggenre)s, %(genre)s,
        %(keyword)s, %(global_point)s, %(fav_novel_cnt)s, %(general_lastup)s,
        %(fetched_at)s)
ON CONFLICT (ncode) DO UPDATE SET
    title          = EXCLUDED.title,
    writer         = EXCLUDED.writer,
    story          = EXCLUDED.story,
    biggenre       = EXCLUDED.biggenre,
    genre          = EXCLUDED.genre,
    keyword        = EXCLUDED.keyword,
    global_point   = EXCLUDED.global_point,
    fav_novel_cnt  = EXCLUDED.fav_novel_cnt,
    general_lastup = EXCLUDED.general_lastup,
    fetched_at     = EXCLUDED.fetched_at;
"""


def save_novels(conn, novels, now):
    """作品を保存し（同じ ncode は上書き）、
    最終取得から STALE_DAYS 日を過ぎた作品を消す。

    すべて 1 つのトランザクションで行い、途中で失敗したら全部取り消す。
    novels の ncode は重複していない前提（narou.fetch_top_novels が保証する）。
    重複していると、追加件数が実際に増えた行数より多く数えられる。
    now は取り込み時刻で、タイムゾーン無しの JST（カラムが TIMESTAMP のため）。
    戻り値は {"added": 追加件数, "updated": 更新件数, "deleted": 削除件数}。
    """
    with conn, conn.cursor() as cur:
        # 取り込みが同時に走っても、既存の確認から保存までの間に
        # 割り込まれないようにする。このロック同士は待ち合うが、
        # 検索の SELECT は待たされない
        cur.execute("LOCK TABLE novels IN SHARE ROW EXCLUSIVE MODE;")

        cur.execute(
            "SELECT ncode FROM novels WHERE ncode = ANY(%s);",
            ([novel["ncode"] for novel in novels],),
        )
        existing_ncodes = {row[0] for row in cur.fetchall()}

        # 100 件程度なので、まとめて INSERT する書き方（execute_values など）は
        # 使わず、読みやすさを優先して 1 件ずつ実行する
        for novel in novels:
            cur.execute(UPSERT_NOVEL_SQL, {**novel, "fetched_at": now})

        # 保存の後に消す。今回取得した作品は fetched_at が now になっているので消えない
        cur.execute(
            "DELETE FROM novels WHERE fetched_at < %s;",
            (now - timedelta(days=STALE_DAYS),),
        )
        deleted_count = cur.rowcount

    return {
        "added": len(novels) - len(existing_ncodes),
        "updated": len(existing_ncodes),
        "deleted": deleted_count,
    }


def search_novels(conn, *, words, writer, genre, sort, limit, offset):
    """条件に合う作品を返す。戻り値は (作品の dict のリスト, 条件に合う総件数)。

    words: キーワードのリスト。すべての語が、タイトル・あらすじ・タグのどれかに
           含まれる作品だけを返す（空なら絞り込まない）
    writer: 作者名の一部（None なら絞り込まない）
    genre: ジャンルのコード（None なら絞り込まない）
    sort: SORT_ORDERS のキー
    """
    if sort not in SORT_ORDERS:
        raise ValueError(f"未知の並び順です: {sort!r}")

    # 条件の文字列は決まったものだけで組み立て、利用者の入力はすべて params で渡す
    conditions = []
    params = []
    for word in words:
        conditions.append(
            f"(title ILIKE %s {LIKE_ESCAPE}"
            f" OR story ILIKE %s {LIKE_ESCAPE}"
            f" OR keyword ILIKE %s {LIKE_ESCAPE})"
        )
        params += [_contains_pattern(word)] * 3
    if writer is not None:
        conditions.append(f"writer ILIKE %s {LIKE_ESCAPE}")
        params.append(_contains_pattern(writer))
    if genre is not None:
        conditions.append("genre = %s")
        params.append(genre)
    where = " AND ".join(conditions) if conditions else "TRUE"

    with conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        # 同じトランザクションでも、PostgreSQL の既定（READ COMMITTED）では
        # SQL ごとにその時点で確定した最新のデータを見るので、count と一覧の間に
        # 取り込みが確定すると件数と一覧がわずかにずれることがある。
        # 取り込みはまれで、再読み込みすれば直るので許容する
        cur.execute(f"SELECT count(*) AS total FROM novels WHERE {where};", params)
        total = cur.fetchone()["total"]

        # 巨大な offset を渡すと PostgreSQL の OFFSET が桁あふれしてエラーになるので、
        # 総件数以上なら一覧の SQL は実行しない（結果はどうせ空）
        if offset >= total:
            return [], total

        # 並び順が同じ作品の順番を id で決めておく。決めないと、ページを移動したときに
        # 同じ作品が 2 回出たり抜けたりすることがある
        cur.execute(
            f"SELECT * FROM novels WHERE {where}"
            f" ORDER BY {SORT_ORDERS[sort]}, id LIMIT %s OFFSET %s;",
            [*params, limit, offset],
        )
        return cur.fetchall(), total


def find_novel_by_ncode(conn, ncode):
    """作品を 1 件返す（novels の全列の dict）。無ければ None。"""
    with conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT * FROM novels WHERE ncode = %s;", (ncode,))
        return cur.fetchone()


def fetch_novels_by_ids(conn, ids):
    """ids の作品を {id: 作品の dict} で返す。無い id は含めない。

    ANY(...) は結果の順番を決めないので、並べ方は呼ぶ側に任せる。
    """
    if not ids:
        return {}
    with conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT * FROM novels WHERE id = ANY(%s);", (list(ids),))
        return {row["id"]: row for row in cur.fetchall()}


def _contains_pattern(text):
    """部分一致用の ILIKE パターンを作る。

    「\\」「%」「_」は ILIKE では特別な意味を持つので、普通の文字として扱うよう
    エスケープする（「\\」を最初に置き換えないと、後で足した「\\」まで二重になる）。
    """
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def create_admin(conn, username, password_hash):
    """管理者を追加する。

    同じユーザー名がいれば psycopg2.errors.UniqueViolation を投げる。
    """
    with conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO admins (username, password_hash) VALUES (%s, %s);",
            (username, password_hash),
        )


def find_admin_by_username(conn, username):
    """管理者を 1 人返す（id・username・password_hash の dict）。いなければ None。"""
    with conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT id, username, password_hash FROM admins WHERE username = %s;",
            (username,),
        )
        return cur.fetchone()


def get_import_status(conn):
    """管理画面に出す取り込みの状況。

    戻り値は {"novel_count": 作品数, "last_fetched_at": 最も新しい取得日時}。
    作品が無ければ last_fetched_at は None。
    """
    with conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT count(*) AS novel_count, max(fetched_at) AS last_fetched_at"
            " FROM novels;"
        )
        return dict(cur.fetchone())


def fetch_embedding_targets(conn):
    """ベクトル化が必要かを判定するための、全作品の一覧（id 順）。

    各作品の id・title・story・keyword と、保存済みのベクトルのモデル名と次元数
    （embedding_model。gemini.EMBEDDING_ID の形）・ハッシュ（embedding_hash）を返す。
    ベクトルが無い作品は、embedding_model・embedding_hash が None になる。
    """
    with conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            SELECT n.id, n.title, n.story, n.keyword,
                   e.model AS embedding_model, e.source_hash AS embedding_hash
            FROM novels AS n
            LEFT JOIN novel_embeddings AS e ON e.novel_id = n.id
            ORDER BY n.id;
            """
        )
        return cur.fetchall()


# 作品が消えていたら保存しない。WHERE EXISTS が偽なら SELECT が 0 行になり、
# INSERT も行われない
UPSERT_EMBEDDING_SQL = """
INSERT INTO novel_embeddings (novel_id, embedding, model, source_hash, updated_at)
SELECT %(novel_id)s, %(embedding)s, %(model)s, %(source_hash)s, %(updated_at)s
WHERE EXISTS (SELECT 1 FROM novels WHERE id = %(novel_id)s)
ON CONFLICT (novel_id) DO UPDATE SET
    embedding   = EXCLUDED.embedding,
    model       = EXCLUDED.model,
    source_hash = EXCLUDED.source_hash,
    updated_at  = EXCLUDED.updated_at;
"""


def save_embeddings(conn, embeddings, now):
    """作品のベクトルを保存し（同じ作品は上書き）、保存した件数を返す。

    embeddings は {"novel_id", "embedding", "model", "source_hash"} の dict のリスト。
    すでに消えた作品は保存せずに飛ばし、件数に数えない。
    同じ novel_id が 2 回あると、後のもので上書きされて件数が実際より多くなるので、
    何も保存せずに ValueError を投げる。
    すべて 1 つのトランザクションで行う。
    now は保存時刻で、タイムゾーン無しの JST（カラムが TIMESTAMP のため）。
    """
    novel_ids = [item["novel_id"] for item in embeddings]
    if len(set(novel_ids)) != len(novel_ids):
        raise ValueError("同じ作品のベクトルが 2 回以上含まれています")

    saved_count = 0
    with conn, conn.cursor() as cur:
        # 作品の一覧を取った後に取り込みで消えた作品は、UPSERT_EMBEDDING_SQL の
        # WHERE EXISTS で飛ばす。ただ、EXISTS を確かめてから INSERT するまでの間に
        # 消されると外部キー違反になるので、実行中の取り込み（save_novels のロック）
        # が終わるのを待ち、このトランザクションの間は消されないようにする。
        # 検索の SELECT は待たせない。
        # 一覧を取った後に内容が書き換わった作品は、書き換わる前のベクトルを保存する
        # ことになるが、source_hash が今の内容と合わないので、次の変換で作り直される
        cur.execute("LOCK TABLE novels IN SHARE MODE;")

        # 100 件程度なので、save_novels と同じく 1 件ずつ実行する
        for item in embeddings:
            cur.execute(UPSERT_EMBEDDING_SQL, {**item, "updated_at": now})
            saved_count += cur.rowcount

    return saved_count


def fetch_embeddings(conn, model):
    """model（gemini.EMBEDDING_ID）で変換したベクトルを、
    (作品の id, ベクトル) のリストで返す（id 順）。
    """
    with conn, conn.cursor() as cur:
        cur.execute(
            "SELECT novel_id, embedding FROM novel_embeddings"
            " WHERE model = %s ORDER BY novel_id;",
            (model,),
        )
        return cur.fetchall()
