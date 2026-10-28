"""作品のベクトル化（DB の作品を Gemini でベクトルにして保存する）と、
保存したベクトルを使った検索（文章で探す・似ている作品）。

db.py と同じく、DB の接続は呼ぶ側から受け取り、Flask に依存させない
（管理画面・2 つのコマンド・テストから同じように呼ぶため）。
"""

import ai_search
import db
import gemini


def embed_novels(conn, api_key, now):
    """ベクトルが無い・古い作品だけをベクトル化して保存し、結果を返す。

    返す値は {"embedded": 保存した件数, "failed": 送れなかった件数,
    "error": 起きた GeminiApiError か None}。
    Gemini で失敗したら（回数制限も含む）そこで止め、残りを失敗として数える。
    失敗の多くはキーの間違いや通信の問題で、続けて送っても同じように失敗し、
    無料枠を無駄に使うため。
    変換している間に消えた作品は db.save_embeddings が飛ばすので、どちらにも数えない。
    now は保存時刻で、タイムゾーン無しの JST。
    """
    targets = ai_search.select_novels_to_embed(
        db.fetch_embedding_targets(conn), gemini.EMBEDDING_ID
    )
    embedded_count = 0
    for start in range(0, len(targets), gemini.MAX_BATCH_SIZE):
        batch = targets[start : start + gemini.MAX_BATCH_SIZE]
        texts = [ai_search.document_text(target) for target in batch]
        try:
            vectors = gemini.embed_texts(texts, api_key)
        except gemini.GeminiApiError as e:
            return {
                "embedded": embedded_count,
                "failed": len(targets) - start,
                "error": e,
            }
        # 送るたびに保存し、途中で回数制限になっても、それまでの分を残す
        embedded_count += db.save_embeddings(
            conn,
            [
                {
                    "novel_id": target["id"],
                    "embedding": vector,
                    "model": gemini.EMBEDDING_ID,
                    "source_hash": ai_search.source_hash(text),
                }
                for target, text, vector in zip(batch, texts, vectors, strict=True)
            ],
            now,
        )
    return {"embedded": embedded_count, "failed": 0, "error": None}


def get_embedding_status(conn):
    """作品数と、今のモデルと内容でベクトルがある件数を返す。

    「変換が必要か」の判定は ai_search.select_novels_to_embed の 1 か所に任せる。
    """
    targets = db.fetch_embedding_targets(conn)
    needed = ai_search.select_novels_to_embed(targets, gemini.EMBEDDING_ID)
    return {
        "novel_count": len(targets),
        "embedded_count": len(targets) - len(needed),
    }


def search_by_text(conn, text, api_key, limit):
    """text に意味が近い作品を近い順に limit 件、(作品の dict, 類似度) のリストで返す。

    比べるベクトルが 1 件も無ければ None を返す（結果が 0 件の [] とは分ける）。
    そのときは、無料枠を使わないよう Gemini を呼ばない。
    Gemini で失敗したら GeminiApiError をそのまま投げる。
    """
    candidates = db.fetch_embeddings(conn, gemini.EMBEDDING_ID)
    if not candidates:
        return None
    query_vector = gemini.embed_text(ai_search.query_text(text), api_key)
    ranked = ai_search.rank_by_similarity(query_vector, candidates, limit)
    return _with_novels(conn, ranked)


def find_similar_novels(conn, novel_id, limit):
    """作品 novel_id にベクトルが近いほかの作品を、search_by_text と同じ形で返す。

    元の作品に今のモデルのベクトルが無ければ None を返す。API は呼ばない。
    """
    candidates = db.fetch_embeddings(conn, gemini.EMBEDDING_ID)
    source_vectors = [vector for id_, vector in candidates if id_ == novel_id]
    if not source_vectors:
        return None
    others = [(id_, vector) for id_, vector in candidates if id_ != novel_id]
    ranked = ai_search.rank_by_similarity(source_vectors[0], others, limit)
    return _with_novels(conn, ranked)


def _with_novels(conn, ranked):
    """(作品の id, 類似度) のリストを、順番を保って (作品の dict, 類似度) にする。"""
    novels = db.fetch_novels_by_ids(conn, [novel_id for novel_id, _ in ranked])
    # ベクトルを読んでから作品を読むまでの間に、取り込みで消えた作品は飛ばす
    return [
        (novels[novel_id], score) for novel_id, score in ranked if novel_id in novels
    ]
