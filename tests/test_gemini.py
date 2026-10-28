import math

import pytest
import requests

import gemini
from tests.helpers import EMBEDDING_ID, FakeResponse

API_KEY = "test-api-key-1234"
EMBED_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "gemini-embedding-2:embedContent"
)
BATCH_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "gemini-embedding-2:batchEmbedContents"
)
DIMENSION_CONFIG = {"outputDimensionality": 768}


def make_values(first=0.5):
    """768 個の数（先頭だけ first にして、どのベクトルか見分けられるようにする）。"""
    return [first] + [0.01] * 767


def fake_post_returning(response, calls=None):
    """呼ばれたら response を返す偽の requests.post を作る。

    呼び出し内容は calls に記録する。
    """

    def fake_post(url, **kwargs):
        if calls is not None:
            calls.append({"url": url, **kwargs})
        return response

    return fake_post


def fake_post_raising(error_class):
    """呼ばれたら、URL を含む文言で error_class を投げる偽の requests.post を作る。

    requests の例外の文言には URL が入るので、本物と同じ形にする。
    """

    def fake_post(url, **kwargs):
        raise error_class(f"failed: {url}")

    return fake_post


def single_response(values):
    return FakeResponse({"embedding": {"values": values}})


def batch_response(values_list):
    return FakeResponse({"embeddings": [{"values": v} for v in values_list]})


# --- embed_text（1 件） ---


def test_embed_text_決まったURL_ヘッダーのキー_768次元の指定_10秒で呼ぶ(
    monkeypatch,
):
    calls = []
    monkeypatch.setattr(
        gemini.requests,
        "post",
        fake_post_returning(single_response(make_values()), calls),
    )

    gemini.embed_text("検索の文章", API_KEY)

    assert len(calls) == 1
    call = calls[0]
    assert call["url"] == EMBED_URL
    assert call["headers"]["x-goog-api-key"] == API_KEY
    assert call["json"] == {
        "content": {"parts": [{"text": "検索の文章"}]},
        "embedContentConfig": DIMENSION_CONFIG,
    }
    assert call["timeout"] == 10
    # キーは URL に入れない（requests の例外の文言に URL が入り、ログに出るため）
    assert API_KEY not in call["url"]
    assert "params" not in call
    # 転送には従わない（requests は転送先にもキーのヘッダーを送るため）
    assert call["allow_redirects"] is False


def test_embed_text_応答のベクトルを返す(monkeypatch):
    values = make_values(0.7)
    monkeypatch.setattr(
        gemini.requests, "post", fake_post_returning(single_response(values))
    )

    assert gemini.embed_text("検索の文章", API_KEY) == values


# --- embed_texts（まとめて） ---


def test_embed_texts_送った順に_各項目にモデルと768次元を付けて_30秒で呼ぶ(
    monkeypatch,
):
    calls = []
    response = batch_response([make_values(0.1), make_values(0.2)])
    monkeypatch.setattr(gemini.requests, "post", fake_post_returning(response, calls))

    gemini.embed_texts(["一つ目", "二つ目"], API_KEY)

    assert len(calls) == 1
    call = calls[0]
    assert call["url"] == BATCH_URL
    assert call["headers"]["x-goog-api-key"] == API_KEY
    assert call["json"] == {
        "requests": [
            {
                "model": "models/gemini-embedding-2",
                "content": {"parts": [{"text": "一つ目"}]},
                "embedContentConfig": DIMENSION_CONFIG,
            },
            {
                "model": "models/gemini-embedding-2",
                "content": {"parts": [{"text": "二つ目"}]},
                "embedContentConfig": DIMENSION_CONFIG,
            },
        ]
    }
    assert call["timeout"] == 30
    assert API_KEY not in call["url"]
    assert call["allow_redirects"] is False


def test_embed_texts_応答のベクトルを順番どおりに返す(monkeypatch):
    values_list = [make_values(0.1), make_values(0.2), make_values(0.3)]
    monkeypatch.setattr(
        gemini.requests, "post", fake_post_returning(batch_response(values_list))
    )

    assert gemini.embed_texts(["a", "b", "c"], API_KEY) == values_list


