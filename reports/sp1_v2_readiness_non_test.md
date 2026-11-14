# SP1 non-test readiness

Corpus size is 129 non-test posts.
V1 has no post_type or activity_type. Its participation proxy is drl_recognized=true.
Both versions use the same configured semester bounds and plannability conditions.
Persisted evidence retains original offsets. Evidence text is phone-redacted on export.
The in-memory extraction retains exact original evidence slices.

| Metric | v1 count / denominator | v1 share | v2 count / denominator | v2 share |
| --- | ---: | ---: | ---: | ---: |
| activity_type:academic_competition | n/a | n/a | 11 / 129 | 8.5% |
| activity_type:blood_donation | n/a | n/a | 2 / 129 | 1.6% |
| activity_type:career_admissions_event | n/a | n/a | 3 / 129 | 2.3% |
| activity_type:club_membership | n/a | n/a | 1 / 129 | 0.8% |
| activity_type:culture_sports_competition | n/a | n/a | 5 / 129 | 3.9% |
| activity_type:legal_health_campaign | n/a | n/a | 8 / 129 | 6.2% |
| activity_type:other | n/a | n/a | 23 / 129 | 17.8% |
| activity_type:seminar_workshop | n/a | n/a | 68 / 129 | 52.7% |
| activity_type:university_history | n/a | n/a | 1 / 129 | 0.8% |
| activity_type:volunteer | n/a | n/a | 7 / 129 | 5.4% |
| mode | 98 / 129 | 76.0% | 114 / 129 | 88.4% |
| offline | 88 / 129 | 68.2% | 105 / 129 | 81.4% |
| offline_location | 88 / 88 | 100.0% | 104 / 105 | 99.0% |
| plannable | 17 / 129 | 13.2% | 92 / 129 | 71.3% |
| post_type:activity | 24 / 129 | 18.6% | 120 / 129 | 93.0% |
| post_type:info_only | 0 / 129 | 0.0% | 1 / 129 | 0.8% |
| post_type:insufficient | 0 / 129 | 0.0% | 8 / 129 | 6.2% |
| post_type:unclassified | 105 / 129 | 81.4% | 0 / 129 | 0.0% |
| registration_deadline | 21 / 129 | 16.3% | 35 / 129 | 27.1% |
| semester:HK1_2026_2027 | 60 / 129 | 46.5% | 62 / 129 | 48.1% |
| semester:HK3_2025_2026 | 47 / 129 | 36.4% | 50 / 129 | 38.8% |
| semester:insufficient_data | 14 / 129 | 10.9% | 8 / 129 | 6.2% |
| semester:out_of_scope_semester | 8 / 129 | 6.2% | 9 / 129 | 7.0% |
| status:failed | 11 / 129 | 8.5% | 6 / 129 | 4.7% |
| status:partial | 27 / 129 | 20.9% | 25 / 129 | 19.4% |
| status:valid | 91 / 129 | 70.5% | 98 / 129 | 76.0% |
| window_open | 115 / 129 | 89.1% | 121 / 129 | 93.8% |

## Reasons excluding a post

Reasons may overlap.

| Method | Reason | Posts |
| --- | --- | ---: |
| v1 | post_type | 105 |
| v1 | mode | 31 |
| v1 | semester | 22 |
| v1 | window_open | 14 |
| v1 | failed_status | 11 |
| v2 | semester | 17 |
| v2 | mode | 15 |
| v2 | post_type | 9 |
| v2 | window_open | 8 |
| v2 | failed_status | 6 |
