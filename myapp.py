from flask import Flask

# instance_relative_config=True で、設定ファイルを instance/ から探す
app = Flask(__name__, instance_relative_config=True)
app.config.from_pyfile("config.py")

# 同じ muds.gdl.jp で動くほかの学生の Flask アプリと
# Cookie 名（既定は "session"）がぶつからないようにする
app.config["SESSION_COOKIE_NAME"] = "narou_search_session"


@app.route("/")
def index():
    return "<p>Hello, World!</p>"
