from swu_mcp.deck_service import DeckService


class FakeCardService:
    def __init__(self, leaders: list[dict] | None = None) -> None:
        self.leaders = leaders or []

    def _ensure_local_catalog(self) -> None:
        pass

    def search_cards(self, **kwargs) -> dict:
        return {"cards": self.leaders}


class DummyDeckService(DeckService):
    def __init__(self, leaders: list[dict] | None = None) -> None:
        self.generate_calls = 0
        self.card_service = FakeCardService(leaders)
        self.collection_service = None
        self.sessions = {}

    def _safe_lookup(self, card: dict) -> dict:
        return card

    def generate_deck(self, **kwargs):
        self.generate_calls += 1
        return {
            "analysis": {"synergy_score": 50, "interaction_density": 10, "average_cost": 2.5, "deck_size": 80, "trait_breakdown": {}, "role_breakdown": {}, "available_aspects": []},
            "validation": {"aspect_penalties": {"total_extra_resource_burden": 0}},
            "deck_holoscan": "",
        }


def test_rank_leader_pairs_shortlist_limits_full_brews() -> None:
    top_k = 2
    leaders = [
        {
            "lookup_id": f"TST/{number:03}",
            "set_code": "TST",
            "number": f"{number:03}",
            "name": f"Leader {number}",
            "subtitle": "Shortlist Test",
            "display_name": f"Leader {number} - Shortlist Test",
            "card_type": "Leader",
            "aspects": ["Villainy"],
        }
        for number in range(1, 7)
    ]
    service = DummyDeckService(leaders)

    result = service.rank_leader_pairs(only_owned=False, top_k=top_k)

    total_pairs = len(leaders) * (len(leaders) - 1) // 2
    assert result["pairs_considered"] == total_pairs
    assert service.generate_calls <= top_k * 3
    assert service.generate_calls < total_pairs


def test_fast_score_prefers_theme_text() -> None:
    service = DummyDeckService()
    first = {"display_name": "Discard Leader", "front_text": "Discard a card from your hand.", "aspects": ["Villainy"]}
    second = {"display_name": "Recursion Leader", "back_text": "Play a card from your discard pile.", "aspects": ["Villainy"]}
    weak = {"display_name": "Blank Leader", "front_text": "", "aspects": ["Villainy"]}

    strong = service._leader_pair_fast_score(first, second, theme="discard recursion", target_packages={"discard_engine"})
    weak_score = service._leader_pair_fast_score(first, weak, theme="discard recursion", target_packages={"discard_engine"})

    assert strong > weak_score
