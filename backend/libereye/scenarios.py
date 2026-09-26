from __future__ import annotations

from .models import SceneState


SCENARIOS = {
    "sidewalk": SceneState(
        name="sidewalk",
        description="Proceeding along a sidewalk with continuous tactile paving and a green traffic light.",
        obstacle_distance_m=4.5,
        tactile_blocked=False,
        traffic_light="green",
        crowd_level="low",
        user_intent="navigate",
    ),
    "blocked": SceneState(
        name="blocked",
        description="A temporary obstacle blocks the tactile paving. Take a short detour, then return to the paving.",
        obstacle_distance_m=2.2,
        tactile_blocked=True,
        traffic_light="green",
        crowd_level="medium",
        user_intent="navigate",
    ),
    "crossing": SceneState(
        name="crossing",
        description="The user is approaching a crossing with a red light and an approaching vehicle.",
        obstacle_distance_m=2.8,
        tactile_blocked=False,
        traffic_light="red",
        vehicle_approaching=True,
        crowd_level="medium",
        user_intent="cross",
    ),
    "finding": SceneState(
        name="finding",
        description="The user is searching for a partly occluded cup in a public space.",
        obstacle_distance_m=2.4,
        tactile_blocked=False,
        traffic_light="unknown",
        target_query="cup",
        target_distance_m=2.0,
        target_direction="right",
        target_confidence=0.9,
        crowd_level="low",
        user_intent="find",
    ),
    "compound_navigation": SceneState(
        name="compound_navigation",
        description="Combined navigation task: follow the sidewalk, avoid the construction barrier on the right, and check traffic signals before crossing.",
        obstacle_distance_m=1.8,
        tactile_blocked=True,
        traffic_light="unknown",
        crowd_level="high",
        user_intent="navigate",
        scene_type="sidewalk",
    ),
}
