from datetime import datetime

import requests

NAROU_API_URL = "https://api.syosetu.com/novelapi/api/"
FETCH_PARAMS = {
    "out": "json",
    "order": "hyoka",
    "lim": 100,
    # DB に保存する 10 項目だけを取得する
    # （転送量を減らすため。API の利用ガイドでも推奨）
    "of": "n-t-w-s-bg-g-k-gp-f-gl",
}
# 指定しないと、API が応答しないときに永久に待ち続ける
TIMEOUT_SECONDS = 30
# general_lastup の形式（例: "2026-03-22 23:00:25"）。形式の自動推測には任せない
LASTUP_FORMAT = "%Y-%m-%d %H:%M:%S"


class NarouApiError(Exception):
    """なろう API から作品を取得できなかったときの例外。"""


def fetch_top_novels():
    """総合ポイント上位の作品を取得し、novels テーブルの行の形にして返す。

    取得できなかった場合や、応答が想定と違う場合は NarouApiError を投げる。
    返す作品の ncode は重複しないことを保証する。
    """
    try:
        response = requests.get(
            NAROU_API_URL, params=FETCH_PARAMS, timeout=TIMEOUT_SECONDS
        )
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as e:
        # 通信エラー・タイムアウト・HTTP エラー・JSON でない応答は、すべてここに来る
        raise NarouApiError(f"なろう API からの取得に失敗しました: {e}") from e

    if not isinstance(data, list):
        raise NarouApiError("なろう API の応答が想定した形式（配列）ではありません")

    # 先頭の要素は {"allcount": 全件数} で、2 番目以降が作品。先頭が欠けていると
    # 1 件目の作品を捨ててしまうので確かめる（allcount は条件に合う作品の総数なので、
    # 返ってくる件数とは一致しない。一致するかは確かめない）
    head = data[0] if data else None
    if not isinstance(head, dict) or not _is_int(head.get("allcount")):
        raise NarouApiError("なろう API の応答の先頭に件数（allcount）がありません")

    raw_novels = data[1:]
    if not raw_novels:
        raise NarouApiError("なろう API から作品が 1 件も返ってきませんでした")

    try:
        novels = [to_novel(raw) for raw in raw_novels]
    except (KeyError, TypeError, ValueError) as e:
        raise NarouApiError(f"なろう API の応答の形式が想定と違います: {e!r}") from e

    ncodes = [novel["ncode"] for novel in novels]
    if len(set(ncodes)) != len(ncodes):
        raise NarouApiError("なろう API の応答に同じ作品（ncode）が重複しています")

    return novels


def to_novel(raw):
    """API の 1 件を、novels テーブルの 1 行（カラム名 → 値）の形にする。"""
    ncode = raw["ncode"]
    # ncode は重複チェックと UNIQUE 制約のキーになるので、
    # 文字列でないものや空文字はここで弾く
    if not isinstance(ncode, str) or not ncode:
        raise ValueError(f"ncode が文字列でないか、空です: {ncode!r}")

    # 型の確かめを DB に任せると、API の異常が DB のエラーとして表示されたり、
    # "123" や 1.5 が黙って変換・丸められて保存されたりするので、ここで確かめる
    return {
        "ncode": ncode,
        "title": _require_str(raw, "title"),
        "writer": _require_str(raw, "writer"),
        "story": _require_str(raw, "story"),
        "biggenre": _require_int(raw, "biggenre"),
        "genre": _require_int(raw, "genre"),
        # タグが無い作品は空文字で返ってくるので、「値なし」として NULL にする
        "keyword": _require_str(raw, "keyword") or None,
        "global_point": _require_int(raw, "global_point"),
        "fav_novel_cnt": _require_int(raw, "fav_novel_cnt"),
        "general_lastup": datetime.strptime(raw["general_lastup"], LASTUP_FORMAT),
    }


def _is_int(value):
    # bool は int の子クラスなので、True / False を整数として通さないよう除く
    return isinstance(value, int) and not isinstance(value, bool)


def _require_str(raw, key):
    value = raw[key]
    if not isinstance(value, str):
        raise ValueError(f"{key} が文字列ではありません: {value!r}")
    return value


def _require_int(raw, key):
    value = raw[key]
    if not _is_int(value):
        raise ValueError(f"{key} が整数ではありません: {value!r}")
    return value