def test_embed_texts_100件までは1回で送れる(monkeypatch):
    calls = []
    response = batch_response([make_values()] * 100)
    monkeypatch.setattr(gemini.requests, "post", fake_post_returning(response, calls))

    assert len(gemini.embed_texts(["文章"] * 100, API_KEY)) == 100
    assert len(calls) == 1


@pytest.mark.parametrize("count", [0, 101])
def test_embed_texts_0件や101件以上ならAPIを呼ばずにValueError(monkeypatch, count):
    calls = []
    monkeypatch.setattr(
        gemini.requests, "post", fake_post_returning(batch_response([]), calls)
    )

    with pytest.raises(ValueError):
        gemini.embed_texts(["文章"] * count, API_KEY)
    assert calls == []


# --- 失敗 ---

# 1 件・まとめての両方で、失敗の扱いが同じことを確かめる
CALLERS = [
    pytest.param(lambda: gemini.embed_text("文章", API_KEY), id="embed_text"),
    pytest.param(lambda: gemini.embed_texts(["文章"], API_KEY), id="embed_texts"),
]


@pytest.mark.parametrize("call", CALLERS)
def test_429ならGeminiQuotaError(monkeypatch, call):
    monkeypatch.setattr(
        gemini.requests, "post", fake_post_returning(FakeResponse(status_code=429))
    )

    with pytest.raises(gemini.GeminiQuotaError):
        call()


def test_GeminiQuotaErrorはGeminiApiErrorの一種():
    # 回数制限だけを見分けたいとき以外は、まとめて GeminiApiError で受けられる
    assert issubclass(gemini.GeminiQuotaError, gemini.GeminiApiError)


@pytest.mark.parametrize("call", CALLERS)
@pytest.mark.parametrize(
    "fake_post",
    [
        pytest.param(fake_post_raising(requests.ConnectionError), id="通信エラー"),
        pytest.param(fake_post_raising(requests.Timeout), id="タイムアウト"),
        pytest.param(fake_post_returning(FakeResponse(status_code=500)), id="500"),
        pytest.param(fake_post_returning(FakeResponse(status_code=403)), id="403"),
        # 本文が正しい形でも、転送なら失敗にすることを確かめる
        pytest.param(
            fake_post_returning(
                FakeResponse(
                    {
                        "embedding": {"values": make_values()},
                        "embeddings": [{"values": make_values()}],
                    },
                    status_code=302,
                )
            ),
            id="302転送",
        ),
        pytest.param(
            fake_post_returning(FakeResponse(invalid_json=True)), id="JSONでない"
        ),
    ],
)
def test_通信やHTTPの失敗はGeminiApiErrorで_回数制限とは区別する(
    monkeypatch, call, fake_post
):
    monkeypatch.setattr(gemini.requests, "post", fake_post)

    with pytest.raises(gemini.GeminiApiError) as excinfo:
        call()
    assert not isinstance(excinfo.value, gemini.GeminiQuotaError)


@pytest.mark.parametrize("call", CALLERS)
def test_例外の文言にAPIキーが含まれない(monkeypatch, call):
    # requests の例外の文言には、呼んだ URL がそのまま入る
    monkeypatch.setattr(
        gemini.requests, "post", fake_post_raising(requests.ConnectionError)
    )

    with pytest.raises(gemini.GeminiApiError) as excinfo:
        call()
    assert "generativelanguage.googleapis.com" in str(excinfo.value)
    assert API_KEY not in str(excinfo.value)


