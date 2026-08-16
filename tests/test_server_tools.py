import asyncio
import hashlib
import json

from swu_mcp.archetypes import known_archetypes
from swu_mcp.server import mcp, swu_known_archetypes


def test_known_archetypes_tool_returns_records() -> None:
    result = swu_known_archetypes()

    assert result["count"] == len(known_archetypes())
    assert any(item["archetype_id"] == "twin-suns-kylo-trench-upgrades" for item in result["archetypes"])


def test_all_pre_change_tool_schemas_match_head_snapshot_and_only_five_tools_were_added() -> None:
    tools = {tool.name: tool for tool in asyncio.run(mcp.list_tools())}
    expected_hashes = {
        "swu_analyze_deck": "daea6fae16f30d263229e826774a0e21f7edb4d0248b159af3331dbdd62b3674",
        "swu_collection_combo_profile": "4a64d465eb7023c6eadf08d6e7351942ec13a5b695bf49bbd3e6255a5110a7fc",
        "swu_collection_summary": "99334726611ccf58a148b0814696bfa6fe08c1b2d027e946beccf5a74331c9aa",
        "swu_defeat_card": "9e6cc29476d4e10924df8c918f4f78a94aaee6640709d5bf88e21daa4867e3e2",
        "swu_draw_card": "fa4f95cf5394f4eb9734bff57e3d8a208ecb294f5ea0ee52db3a58f78f60f0a0",
        "swu_search_cards": "8f357c825ef54f70173239b4be947db5a3c9731169a6276c0cc243dbf229823a",
        "swu_lookup_card": "1c0a1abadd68b668911eaa69009dcbaf6e39f739e52754af4f8d4645b1bc0bd7",
        "swu_export_deck": "addd4472b736686b67e5eccd0014709efbbc3c79982b7b76df59b1e4d8e3ed5c",
        "swu_generate_deck": "6df54fd40daa3015188f32d372b24368daa874cb7e5cc8ba4bd77f6efed32a55",
        "swu_get_game_state": "97a8fcf2f3f1184d866a804be54f266e224c481edc9672a372f6ce4c27107e66",
        "swu_get_image": "9c6bf05c00578885bebfd7707bfac31519607b8fc6ba83a525857458822d95c7",
        "swu_get_legal_actions": "1142e35f82a53cf56449dbdcfef873a919bf15b82728990bb46adace9abe153b",
        "swu_known_archetypes": "99334726611ccf58a148b0814696bfa6fe08c1b2d027e946beccf5a74331c9aa",
        "swu_list_collection": "d872f8ff5d7c1d7b1ba7bed387e336baa34e593116cd50ea0d1213fbaeda4616",
        "swu_load_collection": "375c25158d5875aa1dc038d1e41137b35e341188d893dac997b3f91d9fecbf1d",
        "swu_move_card": "d661bd5533417c5fb5ec99778ab93f2d27ea62cf06d289ad0d05c41850894777",
        "swu_mulligan": "57235fb7eb1df928dedf670fb87d584c1ef34103ecce2ade244c8f6dbb46e23f",
        "swu_optimize_deck": "1b09bb6ca0e95acd228f32bace5f019c7cc2d42095b9e5217134a86df855fa9f",
        "swu_owned_count": "1f6d234131295802032a477c20cebf0a2820787e658ebcdae45d971250ab202d",
        "swu_play_card": "bfd4e51111eede8e7fe789f0a3f42a7d94960b81ae9ad199b657b3fc133a9b32",
        "swu_random_card": "9f7c4aad486a024dab20eb074915510add119b848f5c6c3602d51df967588dcb",
        "swu_rank_leader_pairs": "492756170d375fe062b615f34db976de1c4eb15921f2288a89b3612a8215c431",
        "swu_resource_phase": "8abce54ff9cfd93912ff0e08676de515b57eca79e42cb3dfef5b6f56d3bae6ec",
        "swu_run_deck_goldfish": "b6a75a839a96fee097d119316d79dd05c12242dd3714572846c3d4b55b84ddf1",
        "swu_set_card_state": "62d04c8cf179fd23bf7db54fe190c2c9068b510e9abb12e4e9c14ebf6b8e51e4",
        "swu_sideboard": "ebae7c30c154c7ce47efd450f4fade0c7233c24b8de9fcaf40829c39fb8a80ef",
        "swu_simulate_game": "0567ef23a0765eaecd08ca863a475ba2d42464ab748cce5f35fa21cd7c5fd822",
        "swu_start_game": "4685ff51f8da7c2204a4daa5952e7cea5f260d622cdb41f09514e6cffba9001c",
        "swu_suggest_cards": "8b8a6c7d79fd8d8fd5ca8fab4db4b4d65a215049424709bf9f5416587d8d3a27",
        "swu_take_ai_turn": "0e70224475f150bce4d6a321cc5a150cb16447b680814803f0407efbdeede462",
        "swu_take_game_action": "4c697d9dd700c4b8815c3447ee680b62fcbab5203c635e8a6cedf9262b41ba7f",
        "swu_upload_deck": "46a741e93adbcc692b57799f8d0a39f4f370ed9d4d18a80aa5a6efb55125e60c",
        "swu_validate_deck": "c5426175a1e0809819ad899860d9495540d81ed5dae3787a4dc21f595cc9738a",
        "swu_view_board": "57235fb7eb1df928dedf670fb87d584c1ef34103ecce2ade244c8f6dbb46e23f",
        "swu_view_hand": "57235fb7eb1df928dedf670fb87d584c1ef34103ecce2ade244c8f6dbb46e23f",
    }
    approved_names = {
        "swu_start_ai_brew",
        "swu_get_brew_context",
        "swu_record_brew_decisions",
        "swu_evaluate_ai_brew",
        "swu_finalize_ai_brew",
    }

    actual_hashes = {
        name: hashlib.sha256(
            json.dumps(tools[name].parameters, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        for name in expected_hashes
    }

    assert actual_hashes == expected_hashes
    assert set(tools) == set(expected_hashes) | approved_names
