# Operational activity dataset

Dataset `b1b293901cdbbd30` (unilife-operational-dataset/1.0, activity contract sp3-activity/0.3), generated 2026-11-18T16:15:20+00:00. Counts are read from data/operational/activity_dataset.json; they describe data readiness, not extraction accuracy.

| Status | Posts |
| --- | ---: |
| READY | 1 |
| READY_WITH_WARNINGS | 126 |
| NOT_SCHEDULABLE | 57 |
| NOT_AN_ACTIVITY | 4 |
| DUPLICATE | 0 |
| EXTRACTION_PENDING | 1 |
| **total** | **189** |

Schedulable canonical activities: 127 (FIXED 120, FLEXIBLE_WINDOW 7). With a supported score binding: 117. Mandatory items that cannot be scheduled: 2.

| Extraction method | Posts |
| --- | ---: |
| None | 1 |
| ai_annotation | 129 |
| sp1_v2_model_replay | 59 |

| Split | Posts |
| --- | ---: |
| dev_extra | 24 |
| dev_gold | 16 |
| pool | 89 |
| test | 60 |

| Not schedulable: reason | Posts |
| --- | ---: |
| fixed_duration_over_12h | 3 |
| missing_activity_date | 13 |
| missing_duration | 1 |
| missing_fixed_start_time | 23 |
| missing_mode | 11 |
| missing_quiz_window_end | 1 |
| model_output_stale | 1 |
| uncertain:audience_scope | 2 |
| uncertain:audience_text | 1 |
| uncertain:mandatory_stated | 1 |
| uncertain:mode | 18 |
| uncertain:post_type | 7 |
| uncertain:title | 2 |
| uncertain:window_close | 17 |
| uncertain:window_open | 20 |

| Warning on schedulable activities | Activities |
| --- | ---: |
| activity_type_unknown | 1 |
| audience_not_stated | 41 |
| audience_restriction_unresolved | 17 |
| bounded_cost_unknown | 119 |
| domain_unknown | 12 |
| fee_not_per_person | 3 |
| fee_unknown | 119 |
| fixed_duration_default | 56 |
| location_unknown | 1 |
| multiple_sessions | 13 |
| online_window_treated_as_flexible | 1 |
| quiz_duration_default | 1 |
| registration_deadline_missing | 93 |
| registration_link_missing | 28 |
| score_binding_unsupported | 10 |
| uncertain_soft:activity_type | 1 |
| uncertain_soft:completion_requirements | 3 |
| uncertain_soft:domain | 7 |
| uncertain_soft:duration_minutes_stated | 1 |
| uncertain_soft:fee | 4 |
| uncertain_soft:location | 1 |
| uncertain_soft:multi_session | 3 |
| uncertain_soft:registration_deadline | 2 |
| uncertain_soft:registration_url | 9 |

| Student-eligibility basis (schedulable) | Activities |
| --- | ---: |
| NOT_STATED | 41 |
| OPEN_TO_STUDENTS | 66 |
| RESTRICTED_FREE_TEXT | 15 |
| RESTRICTED_TO_FIT | 1 |
| STRUCTURED_SCOPE | 2 |
| UNCLEAR | 2 |

| Score rule | Bindings |
| --- | ---: |
| R16 | 3 |
| R19 | 94 |
| R3102 | 6 |
| R31402 | 1 |
| R33 | 1 |
| R38 | 2 |
| R39 | 1 |
| R42 | 2 |
| R46 | 7 |

Human decisions applied: 63 (stale: 0). Duplicate groups: 0.

## Change against the previous version

Previous: dc457569c065a947. Added: 0. Removed: 0. Changed: 13.
- pfbid026Sq6YJVpvZ94HBx364fXmJs2i5jTLFKHE6Yt2XziXy6jcsuuuzM38EPfGBsYUn2gl: status, reasons, sp3_activity, binding, features (READY_WITH_WARNINGS -> NOT_SCHEDULABLE)
- pfbid02gENqCMzeMBYaWH3zsqfExUZ5coUdTv7jS37xfTeJijUPRfYs6utzCZGZ3H6o9mYQl: status, reasons, sp3_activity, binding, features (READY_WITH_WARNINGS -> NOT_SCHEDULABLE)
- pfbid02nBhkYKDvQr3jTEnDwyyykJ6eEWWiJmjqTDt6KBbeTm7ucnwnLftxyFRSaYfXjBbDl: status, reasons, sp3_activity, binding, features (READY_WITH_WARNINGS -> NOT_SCHEDULABLE)
- pfbid02zyFDsiq3o68YGWrRuhvSitLHd5SK4segqABuRCRhSq8Y9orEo7sEjs6Tx6LbgVxLl: status, reasons, sp3_activity, binding, features (READY_WITH_WARNINGS -> NOT_SCHEDULABLE)
- pfbid0348peH7andUqAfothwtJxbr5BQnQKPbTUZWjoGcuba4gMHMeBazFxpUseEBGd78xwl: status, reasons, sp3_activity, binding, features (READY_WITH_WARNINGS -> NOT_SCHEDULABLE)
- pfbid03JtQFt1ThCdY31bYF4xAct8ZAgQ4P6F7fzXiGAXNrG4vyrARwVXzvgSEApmDP1k4l: reasons (NOT_SCHEDULABLE -> NOT_SCHEDULABLE)
- pfbid03UiW9MaH5rbtETZ5Yj6c1MqdRgDj1ZDzmpgitawKmbZNc5hqAeHRgAidcAqkK48Kl: status, reasons, sp3_activity, binding, features (READY_WITH_WARNINGS -> NOT_SCHEDULABLE)
- pfbid06exFW2AyQW5HDpHfyMWnECX7HdaZMm7szug6R5JXkU3QE2EuDiCRzqspwxjqTnkpl: features (READY_WITH_WARNINGS -> READY_WITH_WARNINGS)
- pfbid0AEzrJsJY7PUJjjBi4qxUx3L5XFRuTt9GuRKTvvaidxagcFN6xd3Ru6DsccNpuPNEl: reasons (NOT_SCHEDULABLE -> NOT_SCHEDULABLE)
- pfbid0HSj8yJoaxt3xytoxrhDDsnBXbzqoKXCNJooAbB9zusiNDkSWg1Cj1Mz2cJf676mml: status, reasons, sp3_activity, binding, features (READY_WITH_WARNINGS -> NOT_SCHEDULABLE)
- pfbid0YbKfdmeThGmwCrgSQ4QNPQXNRkK6AXsfbGdPcMDb5GwGYHJvRNPVYzLDfqeQ6SZ3l: reasons (NOT_AN_ACTIVITY -> NOT_AN_ACTIVITY)
- pfbid0boR7w7iRdsuvBfCXvESjpRi81S7Js93u4QHY9jXCS7yUF1A2NYoYYewBPaMXdHRYl: status, reasons, sp3_activity, binding, features (READY_WITH_WARNINGS -> NOT_SCHEDULABLE)
- pfbid0dJnSk1s2Vgn1eiFSYgKRbjoCTbKtKXv4qbzRex8Lvim74YKNMbdvwWyYrYeGXRabl: reasons (NOT_SCHEDULABLE -> NOT_SCHEDULABLE)
