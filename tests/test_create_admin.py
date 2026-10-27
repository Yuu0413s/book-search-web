import getpass

import pytest
from werkzeug.security import check_password_hash

import create_admin
from tests.helpers import add_admin, fetch_admins_by_username


@pytest.fixture
def type_in(monkeypatch):
    """キーボードからの入力を差し替える。passwords は getpass で順に返す値。"""

    def setup(username, passwords):
        monkeypatch.setattr("builtins.input", lambda prompt="": username)
        remaining = iter(passwords)
        monkeypatch.setattr(getpass, "getpass", lambda prompt="": next(remaining))

    return setup


def test_正しく入力すると管理者が1人でき_パスワードはハッシュで保存される(
    app, db_conn, type_in
):
    type_in("admin", ["correct-horse", "correct-horse"])

    exit_code = create_admin.main()

    assert exit_code == 0
    admins = fetch_admins_by_username(db_conn)
    assert set(admins) == {"admin"}
    password_hash = admins["admin"]["password_hash"]
    assert "correct-horse" not in password_hash
    assert password_hash.startswith("scrypt:")
    assert check_password_hash(password_hash, "correct-horse")


def test_ユーザー名の前後の空白は取り除いて保存する(app, db_conn, type_in):
    type_in("  admin  ", ["correct-horse", "correct-horse"])

    assert create_admin.main() == 0
    assert set(fetch_admins_by_username(db_conn)) == {"admin"}


@pytest.mark.parametrize(
    ("username", "passwords", "message"),
    [
        ("admin", ["correct-horse", "correct-hose"], "パスワードが一致しません"),
        ("admin", ["", ""], "パスワードを入力してください"),
        ("", ["correct-horse", "correct-horse"], "ユーザー名を入力してください"),
        ("   ", ["correct-horse", "correct-horse"], "ユーザー名を入力してください"),
    ],
)
def test_入力に誤りがあれば作らずに失敗で終わる(
    app, db_conn, type_in, capsys, username, passwords, message
):
    type_in(username, passwords)

    exit_code = create_admin.main()

    assert exit_code == 1
    assert message in capsys.readouterr().err
    assert fetch_admins_by_username(db_conn) == {}


def test_同じユーザー名がいれば失敗で終わり_既存のパスワードは変わらない(
    app, db_conn, type_in, capsys
):
    add_admin(db_conn, "admin", "old-password")
    type_in("admin", ["new-password", "new-password"])

    exit_code = create_admin.main()

    assert exit_code == 1
    assert "すでにいます" in capsys.readouterr().err
    admins = fetch_admins_by_username(db_conn)
    assert set(admins) == {"admin"}
    assert check_password_hash(admins["admin"]["password_hash"], "old-password")
