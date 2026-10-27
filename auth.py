"""管理画面のログイン必須チェックと CSRF 対策。

Flask-Login・Flask-WTF はサーバに無いので、Flask の session で自前で行う。
"""

import functools
import secrets

from flask import abort, redirect, request, session, url_for


def login_required(view):
    """ログインしていなければ、ログイン画面へ移すデコレータ。"""

    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        # session は SECRET_KEY で署名されていて書き換えられないので、
        # admin_id が入っていればログイン済みとみなす（毎回 DB では確かめない）
        if "admin_id" not in session:
            return redirect(url_for("admin_login"))
        return view(*args, **kwargs)

    return wrapped


def get_csrf_token():
    """フォームに埋め込む CSRF トークン。session に無ければ作って保存する。"""
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_hex(32)
    return session["csrf_token"]


def check_csrf_token():
    """POST のとき、フォームのトークンが session のものと一致しなければ 400 にする。

    app.before_request に登録して、すべての POST に対して行う。
    """
    if request.method != "POST":
        return
    expected = session.get("csrf_token")
    sent = request.form.get("csrf_token", "")
    # session に無いとき、空のトークンと一致したとみなさないよう先に弾く
    if expected is None:
        abort(400)
    # compare_digest は比べる時間から中身を推測されないための比較。ASCII 以外を
    # 含む文字列は比べられず例外になるので、バイト列にして比べる
    if not secrets.compare_digest(expected.encode(), sent.encode()):
        abort(400)
