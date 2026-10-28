"""作品のベクトル化（DB の作品を Gemini でベクトルにして保存する）。

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
