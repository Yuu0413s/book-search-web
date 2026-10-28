"""AI 検索の計算（ベクトル化する文章の組み立て・ハッシュ・類似度・上位の選び出し）。

API も DB も使わない。numpy はサーバに無いので、Python だけで計算する。
"""

import hashlib
import math


def document_text(novel):
    """作品をベクトル化するときの文章。

    gemini-embedding-2 は用途を引数で指定できず、文章の先頭の書き方で伝える
    （書き方は docs/design/narou-search.md の「11.7」、理由は「11.11」）。
    """
    # タイトルが空のときは、Gemini の説明に合わせて none と書く
    title = novel["title"] or "none"
    text = f"title: {title} | text: {novel['story']}"
    if novel["keyword"]:
        text += f"\n{novel['keyword']}"
    return text


def query_text(text):
    """検索の文章をベクトル化するときの文章。"""
    return f"task: search result | query: {text}"


def source_hash(text):
    """ベクトル化した文章の SHA-256（16 進数）。作品の内容が変わったかを見分ける。"""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def select_novels_to_embed(targets, model):
    """ベクトル化が必要な作品だけを、元の順番のまま返す。

    targets は db.fetch_embedding_targets の戻り値。model は gemini.EMBEDDING_ID。
    ベクトルが無い作品、別のモデル・次元数で変換した作品、変換した後に内容が
    変わった作品が対象になる。
    """
    return [
        target
        for target in targets
        if target["embedding_model"] != model
        or target["embedding_hash"] != source_hash(document_text(target))
    ]


def cosine_similarity(a, b):
    """2 つのベクトルのコサイン類似度（-1〜1。向きが近いほど大きい）。

    長さが違うか、どちらかが長さ 0 のベクトルなら ValueError を投げる。
    """
    if len(a) != len(b):
        raise ValueError(f"ベクトルの長さが違います（{len(a)} と {len(b)}）")
    # API の値は長さ 1 で返るが、DB の REAL で丸められるので、
    # 内積だけで済ませず長さで割る
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        raise ValueError("長さ 0 のベクトルは向きが無く、類似度を決められません")
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    return dot / (norm_a * norm_b)


def rank_by_similarity(query_vector, candidates, limit):
    """query_vector に近い順に、上位 limit 件の (作品の id, 類似度) を返す。

    candidates は (作品の id, ベクトル) のリスト（db.fetch_embeddings の戻り値）。
    類似度が同じなら id の小さい順にして、結果の順番が毎回変わらないようにする。
    """
    scored = [
        (novel_id, cosine_similarity(query_vector, vector))
        for novel_id, vector in candidates
    ]
    scored.sort(key=lambda item: (-item[1], item[0]))
    return scored[:limit]
