# SP1 segmentation coverage on dev

N0 and N1 were run on 40 development posts. Label counts measure posts with at least
one matching field. They measure coverage of the configured headings.

| Measure | Posts | Share |
| --- | ---: | ---: |
| `time` | 21 / 40 | 52.5% |
| `place` | 24 / 40 | 60.0% |
| `audience` | 15 / 40 | 37.5% |
| `mode` | 5 / 40 | 12.5% |
| `registration` | 11 / 40 | 27.5% |
| `deadline` | 4 / 40 | 10.0% |
| `fee` | 3 / 40 | 7.5% |
| `recognition` | 1 / 40 | 2.5% |
| `requirement` | 0 / 40 | 0.0% |
| `contact` | 4 / 40 | 10.0% |
| No label line | 8 / 40 | 20.0% |
| At least one phone masked | 2 / 40 | 5.0% |
| At least one injection flag | 0 / 40 | 0.0% |
| `injection_suspected:ignore_instructions` | 0 / 40 | 0.0% |
| `injection_suspected:role_marker` | 0 / 40 | 0.0% |
| `injection_suspected:prompt_terms` | 0 / 40 | 0.0% |
| `injection_suspected:delimiter` | 0 / 40 | 0.0% |
| `injection_suspected:code_fence` | 0 / 40 | 0.0% |
| 0 title candidates | 0 / 40 | 0.0% |
| 1 title candidates | 1 / 40 | 2.5% |
| 2 title candidates | 1 / 40 | 2.5% |
| 3 title candidates | 38 / 40 | 95.0% |
| First candidate equals v1 gold title | 6 / 16 | 37.5% |

The title comparison is case-sensitive after NFC and whitespace normalisation. The denominator
includes retained dev gold posts with a v1 title. This compares candidate ranking against v1
titles, which may use different prefix and decoration conventions.
