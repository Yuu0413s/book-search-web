"""管理者を 1 人作る。

サーバでは `cd ~/myapp && python3 create_admin.py` で実行する。
パスワードは入力しても画面に表示されない getpass で 2 回受け取り、
ハッシュにして保存する。
"""

import getpass
import sys

import psycopg2
from werkzeug.security import generate_password_hash

import db
from myapp import PASSWORD_HASH_METHOD, app, get_db


def main():
    """終了コード（成功は 0、失敗は 1）を返す。"""
    username = input("ユーザー名: ").strip()
    if not username:
        return _fail("ユーザー名を入力してください")
    password = getpass.getpass("パスワード: ")
    if not password:
        return _fail("パスワードを入力してください")
    if getpass.getpass("パスワード（確認）: ") != password:
        return _fail("パスワードが一致しません")

    password_hash = generate_password_hash(password, method=PASSWORD_HASH_METHOD)
    # 事前に SELECT で確かめず、UNIQUE 制約で弾く（確かめてから追加するまでの間に
    # 別の実行が割り込む余地をなくすため）
    with app.app_context():
        try:
            db.create_admin(get_db(), username, password_hash)
        except psycopg2.errors.UniqueViolation:
            return _fail(f"ユーザー名「{username}」の管理者はすでにいます")
        except psycopg2.Error as e:
            # 例外の詳細（str(e)）には接続先や接続文字列の一部が含まれることがあるので、
            # 種類名だけを出す
            return _fail(f"DB への接続または保存に失敗しました（{type(e).__name__}）")

    print(f"管理者「{username}」を作りました")
    return 0


def _fail(message):
    print(message, file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
