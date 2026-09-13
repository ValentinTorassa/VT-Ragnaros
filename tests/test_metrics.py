import metrics


def test_every_provider_returns_a_renderable_card():
    m = metrics.Metrics()
    for name in metrics.PROVIDERS:
        card = m.card(name)
        assert set(card) >= {"label", "value"}
        assert isinstance(card["value"], str) and card["value"]
        if "bar" in card:
            assert 0.0 <= card["bar"] <= 1.0


def test_rate_providers_need_two_samples():
    m = metrics.Metrics()
    assert m.cpu()["value"] == "--"  # no previous sample yet
    assert m.cpu()["value"].endswith("%")


def test_unknown_provider_is_reported_not_raised():
    card = metrics.Metrics().card("does_not_exist")
    assert card["value"] == "?"


def test_cards_are_capped_at_four():
    cards = metrics.Metrics().cards(metrics.PROVIDERS)
    assert len(cards) == 4


def test_a_broken_provider_degrades_to_a_placeholder(monkeypatch):
    m = metrics.Metrics()
    monkeypatch.setattr(metrics.Metrics, "ram", lambda self: 1 / 0)
    assert m.card("ram") == {"label": "RAM", "value": "--", "sub": "error"}
