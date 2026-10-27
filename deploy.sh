#!/bin/sh
# 授業サーバ（~/myapp/）にアップロードして、アプリを再読み込みする。
#   使い方: ./deploy.sh
# mod_wsgi は flask.wsgi の更新日時が変わったときだけコードを読み直すので、最後に touch する。
set -eu

cd "$(dirname "$0")"

REMOTE="s2422016@muds.gdl.jp"

# --delete は付けない（サーバにしか無いファイルを誤って消さないため）
rsync -rltvz \
    --exclude ".git/" \
    --exclude ".gitignore" \
    --exclude ".venv/" \
    --exclude ".DS_Store" \
    --exclude "__pycache__/" \
    --exclude ".pytest_cache/" \
    --exclude ".ruff_cache/" \
    --exclude "instance/" \
    --exclude "tests/" \
    --exclude "docs/" \
    --exclude "docker/" \
    --exclude "compose.yaml" \
    --exclude "pyproject.toml" \
    --exclude "requirements-dev.txt" \
    --exclude "CLAUDE.md" \
    --exclude "config.example.py" \
    --exclude "deploy.sh" \
    ./ "$REMOTE:myapp/"

ssh "$REMOTE" 'touch ~/myapp/flask.wsgi'

# 再読み込みの後、トップページが返ってくるか確かめる
sleep 2
status=$(curl -s -o /dev/null -w "%{http_code}" https://muds.gdl.jp/s2422016/)
echo "https://muds.gdl.jp/s2422016/ -> $status"
[ "$status" = "200" ]
