-- テーブル定義（docs/design/narou-search.md の「6. データ構造」）
-- カラム名はなろう API の項目名をそのまま使う。

CREATE TABLE novels (
    id             SERIAL    PRIMARY KEY,
    ncode          TEXT      NOT NULL UNIQUE,
    title          TEXT      NOT NULL,
    writer         TEXT      NOT NULL,
    story          TEXT      NOT NULL,
    biggenre       INTEGER   NOT NULL,
    genre          INTEGER   NOT NULL,
    keyword        TEXT,
    global_point   INTEGER   NOT NULL,
    fav_novel_cnt  INTEGER   NOT NULL,
    general_lastup TIMESTAMP NOT NULL,
    -- 最後に API から取得した日時。14 日を過ぎた作品の削除に使う
    fetched_at     TIMESTAMP NOT NULL,
    created_at     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE admins (
    id            SERIAL    PRIMARY KEY,
    username      TEXT      NOT NULL UNIQUE,
    password_hash TEXT      NOT NULL,
    created_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- AI 検索用の作品のベクトル（docs/design/narou-search.md の「11.6 データ構造」）。
-- 作品が消えたら一緒に消す
CREATE TABLE novel_embeddings (
    novel_id    INTEGER   PRIMARY KEY REFERENCES novels (id) ON DELETE CASCADE,
    embedding   REAL[]    NOT NULL,
    -- 変換に使ったモデル名。モデルを変えたときに、作り直す対象を見分ける
    model       TEXT      NOT NULL,
    -- 変換した文章のハッシュ。作品の内容が変わったかを見分ける
    source_hash TEXT      NOT NULL,
    -- 上書きのときは DB の既定値が効かないので、呼ぶ側から渡す
    updated_at  TIMESTAMP NOT NULL
);
