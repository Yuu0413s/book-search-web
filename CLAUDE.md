# なろう小説検索システム（専門デプロイメントⅢ 中間課題）

## 概要
「小説家になろう」API から取得した作品データを PostgreSQL に保存し、キーワード・作者・ジャンルで検索できる Flask アプリ。
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
├── myapp.py                 # Flask 本体（ルート）
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

## デプロイ
- `.vscode/sftp.json` の `muds-myapp` 設定で、保存時に `~/myapp/` へ自動アップロードされる
- `instance/config.py` はアップロードしない。サーバの `~/myapp/instance/config.py` は直接編集する

## このプロジェクト固有のルール
- Git はローカルのみ。Issue・PR は使わず、main に直接コミットする
- SQL はすべてプレースホルダで書く（文字列の埋め込みをしない）
- URL は `url_for()` で作る（サーバでは先頭に `/s2422016` が付くため）
- （そのほかは未定。開発しながら追記する）
