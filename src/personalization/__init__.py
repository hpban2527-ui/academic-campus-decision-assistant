"""AI-assisted preference interpretation for personalized schedules."""

from personalization.models import (
    CampusId,
    CategoryId,
    ConfirmedPreferenceSaveRequest,
    HardExclusions,
    InterpretPreferenceRequest,
    PersonalizedPlanRequest,
    ModeId,
    PersonalizationLimits,
    PlanningStrategy,
    StudentPreference,
    TimeSlotId,
    TopicId,
)
from personalization.providers import (
    PreferenceProviderInvalidResponse,
    PreferenceProviderUnavailable,
    preference_provider_from_env,
)
from personalization.planner_adapter import (
    PreparedPersonalization,
    prepare_personalized_planner_input,
)
from personalization.profile_assistant import (
    ProfileAssistantDraft,
    ProfileExtraction,
    ProfilePatchAction,
    deterministic_profile_extraction,
    merge_profile_extraction,
    merge_profile_extractions,
)

__all__ = [
    "CampusId",
    "CategoryId",
    "ConfirmedPreferenceSaveRequest",
    "HardExclusions",
    "InterpretPreferenceRequest",
    "PersonalizedPlanRequest",
    "ModeId",
    "PersonalizationLimits",
    "PlanningStrategy",
    "PreparedPersonalization",
    "PreferenceProviderInvalidResponse",
    "PreferenceProviderUnavailable",
    "StudentPreference",
    "TimeSlotId",
    "TopicId",
    "preference_provider_from_env",
    "prepare_personalized_planner_input",
    "ProfileAssistantDraft",
    "ProfileExtraction",
    "ProfilePatchAction",
    "deterministic_profile_extraction",
    "merge_profile_extraction",
    "merge_profile_extractions",
]
