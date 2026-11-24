"""The one demo clock of the UniLife demo.

Every "now" in the real-store demo (planner as_of, planning window start, completion clock) comes
from here, so activities after DEMO_TODAY are always "not yet happened", whatever the real date is.
Set UNILIFE_COMPLETION_AS_OF only in tests or scripts that must move the completion clock.
"""

DEMO_TODAY = "2026-10-25"
DEMO_AS_OF = f"{DEMO_TODAY}T08:00:00+07:00"
DEMO_WINDOW_START = f"{DEMO_TODAY}T00:00:00+07:00"
