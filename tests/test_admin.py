import re
from datetime import datetime, timedelta

import pytest

import myapp
import narou
from tests.helpers import (
    add_admin,
    fetch_novels_by_ncode,
    insert_novel,
    make_novel,
)

USERNAME = "admin"
PASSWORD = "correct-horse"
LOGIN_ERROR = "ユーザー名またはパスワードが違います"


def csrf_token_in(page_html):
    """フォームに埋め込まれた CSRF トークンを取り出す。"""
    match = re.search(r'name="csrf_token" value="([^"]+)"', page_html)
    assert match is not None
    return match.group(1)


def page_csrf_token(client, path):
    response = client.get(path)
    assert response.status_code == 200
    return csrf_token_in(response.get_data(as_text=True))


def log_in(client, username=USERNAME, password=PASSWORD):
    token = page_csrf_token(client, "/admin/login")
    return client.post(
        "/admin/login",
        data={"csrf_token": token, "username": username, "password": password},
    )


def assert_logged_out(client):
    response = client.get("/admin")
    assert response.status_code == 302
    assert response.headers["Location"] == "/admin/login"


@pytest.fixture
def admin_client(client, db_conn):
    """ログイン済みのクライアント。"""
    add_admin(db_conn, USERNAME, PASSWORD)
    assert log_in(client).status_code == 302
    return client


@pytest.fixture
def fetch_calls(monkeypatch):
    """なろう API の取得を差し替え、呼ばれた回数を記録する（実際の API は呼ばない）。"""
    calls = []

    def fake_fetch():
        calls.append(1)
        return [make_novel("N0001AA")]

    monkeypatch.setattr(narou, "fetch_top_novels", fake_fetch)
    return calls


# --- https への切り替え ---


def test_SECUREがTrueでhttpなら_同じURLのhttps版へ302で切り替える(
    client, db_conn, monkeypatch
):
    monkeypatch.setitem(client.application.config, "SESSION_COOKIE_SECURE", True)

    response = client.get("/?q=abc&page=2", base_url="http://localhost/s2422016/")

    assert response.status_code == 302
    assert response.headers["Location"] == "https://localhost/s2422016/?q=abc&page=2"


def test_SECUREがTrueでもhttpsなら切り替えない(client, db_conn, monkeypatch):
    monkeypatch.setitem(client.application.config, "SESSION_COOKIE_SECURE", True)

    response = client.get("/", base_url="https://localhost/s2422016/")

    assert response.status_code == 200


def test_SECUREがFalseならhttpでも切り替えない(client, db_conn):
    response = client.get("/", base_url="http://localhost/s2422016/")

    assert response.status_code == 200


# --- ログイン ---


def test_ログイン画面のフォームにCSRFトークンが入っている(client, db_conn):
    assert page_csrf_token(client, "/admin/login") != ""


def test_正しいユーザー名とパスワードならログインして管理画面へ移る(client, db_conn):
    add_admin(db_conn, USERNAME, PASSWORD)

    response = log_in(client)

    assert response.status_code == 302
    assert response.headers["Location"] == "/admin"
    assert client.get("/admin").status_code == 200


def test_ログインのCookieにはSameSite_LaxとHttpOnlyが付く(client, db_conn):
    add_admin(db_conn, USERNAME, PASSWORD)

    response = log_in(client)

    cookies = [
        cookie
        for cookie in response.headers.getlist("Set-Cookie")
        if cookie.startswith("narou_search_session=")
    ]
    assert len(cookies) == 1
    assert "SameSite=Lax" in cookies[0]
    assert "HttpOnly" in cookies[0]


def test_ユーザー名の前後の空白は取り除いて照合する(client, db_conn):
    add_admin(db_conn, USERNAME, PASSWORD)

    response = log_in(client, username=f"  {USERNAME}  ")

    assert response.status_code == 302
    assert response.headers["Location"] == "/admin"


@pytest.mark.parametrize(
    ("username", "password"),
    [
        (USERNAME, "wrong-password"),
        ("nobody", PASSWORD),
        ("", ""),
        # NUL 文字は psycopg2 が SQL に渡せないので、500 にならないことを確かめる
        ("\x00", PASSWORD),
    ],
)
def test_ユーザー名かパスワードが違えば同じ文言で401になりログインしない(
    client, db_conn, username, password
):
    add_admin(db_conn, USERNAME, PASSWORD)

    response = log_in(client, username=username, password=password)

    assert response.status_code == 401
    assert LOGIN_ERROR in response.get_data(as_text=True)
    assert_logged_out(client)


def test_ユーザーがいないときも_同じ方式のハッシュでパスワードの照合を1回行う(
    client, db_conn, monkeypatch
):
    checked_hashes = []
    original = myapp.check_password_hash

    def spy(password_hash, password):
        checked_hashes.append(password_hash)
        return original(password_hash, password)

    monkeypatch.setattr(myapp, "check_password_hash", spy)

    response = log_in(client, username="nobody")

    assert response.status_code == 401
    assert len(checked_hashes) == 1
    assert checked_hashes[0].startswith("scrypt:")


def test_ログイン前にsessionに入っていた値はログイン後に残らない(client, db_conn):
    add_admin(db_conn, USERNAME, PASSWORD)
    with client.session_transaction() as session:
        session["planted"] = "攻撃者が仕込んだ値"

    log_in(client)

    with client.session_transaction() as session:
        assert "planted" not in session


def test_ログイン前のCSRFトークンはログイン後に使えない(client, db_conn, fetch_calls):
    add_admin(db_conn, USERNAME, PASSWORD)
    token_before_login = page_csrf_token(client, "/admin/login")
    client.post(
        "/admin/login",
        data={
            "csrf_token": token_before_login,
            "username": USERNAME,
            "password": PASSWORD,
        },
    )

    response = client.post("/admin/import", data={"csrf_token": token_before_login})

    assert response.status_code == 400
    assert fetch_calls == []


