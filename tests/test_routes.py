import html
import re
from datetime import datetime
from urllib.parse import quote

import pytest
import requests

import db
import gemini
import myapp
from tests.helpers import add_novel, add_novel_with_vector, use_fake_embed_text

UNAVAILABLE_MESSAGE = "AI 検索が一時的に使えません。キーワード検索をお使いください"
NOT_READY_MESSAGE = "AI 検索の準備ができていません"
GUIDE_MESSAGE = "数字が大きいほど内容が近い（目安）"


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

    # フッターのリンクにも target・rel があるので、作品リンクのタグ全体で確かめる
    assert (
        '<a href="https://ncode.syosetu.com/n2710db/" target="_blank" '
        'rel="noopener noreferrer">' in page
    )


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
        "q=%00",
        "writer=%00",
    ],
)
def test_おかしなパラメータでも初期値で表示する(client, db_conn, query):
    add_novel(db_conn, "N0001AA", title="ポイント低", genre=101, global_point=10)
    add_novel(db_conn, "N0002BB", title="ポイント高", genre=201, global_point=20)

    page = get_html(client, query)

    # 全ジャンル・総合ポイント順・1 ページ目
    assert page.index("ポイント高") < page.index("ポイント低")


def test_キーワードは先頭10語まで使い_11語目以降は無視する(client, db_conn):
    add_novel(db_conn, "N0001AA", title="あいうえおかきくけこ")

    # 11 語目の「ん」はタイトルに無いが、無視されるので作品は出る
    page = get_html(client, f"q={quote('あ い う え お か き く け こ ん')}")

    assert "あいうえおかきくけこ" in page


def test_同じキーワードは1語として数える(client, db_conn):
    add_novel(db_conn, "N0001AA", title="あいうえお")

    # 「あ」10 個は 1 語にまとまるので、2 語目の「ん」で絞り込まれて 0 件になる
    page = get_html(client, f"q={quote('あ ' * 10 + 'ん')}")

    assert "条件に合う作品がありません" in page


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


# --- タブ ---


def test_キーワード検索の画面に_AI検索のタブがある(client, db_conn):
    page = get_html(client)

    assert hrefs_containing(page, "mode=ai")
    assert 'name="writer"' in page


def test_AI検索のタブでは文章の欄だけを出し_作者_ジャンル_並び順の欄は出さない(
    client, db_conn
):
    page = get_html(client, "mode=ai")

    assert 'name="q"' in page
    assert 'name="mode" value="ai"' in page
    for name in ["writer", "genre", "sort"]:
        assert f'name="{name}"' not in page
    assert re.search(r'<a [^>]*href="/"[^>]*>キーワード検索</a>', page)


@pytest.mark.parametrize("mode", ["AI", "keyword", ""])
def test_modeがai以外ならキーワード検索になる(client, db_conn, monkeypatch, mode):
    add_novel_with_vector(db_conn, "N0001AA", 0.9)
    fake = use_fake_embed_text(monkeypatch)

    page = get_html(client, f"mode={mode}&q=abc")

    assert 'name="writer"' in page
    assert fake.calls == []


# --- AI 検索 ---


def ai_search_query(text):
    return f"mode=ai&q={quote(text)}"


def test_AI検索_近い順に作品と類似度を表示し_目安だと添える(
    client, db_conn, monkeypatch
):
    add_novel_with_vector(db_conn, "N0001AA", 0.6, title="遠い作品")
    add_novel_with_vector(db_conn, "N0002BB", 0.8234, title="近い作品")
    fake = use_fake_embed_text(monkeypatch)

    page = get_html(client, ai_search_query("切ない恋の話"))

    assert page.index("近い作品") < page.index("遠い作品")
    # 類似度は 100 倍して四捨五入した整数で出す
    assert "類似度 82%" in page
    assert "類似度 60%" in page
    assert GUIDE_MESSAGE in page
    assert fake.calls == [
        ("task: search result | query: 切ない恋の話", "test-gemini-key")
    ]
    # 入力した文章はフォームに残す
    assert 'value="切ない恋の話"' in page


def test_類似度のパーセントは_100倍して四捨五入した整数にする():
    # 切り捨てなら 87 になる値で確かめる（0.8234 や 0.6 は、どちらでも同じ結果になる）
    assert myapp.percent(0.876) == 88
    assert myapp.percent(0.874) == 87


