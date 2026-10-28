# instance/config.py の見本。コピーして値を埋める。
# instance/config.py は Git にも sftp にも入れない（ローカルとサーバで中身が違うため）。

# session の署名に使う鍵。ランダムな長い文字列にする
#   python3 -c "import secrets; print(secrets.token_hex(32))"
SECRET_KEY = ""

# psycopg2.connect() に渡す接続文字列
#   ローカル:
#   "host=localhost port=5433 dbname=narou_search_dev user=narou password=narou"
DB_DSN = ""

# ログイン情報の Cookie を送る範囲。サーバでは "/s2422016/"、ローカルでは "/"
# （同じ muds.gdl.jp で動くほかの学生のアプリと Cookie がぶつからないようにするため）
SESSION_COOKIE_PATH = "/"

# https のときだけ Cookie を送る。サーバでは True、ローカル（http）では False
# True にすると、http で来たアクセスをサイト全体で https へ切り替える
# （Secure 付きの Cookie は http では送られず、ログインできないため。
# myapp.redirect_to_https）
SESSION_COOKIE_SECURE = False

# Gemini の埋め込み API のキー（AI 検索で使う）。Google AI Studio で発行する
# 無料枠では、送った文章が Google のサービス改善に使われる
GEMINI_API_KEY = ""
