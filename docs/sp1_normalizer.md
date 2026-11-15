# SP1 layer B normaliser

`sp1.normalize.normalize(layer_a, source, config)` accepts an envelope conforming to
`schemas/layer_a_record_v2.schema.json` and emits an activity conforming to
`schemas/activity_v2.schema.json`. Use `load_config()` once when processing a batch. The normaliser
keeps its inputs independent of the returned record. It neither parses natural language nor assigns
a planner slot.

| Rule | Table row | Function | Derived rule ID | Test |
| --- | --- | --- | --- | --- |
| Mandatory without participation cues | N1.1 | `_recognition` | `rule:mandatory_no_participation_cue` | `test_recognition` |
| Activity and information | N1.2–3 | `_recognition` | `rule:post_type_activity`, `rule:post_type_info_only` | `test_recognition` |
| Insufficient or missing post type | N1.4 | `_recognition` | — | `test_recognition` |
| Keep stated window times and null bounds | N2.1, N2.3, N2.5 | `_datetime_value`, `_iso` | — | `test_window` |
| Date-only window bounds | N2.2, N2.4 | `_datetime_value` | `rule:date_only_0000`, `rule:date_only_2359` | `test_window` |
| Reversed window | N2.6 | `normalize` | — | `test_reversed_window` |
| Stated, unknown and unsupported duration | N3.1–3, N3.6, N3.8 | `_duration` | — | `test_duration` |
| Same-day offline duration from stated times | N3.4 | `_duration` | `rule:window_span` | `test_duration` |
| Offline duration default | N3.5 | `_duration` | `team_default:default_offline_2h` | `test_duration` |
| Online quiz duration default | N3.7 | `_duration` | `team_default:default_quiz_30m` | `test_duration` |
| Other online duration default | N3.9 | `_duration` | `team_default:default_online_30m` | `test_duration` |
| Online campus and venue | N4.1 | `_place` | `rule:online_campus_empty`, `rule:online_location_null` | `test_place` |
| Unstated venue | N4.2, N4.4 | `_place` | `rule:location_missing` | `test_place` |
| Campus dictionary | N4.3 | `_place` | `dict:campus_v1.0.0` | `test_place` |
| Stated obligation, fee and audience | N5.1, N5.3, N5.5 | `_team_defaults` | — | `test_mandatory`, `test_fee`, `test_audience` |
| Defaults for obligation, fee and audience | N5.2, N5.4, N5.6 | `_team_defaults` | `team_default:mandatory_false`, `team_default:fee_not_stated_free`, `team_default:audience_all` | `test_mandatory`, `test_fee`, `test_audience` |
| Semester by activity date, missing date or out of scope | N6 | `_semester` | `rule:semester_from_window_open` | `test_semester` |
| Overlapping inclusive semester bounds | N6 | `load_config` | — | `test_overlapping_inclusive_semesters_raise` |
| Date-only registration and completion deadlines | A4 | `_datetime_value` | `rule:date_only_2359` | `test_deadlines` |
| Temporary activity ID | ADR-0001 D5 | `normalize` | `rule:temp_id_url_sha1` | `test_status_and_passthrough` |
| Status from actionable flags | A4 status | `_status` | — | `test_status_and_passthrough`, `test_place` |

When a duration is stated, its value is preserved and `duration_source` records its provenance.
Date-only bounds and deadlines carry their field paths in both `meta.time_defaults` and
`meta.derived`. Adding seconds to a stated clock time is ISO formatting.

## Open items

- A hybrid activity without stated duration, an offline activity without a stated opening time,
  and a multi-session online activity without a quiz or stated duration get null duration with
  `duration_source: unsupported`. Same-day offline times that are equal or reversed also provide
  no usable duration. A reversed window is flagged independently.
- A missing registration deadline stays null and is listed in `meta.unsupported`.
- SP2 mapping, mandatory schedule clashes, and online completion timing beyond stated requirements
  have no new rule in this normaliser.