def test_AI検索_上位20件だけを表示する(client, db_conn, monkeypatch):
    for i in range(25):
        add_novel_with_vector(db_conn, f"N{i:04d}AA", 0.5 + i * 0.01)
    use_fake_embed_text(monkeypatch)

    page = get_html(client, ai_search_query("切ない恋の話"))

    assert page.count('class="card novel"') == 20


def test_AI検索_各作品に似ている作品へのリンクがある(client, db_conn, monkeypatch):
    add_novel_with_vector(db_conn, "N0001AA", 0.9)
    use_fake_embed_text(monkeypatch)

    page = get_html(client, ai_search_query("切ない恋の話"))

    assert hrefs_containing(page, "/novels/N0001AA/similar")


@pytest.mark.parametrize("query", ["mode=ai", "mode=ai&q=", "mode=ai&q=%E3%80%80+"])
def test_AI検索_入力が空か空白だけなら_APIを呼ばず結果も出さない(
    client, db_conn, monkeypatch, query
):
    # ベクトルを入れておき、検索が走れば結果が出る状態にする
    add_novel_with_vector(db_conn, "N0001AA", 0.9)
    fake = use_fake_embed_text(monkeypatch)

    page = get_html(client, query)

    assert fake.calls == []
    assert "類似度" not in page
    assert NOT_READY_MESSAGE not in page


def test_AI検索_ちょうど200文字なら検索する(client, db_conn, monkeypatch):
    add_novel_with_vector(db_conn, "N0001AA", 0.9)
    fake = use_fake_embed_text(monkeypatch)

    page = get_html(client, ai_search_query("あ" * 200))

    assert len(fake.calls) == 1
    assert "類似度 90%" in page


def test_AI検索_200文字を超えたら_APIを呼ばずに注意を出す(client, db_conn, monkeypatch):
    add_novel_with_vector(db_conn, "N0001AA", 0.9)
    fake = use_fake_embed_text(monkeypatch)

    page = get_html(client, ai_search_query("あ" * 201))

    assert fake.calls == []
    assert "200 文字以内で入力してください" in page
    assert "類似度" not in page


def test_AI検索_比べるベクトルが無ければ_APIを呼ばずに準備ができていないと出す(
    client, db_conn, monkeypatch
):
    add_novel(db_conn, "N0001AA")
    fake = use_fake_embed_text(monkeypatch)

    page = get_html(client, ai_search_query("切ない恋の話"))

    assert fake.calls == []
    assert NOT_READY_MESSAGE in page


def test_AI検索_Geminiで失敗したら503で案内を出し_理由をエラーログに残す(
    client, db_conn, monkeypatch, caplog
):
    add_novel_with_vector(db_conn, "N0001AA", 0.9)
    use_fake_embed_text(monkeypatch, error=gemini.GeminiApiError("テスト用の変換失敗"))

    response = client.get(f"/?{ai_search_query('切ない恋の話')}")

    assert response.status_code == 503
    page = response.get_data(as_text=True)
    assert UNAVAILABLE_MESSAGE in page
    # 詳しい理由は画面に出さず、エラーログにだけ残す
    assert "テスト用の変換失敗" not in page
    assert "テスト用の変換失敗" in caplog.text


def test_AI検索_APIキーの形が正しくなくても_キーの値は画面にもエラーログにも出ない(
    app, client, db_conn, monkeypatch, caplog
):
    # 先頭の改行は、そのまま送ると requests の例外の文言にキーの値が入る形
    add_novel_with_vector(db_conn, "N0001AA", 0.9)
    monkeypatch.setitem(app.config, "GEMINI_API_KEY", "\nsecret-gemini-key")
    post_calls = []

    def fake_post(*args, **kwargs):
        post_calls.append(kwargs)
        raise requests.ConnectionError("テスト用の通信エラー")

    monkeypatch.setattr(gemini.requests, "post", fake_post)

    response = client.get(f"/?{ai_search_query('切ない恋の話')}")

    assert response.status_code == 503
    assert post_calls == []
    assert "GEMINI_API_KEY" in caplog.text
    assert "secret-gemini-key" not in caplog.text
    assert "secret-gemini-key" not in response.get_data(as_text=True)


def test_キーワード検索の作品にも_似ている作品へのリンクがある(client, db_conn):
    add_novel(db_conn, "N2710DB")

    page = get_html(client)

    assert hrefs_containing(page, "/novels/N2710DB/similar")


