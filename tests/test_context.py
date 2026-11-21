"""Market context: live snapshot sources and the delisting safety rule."""


def test_market_context_snapshot_and_delisting_guard(tmp_path):
    from datetime import datetime, timezone

    from aitrader import context
    from aitrader.registry import Registry

    reg = Registry(tmp_path / "r.sqlite")
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    answers = {
        "alternative.me": {"data": [{"value": "23", "value_classification": "Extreme Fear"}, {"value": "40"}]},
        "deribit": {"result": {"data": [[1, 0, 0, 0, 50.0], [2, 0, 0, 0, 60.0], [3, 0, 0, 0, 55.0]]}},
        "account-ratio": {"result": {"list": [{"buyRatio": "0.62", "sellRatio": "0.38"}]}},
        "announcements": {"result": {"list": [
            {"title": "Delisting of FOOUSDT Perpetual Contract", "dateTimestamp": now_ms},
            {"title": "Bybit will delist BARUSDT spot trading pair", "dateTimestamp": now_ms},
            {"title": "New listing: BAZUSDT Perpetual Contract", "dateTimestamp": now_ms}]}},
    }

    def fake_get(url):
        return next(v for k, v in answers.items() if k in url)

    snap = context.refresh(reg, get=fake_get)
    assert snap["fear_greed"] == {"value": 23, "label": "Extreme Fear", "week_ago": 40}
    assert snap["dvol"]["value"] == 55.0 and snap["long_short"]["BTC"] == 62.0
    assert context.delisted_pairs(reg) == {"FOO/USDT:USDT"}  # perpetual delisting only
    # a failing source keeps the previous value; nothing raises
    snap2 = context.refresh(reg, get=lambda url: (_ for _ in ()).throw(OSError("offline")))
    assert snap2["fear_greed"]["value"] == 23 and len(reg.kv_get("context_hist")) == 1
    view = context.snapshot(reg)
    assert len(view["markets"]) == 5 and all("next" in m for m in view["markets"])
    assert all(e["kind"] in ("CPI", "NFP", "FOMC") for e in view["events"])
