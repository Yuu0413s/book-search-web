"""Gemini の埋め込み API で、文章をベクトル（数の並び）に変換する。

google-genai はサーバに無いので、requests で直接呼ぶ。
"""

import math

import requests

MODEL = "gemini-embedding-2"
# 3072 次元が既定だが、DB の容量と類似度の計算時間を抑えるため 768 次元にする
DIMENSIONS = 768
# batchEmbedContents に 1 回で送れる件数の上限
MAX_BATCH_SIZE = 100
API_BASE_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}"
EMBED_URL = f"{API_BASE_URL}:embedContent"
BATCH_EMBED_URL = f"{API_BASE_URL}:batchEmbedContents"
# 検索のたびに呼ぶ 1 件は、利用者を待たせすぎないよう短くする
EMBED_TIMEOUT_SECONDS = 10
BATCH_EMBED_TIMEOUT_SECONDS = 30
DIMENSION_CONFIG = {"outputDimensionality": DIMENSIONS}


class GeminiApiError(Exception):
    """Gemini API で変換できなかったときの例外。"""


class GeminiQuotaError(GeminiApiError):
    """Gemini API の回数制限（429）に達したときの例外。"""


def embed_text(text, api_key):
    """文章 1 件をベクトルにして返す。

    変換できなかった場合や、応答が想定と違う場合は GeminiApiError を投げる
    （回数制限なら、その一種の GeminiQuotaError）。
    """
    data = _post(
        EMBED_URL,
        {"content": _content(text), "embedContentConfig": DIMENSION_CONFIG},
        api_key,
        EMBED_TIMEOUT_SECONDS,
    )
    if not isinstance(data, dict):
        raise GeminiApiError("Gemini API の応答が想定した形式（辞書）ではありません")
    return _require_vector(data.get("embedding"))


def embed_texts(texts, api_key):
    """文章をまとめてベクトルにし、texts と同じ順番で返す。

    texts は 1〜MAX_BATCH_SIZE 件。それ以外は API を呼ばずに ValueError を投げる。
    失敗したときの例外は embed_text と同じ。
    """
    if not 1 <= len(texts) <= MAX_BATCH_SIZE:
        raise ValueError(
            f"文章は 1〜{MAX_BATCH_SIZE} 件にしてください（{len(texts)} 件）"
        )

    data = _post(
        BATCH_EMBED_URL,
        {
            "requests": [
                {
                    "model": f"models/{MODEL}",
                    "content": _content(text),
                    "embedContentConfig": DIMENSION_CONFIG,
                }
                for text in texts
            ]
        },
        api_key,
        BATCH_EMBED_TIMEOUT_SECONDS,
    )
    embeddings = data.get("embeddings") if isinstance(data, dict) else None
    if not isinstance(embeddings, list):
        raise GeminiApiError("Gemini API の応答にベクトルの一覧がありません")
    # 件数がずれていると、どの作品のベクトルか対応が取れなくなる
    if len(embeddings) != len(texts):
        raise GeminiApiError(
            f"Gemini API から返ったベクトルの数が違います"
            f"（送った {len(texts)} 件 / 返った {len(embeddings)} 件）"
        )
    return [_require_vector(embedding) for embedding in embeddings]


def _content(text):
    return {"parts": [{"text": text}]}


def _post(url, body, api_key, timeout):
    try:
        # キーは URL ではなくヘッダーで渡す。requests の例外の文言には URL が
        # そのまま入り、ほかの学生も読めるエラーログに出てしまうため
        response = requests.post(
            url, headers={"x-goog-api-key": api_key}, json=body, timeout=timeout
        )
        # 回数制限は、時間を置けば直る。呼ぶ側が残りの変換を止められるよう分ける
        if response.status_code == 429:
            raise GeminiQuotaError("Gemini API の回数制限に達しました")
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        # 通信エラー・タイムアウト・HTTP エラー・JSON でない応答は、すべてここに来る
        raise GeminiApiError(f"Gemini API の呼び出しに失敗しました: {e}") from e


def _require_vector(embedding):
    """応答の 1 件から、DIMENSIONS 個の有限の数の並びを取り出す。"""
    values = embedding.get("values") if isinstance(embedding, dict) else None
    if not isinstance(values, list) or len(values) != DIMENSIONS:
        raise GeminiApiError(
            f"Gemini API の応答のベクトルが {DIMENSIONS} 個の数の並びではありません"
        )
    # 文字列や NaN が混ざったまま保存すると、類似度の計算で失敗するか、
    # 黙っておかしな順位になるので、ここで弾く
    if not all(_is_finite_number(value) for value in values):
        raise GeminiApiError("Gemini API の応答のベクトルに数でない値があります")
    return values


def _is_finite_number(value):
    # bool は int の子クラスなので、True / False を数として通さないよう除く
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return math.isfinite(value)
