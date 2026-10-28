# なろう小説検索

「小説家になろう」の人気作品を、キーワード・作者・ジャンルで探せる Web アプリです。
読みたい話を文章で書くと意味の近い作品が見つかる **AI 検索** と、ある作品に内容が近い作品を一覧で見られる **似ている作品** の機能もあります。

**公開中:** https://muds.gdl.jp/s2422016/

専門デプロイメントⅢの中間課題として作り、授業サーバ（mod_wsgi）で公開しています。

## 主な機能

| 機能 | 内容 |
|---|---|
| キーワード検索 | タイトル・あらすじ・タグに部分一致。空白で区切ると AND 検索 |
| 絞り込み・並べ替え | 作者名・ジャンルで絞り込み、総合ポイント順・ブックマーク数順・最終更新日順に並べ替え。20 件ずつページ送り |
| AI 検索 | 「追放された主人公が辺境でのんびり暮らす話」のような文章で探す。意味の近い順に 20 件を類似度つきで表示 |
| 似ている作品 | 作品ごとに、内容の近いほかの作品を 20 件表示 |
| 管理画面 | ログインした管理者だけが、なろう API からの取り込みとベクトル化を実行できる |

## しくみ

```
なろう API ──(取り込み)──▶ PostgreSQL ◀──(検索)── 閲覧者
                              ▲
Gemini 埋め込み API ──(作品をベクトルに)──┘
```

- **検索のたびになろう API を呼ばない。** 総合ポイント上位 100 件を管理画面（またはコマンド）で DB に取り込み、検索は自分の DB だけで行います。上位から外れて最後の取り込みから 14 日を過ぎた作品は、取り込みのときに消します（なろう API の利用ガイドライン「保存したデータは 2 週間以内に更新か削除」に合わせるため）
- **AI 検索は埋め込み（文章 → ベクトル）で行う。** 取り込んだ作品のタイトル・あらすじ・タグを Gemini の埋め込み API（`gemini-embedding-2`、768 次元）でベクトルにして保存します。検索のときは入力した文章もベクトルにし、コサイン類似度の高い順に並べます
- **類似度の計算は Python だけで行う。** 授業サーバには pgvector も numpy も入っていないため、ベクトルは PostgreSQL の `REAL[]` に保存し、比較は標準ライブラリだけで行います（作品は 100 件ほどなので、全件と比べても十分に速いです）
- **似ている作品では API を呼ばない。** 保存済みのベクトル同士を比べるだけなので、無料枠を使いません

## 技術スタック

| 分類 | 使っているもの |
|---|---|
| 言語 | Python 3.12 |
| フレームワーク | Flask 3.1（Jinja2 テンプレート） |
| DB | PostgreSQL 18（psycopg2） |
| 外部 API | 小説家になろう API、Gemini API（埋め込み） |
| テスト・Lint | pytest、Ruff |
| 公開 | Apache + mod_wsgi（授業サーバ） |

ライブラリのバージョンは、授業サーバにインストール済みのものに合わせて `requirements.txt` で固定しています。

## セキュリティで気をつけたこと

- 利用者の入力はすべてプレースホルダで SQL に渡す
- 管理者のパスワードはソルトつきのハッシュ（scrypt）で保存し、登録画面は作らない（`create_admin.py` で作る）
- すべての POST で CSRF トークンを確かめ、Cookie には SameSite=Lax を付ける。サーバではサイト全体を https に切り替える
- ログには秘密の値（API キー、DB の接続情報）を出さない。授業サーバのエラーログはほかの学生も読めるため

## ローカルで動かす

必要なもの: Python 3.12、Docker、[uv](https://docs.astral.sh/uv/)

```sh
# 1. DB を起動する（ポート 5433。初回は開発用とテスト用の DB が作られる）
docker compose up -d

# 2. 仮想環境を作って依存関係を入れる
uv venv --python 3.12
uv pip install -r requirements-dev.txt

# 3. 開発用 DB にテーブルを作る
docker compose exec -T db psql -U narou -d narou_search_dev < schema.sql

# 4. 設定ファイルを作り、値を埋める（DB_DSN の例は中に書いてある）
mkdir -p instance
cp config.example.py instance/config.py

# 5. 管理者を作り、作品を取り込む（GEMINI_API_KEY があれば続けてベクトル化もする）
.venv/bin/python create_admin.py
.venv/bin/flask --app myapp import-novels

# 6. 開発サーバーを起動する → http://127.0.0.1:5000/
.venv/bin/flask --app myapp run --debug
```

`instance/config.py` には秘密の値が入るので、Git には入れません（`.gitignore` 済み）。
AI 検索を使うには、[Google AI Studio](https://aistudio.google.com/) で発行した API キーを `GEMINI_API_KEY` に設定します。無料枠では、送った文章が Google のサービス改善に使われます。

### よく使うコマンド

| コマンド | 用途 |
|---|---|
| `.venv/bin/pytest` | テストを実行する（テスト用 DB のテーブルは自動で作り直す。Gemini への通信は常に止めている） |
| `.venv/bin/ruff check .` / `.venv/bin/ruff format .` | Lint / 整形 |
| `.venv/bin/flask --app myapp import-novels` | なろう API から取り込み、続けてベクトル化する |
| `.venv/bin/flask --app myapp embed-novels` | ベクトルが無い・古い作品だけをベクトル化する |
| `./deploy.sh` | 授業サーバにアップロードして再読み込みする |

## フォルダ構成

```
mid_assign/
├── myapp.py            # Flask 本体（ルートと CLI コマンド）
├── narou.py            # なろう API からの取得と変換
├── gemini.py           # Gemini 埋め込み API の呼び出し
├── ai_search.py        # ベクトル化する文章の組み立て・類似度の計算（API も DB も使わない）
├── embedding.py        # 作品のベクトル化と、ベクトルを使った検索
├── db.py               # SQL
├── auth.py             # ログイン必須チェック・CSRF トークン
├── genres.py           # ジャンルのコードと名前
├── create_admin.py     # 管理者を作るスクリプト
├── schema.sql          # テーブル定義
├── flask.wsgi          # mod_wsgi の入口
├── templates/  static/
├── tests/              # pytest
└── docs/design/        # 設計メモ
```

設計の詳しい判断（なぜこうしたか）は [docs/design/narou-search.md](docs/design/narou-search.md) にまとめています。

## データの出典

作品データは [小説家になろう API](https://dev.syosetu.com/man/api/) から取得しています。「小説家になろう」は株式会社ヒナプロジェクトの登録商標です。このアプリは非公式のもので、株式会社ヒナプロジェクトとは関係ありません。
