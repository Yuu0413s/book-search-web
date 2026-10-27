from datetime import timedelta

# なろう API の利用ガイドライン「保存したデータは長くても 2 週間以内に更新か削除」に従う
STALE_DAYS = 14

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

        # 1 件ずつ実行する。複数行をまとめた INSERT だと、同じ ncode が
        # 2 回含まれたときに PostgreSQL がエラーにするため（100 件なので速度は問題ない）
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