@pytest.mark.parametrize(
    "api_key",
    [
        pytest.param(f" {API_KEY}", id="先頭に空白"),
        pytest.param(f"{API_KEY} ", id="末尾に空白"),
        pytest.param(f"{API_KEY}\n", id="末尾に改行"),
        pytest.param(f"{API_KEY}\r\n", id="末尾にCRLF"),
        pytest.param("test-api\rkey-1234", id="途中にCR"),
        pytest.param(f"{API_KEY}　", id="全角空白"),
        pytest.param("", id="空"),
        pytest.param(None, id="None"),
    ],
)
@pytest.mark.parametrize(
    "call_with_key",
    [
        pytest.param(lambda key: gemini.embed_text("文章", key), id="embed_text"),
        pytest.param(lambda key: gemini.embed_texts(["文章"], key), id="embed_texts"),
    ],
)
def test_キーの形が正しくなければ_APIを呼ばずにGeminiApiErrorで_文言にキーが入らない(
    monkeypatch, api_key, call_with_key
):
    # 先頭の空白や改行は requests の例外の文言にキーの値が入り、末尾の改行や全角文字は
    # GeminiApiError 以外の例外になる。どれも送る前に弾くことを確かめる
    calls = []
    monkeypatch.setattr(
        gemini.requests,
        "post",
        fake_post_returning(single_response(make_values()), calls),
    )

    with pytest.raises(gemini.GeminiApiError) as excinfo:
        call_with_key(api_key)
    assert calls == []
    assert API_KEY not in str(excinfo.value)
    # 「途中にCR」はキーが API_KEY と一致せず、上の確認では必ず通ってしまうので、
    # キーの一部が入っていないことも確かめる
    assert "test-api" not in str(excinfo.value)


def test_保存するモデルの名前には次元数も含める():
    # 次元数だけを変えたときも、古いベクトルを作り直す対象として見分けるため
    # 期待値は helpers の EMBEDDING_ID（"gemini-embedding-2:768"）。ほかのテストも
    # この値を使うので、1 か所にまとめ、実装とずれたらここで落ちるようにする
    assert gemini.EMBEDDING_ID == EMBEDDING_ID


# --- 応答の形の異常 ---


@pytest.mark.parametrize(
    "json_data",
    [
        pytest.param({}, id="embeddingが無い"),
        pytest.param({"embedding": {}}, id="valuesが無い"),
        pytest.param({"embedding": {"values": "0.1"}}, id="valuesが配列でない"),
        pytest.param([], id="応答が辞書でない"),
    ],
)
def test_embed_text_応答の形が違えばGeminiApiError(monkeypatch, json_data):
    monkeypatch.setattr(
        gemini.requests, "post", fake_post_returning(FakeResponse(json_data))
    )

    with pytest.raises(gemini.GeminiApiError):
        gemini.embed_text("文章", API_KEY)


@pytest.mark.parametrize(
    "json_data",
    [
        pytest.param({}, id="embeddingsが無い"),
        pytest.param({"embeddings": [{"values": make_values()}]}, id="件数が少ない"),
        pytest.param({"embeddings": [{"values": make_values()}] * 3}, id="件数が多い"),
        pytest.param({"embeddings": [{}, {}]}, id="valuesが無い"),
    ],
)
def test_embed_texts_応答の形や件数が違えばGeminiApiError(monkeypatch, json_data):
    monkeypatch.setattr(
        gemini.requests, "post", fake_post_returning(FakeResponse(json_data))
    )

    with pytest.raises(gemini.GeminiApiError):
        gemini.embed_texts(["一つ目", "二つ目"], API_KEY)


@pytest.mark.parametrize(
    "values",
    [
        pytest.param([0.1] * 767, id="767次元"),
        pytest.param([0.1] * 769, id="769次元"),
        pytest.param(["0.1"] + [0.1] * 767, id="文字列が混ざる"),
        pytest.param([True] + [0.1] * 767, id="boolが混ざる"),
        pytest.param([None] + [0.1] * 767, id="nullが混ざる"),
        pytest.param([math.inf] + [0.1] * 767, id="無限大が混ざる"),
        pytest.param([math.nan] + [0.1] * 767, id="NaNが混ざる"),
    ],
)
def test_ベクトルが768個の有限の数でなければGeminiApiError(monkeypatch, values):
    monkeypatch.setattr(
        gemini.requests, "post", fake_post_returning(single_response(values))
    )

    with pytest.raises(gemini.GeminiApiError):
        gemini.embed_text("文章", API_KEY)


def test_整数の値は数として受け付ける(monkeypatch):
    # JSON では 0 や 1 が整数として届くことがあるので、弾かないことを確かめる
    values = [1, 0] + [0.01] * 766
    monkeypatch.setattr(
        gemini.requests, "post", fake_post_returning(single_response(values))
    )

    assert gemini.embed_text("文章", API_KEY) == values
