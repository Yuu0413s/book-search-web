import math
import secrets
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import click
import psycopg2
from flask import (
    Flask,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.exceptions import InternalServerError
from werkzeug.security import check_password_hash, generate_password_hash

import auth
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

# パスワードのハッシュの方式。Werkzeug の既定に任せると、更新したときに方式が
# 黙って変わるので明示する（create_admin.py とログインのダミーで共通に使う）
PASSWORD_HASH_METHOD = "scrypt"
LOGIN_ERROR = "ユーザー名またはパスワードが違います"
# ユーザーがいないときの照合に使う、どのパスワードとも一致しないハッシュ
DUMMY_PASSWORD_HASH = generate_password_hash(
    secrets.token_hex(16), method=PASSWORD_HASH_METHOD
)

# instance_relative_config=True で、設定ファイルを instance/ から探す
app = Flask(__name__, instance_relative_config=True)
app.config.from_pyfile("config.py")

# 同じ muds.gdl.jp で動くほかの学生の Flask アプリと
# Cookie 名（既定は "session"）がぶつからないようにする
app.config["SESSION_COOKIE_NAME"] = "narou_search_session"
# ほかのサイトからの POST には Cookie を送らないようにして、CSRF トークンと二重に守る。
# Flask の既定（None）は属性を付けず、ブラウザ任せになるので明示する
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
# ログインはブラウザを閉じるまで有効にする。session.permanent を True にしない限り、
# Flask は有効期限の無い Cookie を返すので、ブラウザを閉じると消える。
# ただし Cookie の値そのものはログアウトしても無効にならず、署名の確認にはこの期限
# （既定 31 日）が使われるので、盗まれたときに使える期間を短くする。最後に session が
# 書き換わってから（ログイン・取り込みなど）この時間がたつと、ログインし直しになる
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=8)

app.add_template_global(auth.get_csrf_token, "csrf_token")


def get_db():
    """いまの処理（リクエスト 1 回、または CLI コマンド 1 回）用の DB 接続を返す。
    無ければ作る。

    起動時に 1 回だけ接続すると、途中で切れたときに再起動するまで全ページが
    エラーになるので、処理ごとに作り、終わったら close_db で閉じる。
    """
    if "db" not in g:
        g.db = psycopg2.connect(app.config["DB_DSN"])
    return g.db


@app.before_request
def redirect_to_https():
    # Secure 付きの Cookie は http では送られずログインできないので、Cookie を
    # Secure にしている環境（サーバ）では、http で来たら https の同じ URL へ移す。
    # 301 だとブラウザに記憶され、設定を戻しても移り続けるので 302 にする
    if app.config["SESSION_COOKIE_SECURE"] and not request.is_secure:
        return redirect(request.url.replace("http://", "https://", 1), code=302)
    return None


# https への切り替えより後に登録し、http の POST はトークンを見る前に切り替える
app.before_request(auth.check_csrf_token)


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
    # abort(500) で例外を投げ直すと、Flask が元の例外ごとトレースバックをログに
    # 出してしまうので、例外を投げずに 500 の応答を返す
    return InternalServerError()


@app.errorhandler(narou.NarouApiError)
def handle_narou_error(e):
    # 文言には、narou.py で書いた説明に加えて、requests の例外の文言（なろう API の
    # URL を含む）や API の応答の値が入る。どれも公開されている値で秘密は入らないので、
    # 原因が分かるようそのまま記録する
    app.logger.error("取り込みに失敗しました（%s）", e)
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
    # str.split() は全角スペースも区切りとして扱う。同じ語は（順番を保ったまま）
    # 1 つにまとめてから数える
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


def run_import():
    """なろう API から取り込み、db.save_novels の結果を返す。

    取り込みコマンドと管理画面の両方から使う。失敗したら例外をそのまま投げる。
    """
    novels = narou.fetch_top_novels()
    # なろう API の日時（JST）と揃えるため、サーバのタイムゾーン設定に任せず明示する。
    # カラムはタイムゾーン無しの TIMESTAMP なので、JST の時刻のままタイムゾーン情報だけ
    # 外す（付けたまま渡すと、DB のタイムゾーン設定で変換されて時刻がずれる）
    now = datetime.now(ZoneInfo("Asia/Tokyo")).replace(tzinfo=None)
    return db.save_novels(get_db(), novels, now)


def format_import_result(result):
    return (
        f"追加 {result['added']} 件・更新 {result['updated']} 件・"
        f"削除 {result['deleted']} 件"
    )


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if "admin_id" in session:
        return redirect(url_for("admin_home"))
    if request.method == "GET":
        return render_template("admin_login.html", username="")

    username = _remove_nul(request.form.get("username", "")).strip()
    password = request.form.get("password", "")
    admin = db.find_admin_by_username(get_db(), username)
    # ユーザーがいないときもダミーのハッシュで照合して、応答にかかる時間の差から
    # ユーザー名の有無を推測されないようにする
    password_hash = admin["password_hash"] if admin else DUMMY_PASSWORD_HASH
    password_matches = check_password_hash(password_hash, password)
    if admin is None or not password_matches:
        return render_template(
            "admin_login.html", username=username, error=LOGIN_ERROR
        ), 401

    # ログイン前の session（攻撃者が用意したものかもしれない）を引き継がないよう、
    # 中身を捨ててから入れる。CSRF トークンもここで作り直される
    session.clear()
    session["admin_id"] = admin["id"]
    return redirect(url_for("admin_home"))


@app.route("/admin")
@auth.login_required
def admin_home():
    return render_template("admin.html", status=db.get_import_status(get_db()))


@app.route("/admin/import", methods=["POST"])
@auth.login_required
def admin_import():
    # 失敗したときは、DB・なろう API のエラーのハンドラが 500 の画面を返す
    result = run_import()
    # 結果を画面に直接返すと、再読み込みで取り込みがもう一度走るので、
    # flash で次の画面に渡して管理画面へ移す（PRG）
    flash(f"取り込みました（{format_import_result(result)}）")
    return redirect(url_for("admin_home"))


@app.route("/admin/logout", methods=["POST"])
@auth.login_required
def admin_logout():
    session.clear()
    return redirect(url_for("index"))


@app.cli.command("import-novels")
def import_novels_command():
    """なろう API から総合ポイント上位の作品を取り込む。"""
    try:
        result = run_import()
    except narou.NarouApiError as e:
        raise click.ClickException(str(e)) from e
    except psycopg2.Error as e:
        # 例外の詳細（str(e)）には接続先や接続文字列の一部が含まれることがあるので、
        # 種類名だけを出す
        raise click.ClickException(
            f"DB への接続または保存に失敗しました（{type(e).__name__}）"
        ) from e

    click.echo(format_import_result(result))
