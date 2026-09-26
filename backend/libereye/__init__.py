"""LiberEye: Event-Priority Coordination of Speech and Wrist Haptics for Assistive Navigation.

Core components implementing the ICASSP 2027 paper:
- EPMCCoordinator / EPMC: Event Priority Multimodal Coordination algorithm (Alg. 1, Eq. 2, Eq. 3)
- MobilityEvent: Structured event e_i = <a_i, s_i, c_i, M_i, r_i> (Section 2.1, Eq. 1)
- BackendPerceptionPipeline / Perception Modules: Obstacles & tactile, Traffic & crossings, Search & scene & text
- SupervisoryModule: Supervisory software module for traffic, sensor-health, and immediate-risk overrides
- ScenePersistenceFSM: Scene-state persistence limiting switching across sidewalk/approaching/crossing/recovery
- WristCueProfile / TABLE1_WRIST_CUES: Table 1 wrist output cues (D1-D4, W1-W3)
- SmartphoneRelay: Smartphone speech and BLE command dispatch
- CameraGlassesReceiver: Egocentric camera glasses and phone camera fallback
"""

from .camera_glasses import CameraGlassesReceiver, GlassesBleParser, GlassesWifiReceiver
from .coordination_evaluation import CoordinationEvaluator, ReplayMetrics
from .epmc import EPMCCoordinator, EPMCResult
from .mobility_events import (
    MODULE_OBSTACLE_TACTILE,
    MODULE_SEARCH_SCENE_TEXT,
    MODULE_TRAFFIC_CROSSINGS,
    MobilityEvent,
    distance_to_d_cue,
    extract_candidate_cues,
    fuse_severities,
    select_highest_priority_cue,
)
from .models import (
    AssistancePlan,
    AvoidancePlan,
    ContextPlan,
    HapticCue,
    PerceptionFrame,
    SceneState,
    Severity,
    SpatialAudioCue,
)
from .mobility_coordinator import MobilityOrchestrator
from .perception_modules import (
    BackendPerceptionPipeline,
    ObstacleTactileModule,
    SearchSceneTextModule,
    TrafficCrossingModule,
)
from .scene_persistence import ScenePersistenceFSM
from .smartphone_relay import format_smartphone_plan, mobile_response
from .supervisory_module import SupervisoryDecision, SupervisoryModule
from .wrist_haptics import (
    TABLE1_WRIST_CUES,
    WRIST_CUE_PRIORITY_ORDER,
    WRIST_CUE_PRIORITY_RANK,
    BleWristDriver,
    FallbackWristDriver,
    MockWristDriver,
    SerialWristDriver,
    WristCueDriver,
    WristCueProfile,
    create_haptic_cue,
    create_wrist_driver,
)

# Aliases
EPMC = EPMCCoordinator

__all__ = [
    # Paper-primary names
    "EPMCCoordinator",
    "EPMC",
    "EPMCResult",
    "MobilityEvent",
    "ObstacleTactileModule",
    "TrafficCrossingModule",
    "SearchSceneTextModule",
    "BackendPerceptionPipeline",
    "SupervisoryModule",
    "SupervisoryDecision",
    "ScenePersistenceFSM",
    "WristCueProfile",
    "TABLE1_WRIST_CUES",
    "WRIST_CUE_PRIORITY_ORDER",
    "WRIST_CUE_PRIORITY_RANK",
    "create_wrist_driver",
    "create_haptic_cue",
    "format_smartphone_plan",
    "CameraGlassesReceiver",
    "CoordinationEvaluator",
    "ReplayMetrics",
    # Data models
    "AssistancePlan",
    "PerceptionFrame",
    "SceneState",
    "HapticCue",
    "AvoidancePlan",
    "ContextPlan",
    "SpatialAudioCue",
    "Severity",
    # Legacy compatibility
    "MobilityOrchestrator",
    "mobile_response",
    "GlassesWifiReceiver",
]
