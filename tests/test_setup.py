"""環境構築の動作確認用。テストランナーとテスト用 DB が動くことを確かめる。"""

import psycopg2


def test_トップページが200を返す(client):
    response = client.get("/")

    assert response.status_code == 200


def test_テスト用DBにテーブルが作られている(test_db):
    conn = psycopg2.connect(test_db)
    with conn, conn.cursor() as cur:
        cur.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' ORDER BY table_name;"
        )
        tables = [row[0] for row in cur.fetchall()]
    conn.close()

    assert tables == ["admins", "novel_embeddings", "novels"]
