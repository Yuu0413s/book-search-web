from datetime import datetime
from zoneinfo import ZoneInfo

import click
import psycopg2
from flask import Flask

import db
import narou

# instance_relative_config=True で、設定ファイルを instance/ から探す
app = Flask(__name__, instance_relative_config=True)
app.config.from_pyfile("config.py")

# 同じ muds.gdl.jp で動くほかの学生の Flask アプリと
# Cookie 名（既定は "session"）がぶつからないようにする
app.config["SESSION_COOKIE_NAME"] = "narou_search_session"


@app.route("/")
def index():
    return "<p>Hello, World!</p>"


@app.cli.command("import-novels")
def import_novels_command():
    """なろう API から総合ポイント上位の作品を取り込む。"""
    try:
        novels = narou.fetch_top_novels()
    except narou.NarouApiError as e:
        raise click.ClickException(str(e)) from e

    # なろう API の日時（JST）と揃えるため、サーバのタイムゾーン設定に任せず明示する
    now = datetime.now(ZoneInfo("Asia/Tokyo")).replace(tzinfo=None)
    try:
        conn = psycopg2.connect(app.config["DB_DSN"])
        try:
            result = db.save_novels(conn, novels, now)
        finally:
            conn.close()
    except psycopg2.Error as e:
        raise click.ClickException(f"DB への接続または保存に失敗しました: {e}") from e

    click.echo(
        f"追加 {result['added']} 件・更新 {result['updated']} 件・"
        f"削除 {result['deleted']} 件"
    )
