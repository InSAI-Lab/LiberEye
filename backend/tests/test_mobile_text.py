from types import SimpleNamespace

from libereye.mobile_contract import _compact, _next_action, _scene_brief, _spoken_summary


def test_english_summary_preserves_decimal_distances():
    plan = SimpleNamespace(
        main_instruction="Obstacle 1.5 m ahead. Slow down.",
        voice_message="Obstacle 1.5 m ahead. Slow down.",
    )
    evidence = {"scene_description": "Obstacle 1.5 m ahead. A shop is on the right."}

    assert _scene_brief(plan, evidence) == "Obstacle 1.5 m ahead"
    assert _next_action(plan) == "Obstacle 1.5 m ahead"
    assert _spoken_summary("Sidewalk.", "Caution", "Slow down.") == "Sidewalk. Caution. Slow down."


def test_english_compaction_keeps_complete_words():
    assert _compact("Continue along the walkable pavement", 24) == "Continue along the..."
