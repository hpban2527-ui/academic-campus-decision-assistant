# Operational activity dataset

Dataset `cbf50f877027cf14` (unilife-operational-dataset/1.0, activity contract sp3-activity/0.3), generated 2026-11-18T10:49:57+00:00. Counts are read from data/operational/activity_dataset.json; they describe data readiness, not extraction accuracy.

| Status | Posts |
| --- | ---: |
| READY | 1 |
| READY_WITH_WARNINGS | 131 |
| NOT_SCHEDULABLE | 52 |
| NOT_AN_ACTIVITY | 4 |
| DUPLICATE | 0 |
| EXTRACTION_PENDING | 1 |
| **total** | **189** |

Schedulable canonical activities: 132 (FIXED 127, FLEXIBLE_WINDOW 5). With a supported score binding: 122. Mandatory items that cannot be scheduled: 2.

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
| missing_activity_date | 13 |
| missing_duration | 1 |
| missing_fixed_start_time | 23 |
| missing_mode | 11 |
| missing_quiz_window_end | 1 |
| model_output_stale | 1 |
| uncertain:audience_scope | 2 |
| uncertain:audience_text | 1 |
| uncertain:completion_requirements | 5 |
| uncertain:mandatory_stated | 1 |
| uncertain:mode | 14 |
| uncertain:post_type | 2 |
| uncertain:title | 2 |
| uncertain:window_close | 13 |
| uncertain:window_open | 16 |

| Warning on schedulable activities | Activities |
| --- | ---: |
| activity_type_unknown | 1 |
| audience_not_stated | 46 |
| audience_restriction_unresolved | 20 |
| bounded_cost_unknown | 124 |
| domain_unknown | 13 |
| fee_not_per_person | 3 |
| fee_unknown | 124 |
| fixed_duration_default | 58 |
| location_unknown | 2 |
| multiple_sessions | 12 |
| quiz_duration_default | 1 |
| registration_deadline_missing | 96 |
| registration_link_missing | 29 |
| score_binding_unsupported | 10 |
| uncertain_soft:activity_type | 1 |
| uncertain_soft:domain | 7 |
| uncertain_soft:duration_minutes_stated | 1 |
| uncertain_soft:fee | 5 |
| uncertain_soft:location | 1 |
| uncertain_soft:multi_session | 2 |
| uncertain_soft:registration_deadline | 2 |
| uncertain_soft:registration_url | 9 |

| Student-eligibility basis (schedulable) | Activities |
| --- | ---: |
| NOT_STATED | 46 |
| OPEN_TO_STUDENTS | 62 |
| RESTRICTED_FREE_TEXT | 17 |
| RESTRICTED_TO_FIT | 2 |
| STRUCTURED_SCOPE | 2 |
| UNCLEAR | 3 |

| Score rule | Bindings |
| --- | ---: |
| R16 | 2 |
| R19 | 98 |
| R3102 | 6 |
| R31402 | 1 |
| R33 | 1 |
| R38 | 2 |
| R39 | 1 |
| R42 | 2 |
| R4302 | 2 |
| R46 | 7 |

Human decisions applied: 63 (stale: 0). Duplicate groups: 0.

## Change against the previous version

Previous: 01e1c8eaf4704f98. Added: 0. Removed: 0. Changed: 0.
