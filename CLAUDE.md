# なろう小説検索システム（専門デプロイメントⅢ 中間課題）

## 概要
「小説家になろう」API から取得した作品データを PostgreSQL に保存し、キーワード・作者・ジャンルで検索できる Flask アプリ。Gemini の埋め込み（文章 → ベクトル）を使った AI 検索（文章で探す・似ている作品）もある。
設計は `docs/design/narou-search.md` を参照。

## 技術スタック
- ランタイム: Python 3.12
- フレームワーク: Flask 3.1.3（バージョンは授業サーバに合わせて `requirements.txt` で固定）
- DB: PostgreSQL 18（ローカルは Docker、サーバは授業の `s2422016` DB）
- テスト: pytest（バックエンドのみ）
- Lint / 整形: Ruff
- デプロイ先: 授業サーバ muds.gdl.jp（mod_wsgi）→ https://muds.gdl.jp/s2422016/

## ディレクトリ構成
```
mid_assign/                  → サーバの ~/myapp/
├── flask.wsgi               # mod_wsgi の入口
├── myapp.py                 # Flask 本体（ルートと CLI コマンド。DB 接続もここで作る）
├── narou.py                 # なろう API からの取得と変換
├── gemini.py                # Gemini 埋め込み API の呼び出し（文章 → ベクトル）
├── ai_search.py             # AI 検索の計算（文章の組み立て・ハッシュ・類似度・上位の選び出し）
├── embedding.py             # 作品のベクトル化と、ベクトルを使った検索（文章で探す・似ている作品）
├── db.py                    # SQL（接続は呼ぶ側から受け取る）
├── auth.py                  # ログイン必須チェック・CSRF トークン
├── genres.py                # ジャンルのコード → 名前の辞書
├── create_admin.py          # 管理者を作るスクリプト
├── schema.sql               # テーブル定義
├── config.example.py        # instance/config.py の見本
├── instance/config.py       # 秘密情報。Git・sftp とも除外（サーバ上で直接作る）
├── templates/  static/
├── tests/                   # サーバに送らない
├── docs/                    # サーバに送らない
├── compose.yaml             # ローカル用 PostgreSQL（ポート 5433）
└── requirements.txt / requirements-dev.txt
```

## コマンド
| コマンド | 用途 |
|---|---|
| `docker compose up -d` | ローカルの PostgreSQL を起動 |
| `.venv/bin/flask --app myapp run --debug` | 開発サーバー起動 |
| `.venv/bin/pytest` | テスト実行 |
| `.venv/bin/ruff check .` | Lint |
| `.venv/bin/ruff format .` | 整形 |
| `uv pip install -r requirements-dev.txt` | 依存関係のインストール |
| `./deploy.sh` | サーバにデプロイ |
| `.venv/bin/flask --app myapp import-novels` | なろう API から取り込み、続けてベクトル化する（サーバでは `cd ~/myapp && python3 -m flask --app myapp import-novels`） |
| `.venv/bin/flask --app myapp embed-novels` | ベクトルが無い・古い作品だけをベクトル化する（サーバでは `cd ~/myapp && python3 -m flask --app myapp embed-novels`） |
| `.venv/bin/python create_admin.py` | 管理者を作る（サーバでは `cd ~/myapp && python3 create_admin.py`） |

## デプロイ
- `./deploy.sh` で `~/myapp/` に rsync し、`flask.wsgi` を touch して再読み込みする
- mod_wsgi（デーモンモード）は **`flask.wsgi` の更新日時が変わったときだけ** コードと設定を読み直す。`.py` やテンプレートを上げただけでは反映されない
- VSCode で保存したときも `.vscode/sftp.json` の `muds-myapp` 設定で自動アップロードされるが、touch はされない
- `instance/config.py` はアップロードしない。サーバの `~/myapp/instance/config.py`（権限 600）は直接編集する
- エラーログ：`/var/log/httpd/s2422016-error_log`（ほかの学生も読めるので、秘密の値をログに出さない）

## このプロジェクト固有のルール
- Git はローカルのみ。Issue・PR は使わず、main に直接コミットする
- 利用者の入力は必ずプレースホルダで SQL に渡す。SQL 文に埋め込んでよいのは、コード内で決めた固定の文字列（列名・並び順・条件の組み立て）だけ
- URL は `url_for()` で作る（サーバでは先頭に `/s2422016` が付くため）
- POST のフォームには `<input type="hidden" name="csrf_token" value="{{ csrf_token() }}">` を入れる（すべての POST で CSRF トークンを確かめ、無ければ 400 になるため）
- （そのほかは未定。開発しながら追記する）
