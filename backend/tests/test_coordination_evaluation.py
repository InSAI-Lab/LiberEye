"""Synthetic replay validates software behavior, never participant outcomes."""
from dataclasses import asdict

import pytest

from libereye.coordination_evaluation import CoordinationEvaluator


def test_comparison_policies_execute_distinct_output_rules():
    results = CoordinationEvaluator().evaluate_benchmark_scenarios()
    assert set(results) == {"S", "AH", "AHC"}
    assert results["S"].total_cues_emitted == 0
    assert results["S"].speech_suppressions == 0
    assert results["AH"].total_cues_emitted > results["AHC"].total_cues_emitted
    assert results["AH"].haptic_preemptions == 0
    assert results["AHC"].speech_suppressions > 0
    assert results["AHC"].haptic_preemptions > 0
    assert results["S"].spoken_character_count == results["AH"].spoken_character_count
    assert results["AHC"].spoken_character_count < results["AH"].spoken_character_count
    for metrics in results.values():
        assert metrics.physical_output_measured is False
        assert metrics.p95_latency_ms >= metrics.median_latency_ms >= 0
        assert "workload_nasa_tlx_mean" not in asdict(metrics)
        assert "near_miss_estimate" not in asdict(metrics)


def test_replays_reset_fsm_and_counters():
    evaluator = CoordinationEvaluator()
    first = evaluator.evaluate_benchmark_scenarios()
    second = evaluator.evaluate_benchmark_scenarios()
    for condition in first:
        left, right = asdict(first[condition]), asdict(second[condition])
        for key in ("median_latency_ms", "p95_latency_ms"):
            left.pop(key)
            right.pop(key)
        assert left == right


def test_study_conditions_cannot_be_presented_as_simulated_results():
    with pytest.raises(ValueError):
        CoordinationEvaluator().run_replay([], "C0")