def test_URLの先頭にs2422016が付く環境では_タブと似ている作品のリンクにも付く(
    client, db_conn, monkeypatch
):
    add_novel_with_vector(db_conn, "N0001AA", 0.9)
    use_fake_embed_text(monkeypatch)

    page = get_html(
        client, ai_search_query("切ない恋の話"), base_url="http://localhost/s2422016/"
    )

    links = hrefs_containing(page, "mode=ai") + hrefs_containing(page, "/similar")
    assert hrefs_containing(page, "mode=ai")
    assert hrefs_containing(page, "/similar")
    assert all(link.startswith("/s2422016/") for link in links)
    assert 'action="/s2422016/"' in page


# --- 似ている作品 ---


def test_似ている作品_元の作品と_近い順のほかの作品と類似度を出し_APIは呼ばない(
    client, db_conn, monkeypatch
):
    add_novel_with_vector(db_conn, "N0001AA", 1.0, title="元の作品")
    add_novel_with_vector(db_conn, "N0002BB", 0.6, title="遠い作品")
    add_novel_with_vector(db_conn, "N0003CC", 0.8234, title="近い作品")
    fake = use_fake_embed_text(monkeypatch)

    response = client.get("/novels/N0001AA/similar")

    assert response.status_code == 200
    page = response.get_data(as_text=True)
    assert page.index("元の作品") < page.index("近い作品") < page.index("遠い作品")
    assert "類似度 82%" in page
    assert "類似度 60%" in page
    assert GUIDE_MESSAGE in page
    # 元の作品は一覧に入れない（入れば類似度 100% のカードが出る）
    assert "類似度 100%" not in page
    assert page.count('class="card novel"') == 3
    assert fake.calls == []


def test_似ている作品_上位20件だけを表示する(client, db_conn):
    add_novel_with_vector(db_conn, "N9999ZZ", 1.0)
    for i in range(25):
        add_novel_with_vector(db_conn, f"N{i:04d}AA", 0.5 + i * 0.01)

    page = client.get("/novels/N9999ZZ/similar").get_data(as_text=True)

    # 元の作品のカード 1 枚と、似ている作品 20 枚
    assert page.count('class="card novel"') == 21


def test_似ている作品_無い作品なら404(client, db_conn):
    add_novel_with_vector(db_conn, "N0001AA", 1.0)

    assert client.get("/novels/N9999ZZ/similar").status_code == 404


def test_似ている作品_小文字のncodeでも同じ作品を出す(client, db_conn):
    add_novel_with_vector(db_conn, "N0001AA", 1.0, title="元の作品")
    add_novel_with_vector(db_conn, "N0002BB", 0.9, title="近い作品")

    response = client.get("/novels/n0001aa/similar")

    assert response.status_code == 200
    page = response.get_data(as_text=True)
    assert "元の作品" in page
    assert "類似度 90%" in page


def test_似ている作品_元の作品にベクトルが無ければ_準備ができていないと出す(
    client, db_conn
):
    add_novel(db_conn, "N0001AA", title="元の作品")
    add_novel_with_vector(db_conn, "N0002BB", 0.9, title="近い作品")

    response = client.get("/novels/N0001AA/similar")

    assert response.status_code == 200
    page = response.get_data(as_text=True)
    assert "元の作品" in page
    assert "この作品はまだ AI 検索の準備ができていません" in page
    assert "近い作品" not in page


def test_似ている作品_ほかの作品が無ければそう出す(client, db_conn):
    add_novel_with_vector(db_conn, "N0001AA", 1.0, title="元の作品")

    response = client.get("/novels/N0001AA/similar")

    assert response.status_code == 200
    page = response.get_data(as_text=True)
    assert "元の作品" in page
    assert "似ている作品がありません" in page


# --- DB 接続 ---


def test_get_dbは同じリクエストの中では同じ接続を返し_終わると閉じる(app):
    with app.app_context():
        first = myapp.get_db()
        second = myapp.get_db()
        assert first is second
        assert not first.closed

    assert first.closed


def test_並び順の表示名はDBの並び順と同じキーを持つ():
    assert myapp.SORT_LABELS.keys() == db.SORT_ORDERS.keys()


def test_DBのエラーは種類名だけをログに出して500を返す(
    app, client, monkeypatch, caplog
):
    # 書式の誤った接続文字列。psycopg2 の例外の文言には「RETPW」が含まれる
    monkeypatch.setitem(app.config, "DB_DSN", "host=localhost password=SEC RETPW")

    response = client.get("/")

    assert response.status_code == 500
    assert "ProgrammingError" in caplog.text
    assert "RETPW" not in caplog.text
    assert "RETPW" not in response.get_data(as_text=True)