def test_ログイン済みでログイン画面を開くと管理画面へ移る(admin_client):
    response = admin_client.get("/admin/login")

    assert response.status_code == 302
    assert response.headers["Location"] == "/admin"


# --- ログイン必須 ---


def test_ログインせずに管理画面を開くとログイン画面へ移る(client, db_conn):
    assert_logged_out(client)


@pytest.mark.parametrize("path", ["/admin/import", "/admin/logout"])
def test_ログインせずにPOSTするとログイン画面へ移り_何も実行しない(
    client, db_conn, fetch_calls, path
):
    # CSRF トークンは正しいものを送り、ログインしていないことだけで弾かれるか確かめる
    token = page_csrf_token(client, "/admin/login")

    response = client.post(path, data={"csrf_token": token})

    assert response.status_code == 302
    assert response.headers["Location"] == "/admin/login"
    assert fetch_calls == []


# --- 管理画面 ---


def test_管理画面に作品数と最終取り込み日時を表示する(admin_client, db_conn):
    insert_novel(db_conn, "N0001AA", fetched_at=datetime(2026, 10, 20, 9, 0, 0))
    insert_novel(db_conn, "N0002BB", fetched_at=datetime(2026, 10, 27, 12, 34, 56))

    page = admin_client.get("/admin").get_data(as_text=True)

    assert "2 件" in page
    assert "2026-10-27 12:34" in page


def test_作品が無ければまだ取り込んでいないと表示する(admin_client, db_conn):
    page = admin_client.get("/admin").get_data(as_text=True)

    assert "まだ取り込んでいません" in page


# --- 取り込み ---


def test_取り込みに成功すると管理画面へ移り_結果を1回だけ表示する(
    admin_client, db_conn, monkeypatch
):
    novels = [make_novel("N0001AA"), make_novel("N0002BB")]
    monkeypatch.setattr(narou, "fetch_top_novels", lambda: novels)
    token = page_csrf_token(admin_client, "/admin")

    response = admin_client.post("/admin/import", data={"csrf_token": token})

    assert response.status_code == 302
    assert response.headers["Location"] == "/admin"
    assert set(fetch_novels_by_ncode(db_conn)) == {"N0001AA", "N0002BB"}
    # 文言の前後に余計な文字が付いても、同じ結果が 2 行出ても落ちるよう、
    # タグの区切りまで含めて、ちょうど 1 回出ていることを確かめる
    message = ">取り込みました（追加 2 件・更新 0 件・削除 0 件）<"
    assert admin_client.get("/admin").get_data(as_text=True).count(message) == 1
    assert message not in admin_client.get("/admin").get_data(as_text=True)


def test_APIの取得に失敗したら500になりDBは変えない(
    admin_client, db_conn, monkeypatch, caplog
):
    # 30 日前の作品は、取り込みが成功していれば削除されるはずのもの
    insert_novel(db_conn, "N0099ZZ", fetched_at=datetime.now() - timedelta(days=30))

    def failing_fetch():
        raise narou.NarouApiError("テスト用の取得失敗")

    monkeypatch.setattr(narou, "fetch_top_novels", failing_fetch)
    token = page_csrf_token(admin_client, "/admin")

    response = admin_client.post("/admin/import", data={"csrf_token": token})

    assert response.status_code == 500
    assert "テスト用の取得失敗" in caplog.text
    assert set(fetch_novels_by_ncode(db_conn)) == {"N0099ZZ"}
    assert "追加" not in admin_client.get("/admin").get_data(as_text=True)


# --- ログアウト ---


def test_ログアウトするとトップページへ移り_ログインしていない状態に戻る(
    admin_client,
):
    token = page_csrf_token(admin_client, "/admin")

    response = admin_client.post("/admin/logout", data={"csrf_token": token})

    assert response.status_code == 302
    assert response.headers["Location"] == "/"
    assert_logged_out(admin_client)


# --- CSRF ---


@pytest.mark.parametrize(
    "form",
    [
        {},
        {"csrf_token": ""},
        {"csrf_token": "wrong-token"},
        # compare_digest は ASCII 以外の文字列を比べると例外を出すので、500 に
        # ならないことを確かめる
        {"csrf_token": "あいう"},
    ],
)
def test_CSRFトークンが無いか違えば取り込みは400になり実行しない(
    admin_client, fetch_calls, form
):
    # 管理画面を開いて session にトークンを作っておき、「session に無いから 400」
    # ではなく、送ったトークンとの比較で弾かれることを確かめる
    page_csrf_token(admin_client, "/admin")

    response = admin_client.post("/admin/import", data=form)

    assert response.status_code == 400
    assert fetch_calls == []


def test_CSRFトークンが無ければ正しいパスワードでもログインは400になる(client, db_conn):
    add_admin(db_conn, USERNAME, PASSWORD)
    page_csrf_token(client, "/admin/login")

    response = client.post(
        "/admin/login", data={"username": USERNAME, "password": PASSWORD}
    )

    assert response.status_code == 400
    assert_logged_out(client)


def test_sessionにトークンが無いとき_空のトークンを送っても400になる(client, db_conn):
    # ログイン画面を開いていない（session にトークンが無い）状態で、
    # 「無い」と「空」が一致したとみなされないことを確かめる
    add_admin(db_conn, USERNAME, PASSWORD)

    response = client.post(
        "/admin/login",
        data={"csrf_token": "", "username": USERNAME, "password": PASSWORD},
    )

    assert response.status_code == 400
    assert_logged_out(client)
