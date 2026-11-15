"""SP3 feasibility assessment public interface."""

from .availability import (
    AVAILABILITY_VERSION,
    ApplyScope,
    AvailabilityContractError,
    resolve_availability,
)

from .feasibility import (
    CONTRACT_VERSION,
    EligibilityStatus,
    FeasibilityContractError,
    FeasibilityEvidence,
    FeasibilityStatus,
    ProgressStatus,
    RegistrationStatus,
    ScheduleType,
    TermScopeStatus,
    assess_feasibility,
)
from .planner import (
    AVAILABLE_PRESETS,
    PlanFilters,
    PresetMode,
    SpeedMode,
    build_plan,
    recommend_plans,
    what_if_skip,
)

__all__ = [
    "AVAILABLE_PRESETS",
    "AVAILABILITY_VERSION",
    "ApplyScope",
    "AvailabilityContractError",
    "CONTRACT_VERSION",
    "EligibilityStatus",
    "FeasibilityContractError",
    "FeasibilityEvidence",
    "FeasibilityStatus",
    "PlanFilters",
    "PresetMode",
    "ProgressStatus",
    "RegistrationStatus",
    "ScheduleType",
    "SpeedMode",
    "TermScopeStatus",
    "assess_feasibility",
    "build_plan",
    "recommend_plans",
    "resolve_availability",
    "what_if_skip",
]
