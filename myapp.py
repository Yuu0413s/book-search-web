import math
from datetime import datetime
from zoneinfo import ZoneInfo

import click
import psycopg2
from flask import Flask, g, render_template, request, url_for
from werkzeug.exceptions import InternalServerError

import db
import genres
import narou

PER_PAGE = 20
# 1 語ごとに SQL の条件が増えるので、語を大量に並べた URL で
# DB を重くされないよう上限を設ける
MAX_KEYWORDS = 10
STORY_EXCERPT_LENGTH = 200

# 並び順の表示名。キーは db.SORT_ORDERS と揃える
SORT_LABELS = {
    "point": "総合ポイント順",
    "fav": "ブックマーク数順",
    "lastup": "最終更新日順",
}
DEFAULT_SORT = "point"

# instance_relative_config=True で、設定ファイルを instance/ から探す
app = Flask(__name__, instance_relative_config=True)
app.config.from_pyfile("config.py")

# 同じ muds.gdl.jp で動くほかの学生の Flask アプリと
# Cookie 名（既定は "session"）がぶつからないようにする
app.config["SESSION_COOKIE_NAME"] = "narou_search_session"


def get_db():
    """いまの処理（リクエスト 1 回、または CLI コマンド 1 回）用の DB 接続を返す。
    無ければ作る。

    起動時に 1 回だけ接続すると、途中で切れたときに再起動するまで全ページが
    エラーになるので、処理ごとに作り、終わったら close_db で閉じる。
    """
    if "db" not in g:
        g.db = psycopg2.connect(app.config["DB_DSN"])
    return g.db


@app.teardown_appcontext
def close_db(exception):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


@app.errorhandler(psycopg2.Error)
def handle_db_error(e):
    # Flask の既定ではトレースバックと例外の文言がエラーログに出るが、文言には
    # 接続先や接続文字列の一部が含まれることがあり、ログはほかの学生も読めるので、
    # 種類名だけを記録する
    app.logger.error("DB の処理に失敗しました（%s）", type(e).__name__)
    return InternalServerError()


@app.template_filter("novel_url")
def novel_url(ncode):
    # API の ncode は大文字（N2710DB）だが、作品ページの URL は小文字
    return f"https://ncode.syosetu.com/{ncode.lower()}/"


@app.template_filter("excerpt")
def excerpt(text):
    if len(text) <= STORY_EXCERPT_LENGTH:
        return text
    return text[:STORY_EXCERPT_LENGTH] + "…"


@app.template_filter("genre_name")
def genre_name(code):
    return genres.GENRE_NAMES.get(code, genres.UNKNOWN_GENRE_NAME)


def parse_search_args(args):
    """URL の検索パラメータを読み取る。おかしな値は初期値に置き換える。"""
    genre = _to_int(args.get("genre"))
    if genre not in genres.GENRE_NAMES:
        genre = None

    sort = args.get("sort", DEFAULT_SORT)
    if sort not in db.SORT_ORDERS:
        sort = DEFAULT_SORT

    page = _to_int(args.get("page"))
    if page is None or page < 1:
        page = 1

    return {
        # NUL 文字は psycopg2 が SQL に渡せずエラーになるので取り除く
        "q": _remove_nul(args.get("q", "")).strip(),
        "writer": _remove_nul(args.get("writer", "")).strip(),
        "genre": genre,
        "sort": sort,
        "page": page,
    }


def _remove_nul(text):
    return text.replace("\x00", "")


def _to_int(text):
    try:
        return int(text)
    except (TypeError, ValueError):
        return None


@app.route("/")
def index():
    search = parse_search_args(request.args)
    # str.split() は全角スペースも区切りとして扱う。同じ語は 1 つにまとめてから数える
    words = list(dict.fromkeys(search["q"].split()))[:MAX_KEYWORDS]
    offset = (search["page"] - 1) * PER_PAGE
    novels, total = db.search_novels(
        get_db(),
        words=words,
        writer=search["writer"] or None,
        genre=search["genre"],
        sort=search["sort"],
        limit=PER_PAGE,
        offset=offset,
    )
    # 0 件でもページ送りの計算が崩れないよう、最低 1 ページとして扱う
    last_page = max(1, math.ceil(total / PER_PAGE))

    def page_url(page):
        # 空の条件と初期値の並び順は URL に入れない（短く、共有しやすくするため）
        args = {
            "q": search["q"] or None,
            "writer": search["writer"] or None,
            "genre": search["genre"],
            "sort": search["sort"] if search["sort"] != DEFAULT_SORT else None,
        }
        args = {key: value for key, value in args.items() if value is not None}
        return url_for("index", **args, page=page)

    return render_template(
        "search.html",
        search=search,
        novels=novels,
        total=total,
        first_number=offset + 1,
        last_page=last_page,
        page_url=page_url,
        genre_groups=genres.GENRE_GROUPS,
        sort_labels=SORT_LABELS,
    )


@app.cli.command("import-novels")
def import_novels_command():
    """なろう API から総合ポイント上位の作品を取り込む。"""
    try:
        novels = narou.fetch_top_novels()
    except narou.NarouApiError as e:
        raise click.ClickException(str(e)) from e

    # なろう API の日時（JST）と揃えるため、サーバのタイムゾーン設定に任せず明示する。
    # カラムはタイムゾーン無しの TIMESTAMP なので、JST の時刻のままタイムゾーン情報だけ
    # 外す（付けたまま渡すと、DB のタイムゾーン設定で変換されて時刻がずれる）
    now = datetime.now(ZoneInfo("Asia/Tokyo")).replace(tzinfo=None)
    try:
        result = db.save_novels(get_db(), novels, now)
    except psycopg2.Error as e:
        # 例外の詳細（str(e)）には接続先や接続文字列の一部が含まれることがあるので、
        # 種類名だけを出す
        raise click.ClickException(
            f"DB への接続または保存に失敗しました（{type(e).__name__}）"
        ) from e

    click.echo(
        f"追加 {result['added']} 件・更新 {result['updated']} 件・"
        f"削除 {result['deleted']} 件"
    )
