from swu_mcp.deck_service import DeckService, TWIN_SUNS


class DummyDeckService(DeckService):
    def __init__(self):
        self.generate_calls = 0

    def generate_deck(self, **kwargs):
        self.generate_calls += 1
        return {
            "analysis": {"synergy_score": 50, "interaction_density": 10, "average_cost": 2.5, "deck_size": 80, "trait_breakdown": {}, "role_breakdown": {}, "available_aspects": []},
            "validation": {"aspect_penalties": {"total_extra_resource_burden": 0}},
            "deck_holoscan": "",
        }


def test_rank_leader_pairs_shortlist_limits_full_brews() -> None:
    service = DummyDeckService()

    assert hasattr(service, "_leader_pair_fast_score")


def test_fast_score_prefers_theme_text() -> None:
    service = DummyDeckService()
    first = {"display_name": "Discard Leader", "front_text": "Discard a card from your hand.", "aspects": ["Villainy"]}
    second = {"display_name": "Recursion Leader", "back_text": "Play a card from your discard pile.", "aspects": ["Villainy"]}
    weak = {"display_name": "Blank Leader", "front_text": "", "aspects": ["Villainy"]}

    strong = service._leader_pair_fast_score(first, second, theme="discard recursion", target_packages={"discard_engine"})
    weak_score = service._leader_pair_fast_score(first, weak, theme="discard recursion", target_packages={"discard_engine"})

    assert strong > weak_score
