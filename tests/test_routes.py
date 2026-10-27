import html
import re
from datetime import datetime
from urllib.parse import quote

import pytest

import myapp
from tests.helpers import insert_novel

NOW = datetime(2026, 10, 27, 12, 0, 0)


def add_novel(conn, ncode, **overrides):
    """画面のテスト用に作品を入れる。指定しない項目は、どの検索語にも当たらない値にする。"""
    values = {
        "title": f"作品{ncode}",
        "writer": "作者",
        "story": "あらすじ",
        "keyword": None,
        **overrides,
    }
    insert_novel(conn, ncode, fetched_at=NOW, **values)


def get_html(client, query="", **kwargs):
    response = client.get(f"/?{query}", **kwargs)
    assert response.status_code == 200
    return response.get_data(as_text=True)


def hrefs_containing(page_html, text):
    """ページ内のリンク先のうち、text を含むものを（&amp; などを戻して）返す。"""
    return [
        html.unescape(href)
        for href in re.findall(r'href="([^"]*)"', page_html)
        if text in html.unescape(href)
    ]


# --- 一覧の表示 ---


def test_条件なしで作品の一覧を表示する(client, db_conn):
    add_novel(
        db_conn,
        "N2710DB",
        title="とんでもスキルで異世界放浪メシ",
        writer="江口　連",
        genre=201,
        general_lastup=datetime(2026, 3, 22, 23, 0, 25),
        story="短いあらすじ",
    )

    page = get_html(client)

    assert "とんでもスキルで異世界放浪メシ" in page
    assert "江口　連" in page
    assert "ハイファンタジー〔ファンタジー〕" in page
    assert "2026-03-22" in page
    assert "短いあらすじ" in page


def test_タイトルのリンク先は小文字のncodeのURLで_別タブで開く(client, db_conn):
    add_novel(db_conn, "N2710DB")

    page = get_html(client)

    assert 'href="https://ncode.syosetu.com/n2710db/"' in page
    assert 'target="_blank"' in page
    assert 'rel="noopener noreferrer"' in page


def test_あらすじは200文字を超えたら先頭200文字と三点リーダーにする(client, db_conn):
    add_novel(db_conn, "N0001AA", story="あ" * 200)
    add_novel(db_conn, "N0002BB", story="い" * 201)

    page = get_html(client)

    assert "あ" * 200 in page
    assert "あ" * 200 + "…" not in page
    assert "い" * 200 + "…" in page
    assert "い" * 201 not in page


def test_タイトルにHTMLが含まれていてもエスケープして表示する(client, db_conn):
    add_novel(db_conn, "N0001AA", title="<script>alert(1)</script>")

    page = get_html(client)

    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page
    assert "<script>alert(1)</script>" not in page


# --- 検索条件 ---


def test_キーワードで絞り込める(client, db_conn):
    add_novel(db_conn, "N0001AA", title="異世界食堂")
    add_novel(db_conn, "N0002BB", title="現代劇")

    page = get_html(client, f"q={quote('異世界')}")

    assert "異世界食堂" in page
    assert "現代劇" not in page


def test_全角スペースで区切ってもすべての語を含む作品だけがヒットする(client, db_conn):
    add_novel(db_conn, "N0001AA", title="異世界の物語", story="転生する")
    add_novel(db_conn, "N0002BB", title="異世界の冒険", story="旅をする")

    page = get_html(client, f"q={quote('異世界　転生')}")

    assert "異世界の物語" in page
    assert "異世界の冒険" not in page


def test_作者_ジャンル_並べ替えの条件が反映される(client, db_conn):
    add_novel(db_conn, "N0001AA", title="対象・少", writer="山田", genre=201,
              fav_novel_cnt=10)  # fmt: skip
    add_novel(db_conn, "N0002BB", title="対象・多", writer="山田", genre=201,
              fav_novel_cnt=50)  # fmt: skip
    add_novel(db_conn, "N0003CC", title="作者違い", writer="佐藤", genre=201)
    add_novel(db_conn, "N0004DD", title="ジャンル違い", writer="山田", genre=101)

    page = get_html(client, f"writer={quote('山田')}&genre=201&sort=fav")

    assert page.index("対象・多") < page.index("対象・少")
    assert "作者違い" not in page
    assert "ジャンル違い" not in page


def test_フォームに今の検索条件が入っている(client, db_conn):
    add_novel(db_conn, "N0001AA", title="異世界", writer="山田", genre=201)

    page = get_html(
        client, f"q={quote('異世界')}&writer={quote('山田')}&genre=201&sort=fav"
    )

    assert 'value="異世界"' in page
    assert 'value="山田"' in page
    assert 'value="201" selected' in page
    assert 'value="fav" selected' in page


@pytest.mark.parametrize(
    "query",
    [
        "page=abc",
        "page=0",
        "page=-1",
        "sort=xxx",
        "genre=abc",
        "genre=12345",
        "q=&writer=&genre=",
    ],
)
def test_おかしなパラメータでも初期値で表示する(client, db_conn, query):
    add_novel(db_conn, "N0001AA", title="ポイント低", genre=101, global_point=10)
    add_novel(db_conn, "N0002BB", title="ポイント高", genre=201, global_point=20)

    page = get_html(client, query)

    # 全ジャンル・総合ポイント順・1 ページ目
    assert page.index("ポイント高") < page.index("ポイント低")


def test_条件に合う作品が無ければそう表示する(client, db_conn):
    add_novel(db_conn, "N0001AA", title="異世界食堂")

    page = get_html(client, f"q={quote('存在しない語')}")

    assert "条件に合う作品がありません" in page
    assert "異世界食堂" not in page


def test_範囲外のページならそう表示する(client, db_conn):
    add_novel(db_conn, "N0001AA", title="異世界食堂")

    page = get_html(client, "page=2")

    assert "このページには作品がありません" in page
    assert "異世界食堂" not in page


# --- ページ送り ---


def test_20件ずつ表示し_ページ送りのリンクは検索条件を引き継ぐ(client, db_conn):
    for i in range(25):
        add_novel(db_conn, f"N{i:04d}AA", title=f"異世界{i:02d}巻", global_point=25 - i)

    first_page = get_html(client, f"q={quote('異世界')}")
    second_page = get_html(client, f"q={quote('異世界')}&page=2")

    assert "異世界19巻" in first_page
    assert "異世界20巻" not in first_page
    assert "異世界20巻" in second_page
    assert "異世界24巻" in second_page
    assert "異世界19巻" not in second_page

    page2_links = hrefs_containing(first_page, "page=2")
    assert page2_links
    assert all(f"q={quote('異世界')}" in link for link in page2_links)


def test_URLの先頭にs2422016が付く環境ではリンクとCSSにも付く(client, db_conn):
    for i in range(25):
        add_novel(db_conn, f"N{i:04d}AA")

    page = get_html(client, base_url="http://localhost/s2422016/")

    assert hrefs_containing(page, "style.css")
    assert all(
        link.startswith("/s2422016/") for link in hrefs_containing(page, "style.css")
    )
    assert hrefs_containing(page, "page=2")
    assert all(
        link.startswith("/s2422016/") for link in hrefs_containing(page, "page=2")
    )
    assert 'action="/s2422016/"' in page


# --- DB 接続 ---


def test_get_dbは同じリクエストの中では同じ接続を返し_終わると閉じる(app):
    with app.app_context():
        first = myapp.get_db()
        second = myapp.get_db()
        assert first is second
        assert not first.closed

    assert first.closed
