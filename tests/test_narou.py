from datetime import datetime

import pytest
import requests

import narou
from tests.helpers import make_raw_novel


class FakeResponse:
    """requests.get の戻り値の代わり。"""

    def __init__(self, json_data=None, status_code=200, invalid_json=False):
        self.json_data = json_data
        self.status_code = status_code
        self.invalid_json = invalid_json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} Error")

    def json(self):
        if self.invalid_json:
            raise requests.JSONDecodeError("Expecting value", "<html>", 0)
        return self.json_data


def fake_get_returning(response, calls=None):
    """呼ばれたら response を返す偽の requests.get を作る。

    呼び出し内容は calls に記録する。
    """

    def fake_get(url, **kwargs):
        if calls is not None:
            calls.append({"url": url, **kwargs})
        return response

    return fake_get


def fake_get_raising(error):
    def fake_get(url, **kwargs):
        raise error

    return fake_get


# --- API の呼び方 ---


def test_APIを総合ポイント順_100件_必要な項目だけで呼ぶ(monkeypatch):
    calls = []
    response = FakeResponse([{"allcount": 1}, make_raw_novel()])
    monkeypatch.setattr(narou.requests, "get", fake_get_returning(response, calls))

    narou.fetch_top_novels()

    assert len(calls) == 1
    call = calls[0]
    assert call["url"] == "https://api.syosetu.com/novelapi/api/"
    assert call["params"]["out"] == "json"
    assert call["params"]["order"] == "hyoka"
    assert call["params"]["lim"] == 100
    assert set(call["params"]["of"].split("-")) == {
        "n", "t", "w", "s", "bg", "g", "k", "gp", "f", "gl",
    }  # fmt: skip
    assert call["timeout"] == 30


def test_応答の先頭のallcountを除いて作品だけを返す(monkeypatch):
    response = FakeResponse(
        [{"allcount": 2}, make_raw_novel("N0001AA"), make_raw_novel("N0002BB")]
    )
    monkeypatch.setattr(narou.requests, "get", fake_get_returning(response))

    novels = narou.fetch_top_novels()

    assert [novel["ncode"] for novel in novels] == ["N0001AA", "N0002BB"]


# --- 変換（to_novel） ---


def test_to_novel_APIの項目をDBのカラム名に対応させる():
    novel = narou.to_novel(make_raw_novel("N2710DB"))

    assert novel == {
        "ncode": "N2710DB",
        "title": "テスト作品",
        "writer": "テスト作者",
        "story": "テストのあらすじ",
        "biggenre": 2,
        "genre": 201,
        "keyword": "異世界 転生",
        "global_point": 1000,
        "fav_novel_cnt": 200,
        "general_lastup": datetime(2026, 3, 22, 23, 0, 25),
    }


def test_to_novel_keywordが空文字ならNoneにする():
    novel = narou.to_novel(make_raw_novel(keyword=""))

    assert novel["keyword"] is None


# --- 失敗したときは NarouApiError ---


def test_通信エラーならNarouApiError(monkeypatch):
    monkeypatch.setattr(
        narou.requests, "get", fake_get_raising(requests.ConnectionError())
    )

    with pytest.raises(narou.NarouApiError):
        narou.fetch_top_novels()


def test_タイムアウトならNarouApiError(monkeypatch):
    monkeypatch.setattr(narou.requests, "get", fake_get_raising(requests.Timeout()))

    with pytest.raises(narou.NarouApiError):
        narou.fetch_top_novels()


def test_HTTPエラーならNarouApiError(monkeypatch):
    response = FakeResponse(status_code=500)
    monkeypatch.setattr(narou.requests, "get", fake_get_returning(response))

    with pytest.raises(narou.NarouApiError):
        narou.fetch_top_novels()


def test_JSONでない応答ならNarouApiError(monkeypatch):
    response = FakeResponse(invalid_json=True)
    monkeypatch.setattr(narou.requests, "get", fake_get_returning(response))

    with pytest.raises(narou.NarouApiError):
        narou.fetch_top_novels()


def test_応答が配列でないならNarouApiError(monkeypatch):
    response = FakeResponse({"error": "something"})
    monkeypatch.setattr(narou.requests, "get", fake_get_returning(response))

    with pytest.raises(narou.NarouApiError):
        narou.fetch_top_novels()


def test_必要な項目が欠けていたらNarouApiError(monkeypatch):
    raw = make_raw_novel()
    del raw["title"]
    response = FakeResponse([{"allcount": 1}, raw])
    monkeypatch.setattr(narou.requests, "get", fake_get_returning(response))

    with pytest.raises(narou.NarouApiError):
        narou.fetch_top_novels()


def test_日時の形式が違っていたらNarouApiError(monkeypatch):
    response = FakeResponse(
        [{"allcount": 1}, make_raw_novel(general_lastup="2026/03/22")]
    )
    monkeypatch.setattr(narou.requests, "get", fake_get_returning(response))

    with pytest.raises(narou.NarouApiError):
        narou.fetch_top_novels()


def test_0件ならNarouApiError(monkeypatch):
    response = FakeResponse([{"allcount": 0}])
    monkeypatch.setattr(narou.requests, "get", fake_get_returning(response))

    with pytest.raises(narou.NarouApiError):
        narou.fetch_top_novels()


def test_同じncodeが2回含まれていたらNarouApiError(monkeypatch):
    response = FakeResponse(
        [{"allcount": 2}, make_raw_novel("N0001AA"), make_raw_novel("N0001AA")]
    )
    monkeypatch.setattr(narou.requests, "get", fake_get_returning(response))

    with pytest.raises(narou.NarouApiError):
        narou.fetch_top_novels()
