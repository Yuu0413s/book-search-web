-- コンテナの初回起動時に 1 回だけ実行される。
-- 開発用（narou_search_dev）は POSTGRES_DB で作られるので、テスト用だけを作る。
CREATE DATABASE narou_search_test;
