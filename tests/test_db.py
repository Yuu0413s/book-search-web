from datetime import datetime, timedelta

import psycopg2
import pytest

import db
from tests.helpers import fetch_novels_by_ncode, insert_novel, make_novel

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
