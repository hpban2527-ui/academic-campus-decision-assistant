# SP1 LLM development comparison

Small development samples (16 gold v1 + 5 completed gold v2 in the current corpus).
These are dev results used for policy selection, not a held-out test evaluation.
LLM-only means LLM on decidable fields with mandatory rules fallback on invalid/missing decisions.
Unlabelled activity_type has n=0 and cannot influence model selection or policy.
Retry rates count recorded second replies only. Single notebook replies cannot reveal hypothetical retry success.
Wilson field-trial intervals do not account for correlated errors within posts.

Chosen model: fake/rules-fallback. Runner-up: fake/closed-labels.
Selection: total correct on decidable labelled fields, then fewer fabricated, then mean seconds/post.

## fake/rules-fallback

Labelled posts: 21. Mean/max seconds per post: 3.000/3.000. Peak VRAM: 0.000 GiB.
Selection counts: {'correct': 127, 'fabricated': 4, 'seconds': 3}

classify: valid 0/21 (0.0%); recorded retry 0/21 (0.0%).
roles: valid 0/21 (0.0%); recorded retry 0/21 (0.0%).
Error codes: {'no_json': 42}

### Gold v1

| Method | Field | n | Correct | Wrong | Fabricated | Missed | 95% Wilson |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| rules | title | 16 | 9 | 7 | 0 | 0 | 33.2%-76.9% |
| rules | window_open | 16 | 13 | 2 | 1 | 0 | 57.0%-93.4% |
| rules | window_close | 16 | 15 | 0 | 0 | 1 | 71.7%-98.9% |
| rules | registration_deadline | 16 | 15 | 0 | 0 | 1 | 71.7%-98.9% |
| rules | mode | 16 | 12 | 1 | 0 | 3 | 50.5%-89.8% |
| rules | location | 16 | 11 | 1 | 0 | 4 | 44.4%-85.8% |
| rules | fee | 16 | 15 | 0 | 0 | 1 | 71.7%-98.9% |
| rules | registration_url | 16 | 13 | 0 | 2 | 1 | 57.0%-93.4% |
| rules | mandatory_stated | 16 | 16 | 0 | 0 | 0 | 80.6%-100.0% |
| rules | domain | 16 | 8 | 4 | 0 | 4 | 28.0%-72.0% |
| rules | TOTAL | 160 | 127 | 15 | 3 | 15 | 72.5%-84.9% |
| llm | title | 16 | 9 | 7 | 0 | 0 | 33.2%-76.9% |
| llm | window_open | 16 | 13 | 2 | 1 | 0 | 57.0%-93.4% |
| llm | window_close | 16 | 15 | 0 | 0 | 1 | 71.7%-98.9% |
| llm | registration_deadline | 16 | 15 | 0 | 0 | 1 | 71.7%-98.9% |
| llm | mode | 16 | 12 | 1 | 0 | 3 | 50.5%-89.8% |
| llm | location | 16 | 11 | 1 | 0 | 4 | 44.4%-85.8% |
| llm | fee | 16 | 15 | 0 | 0 | 1 | 71.7%-98.9% |
| llm | registration_url | 16 | 13 | 0 | 2 | 1 | 57.0%-93.4% |
| llm | mandatory_stated | 16 | 16 | 0 | 0 | 0 | 80.6%-100.0% |
| llm | domain | 16 | 8 | 4 | 0 | 4 | 28.0%-72.0% |
| llm | TOTAL | 160 | 127 | 15 | 3 | 15 | 72.5%-84.9% |
| hybrid | title | 16 | 9 | 7 | 0 | 0 | 33.2%-76.9% |
| hybrid | window_open | 16 | 13 | 2 | 1 | 0 | 57.0%-93.4% |
| hybrid | window_close | 16 | 15 | 0 | 0 | 1 | 71.7%-98.9% |
| hybrid | registration_deadline | 16 | 15 | 0 | 0 | 1 | 71.7%-98.9% |
| hybrid | mode | 16 | 12 | 1 | 0 | 3 | 50.5%-89.8% |
| hybrid | location | 16 | 11 | 1 | 0 | 4 | 44.4%-85.8% |
| hybrid | fee | 16 | 15 | 0 | 0 | 1 | 71.7%-98.9% |
| hybrid | registration_url | 16 | 13 | 0 | 2 | 1 | 57.0%-93.4% |
| hybrid | mandatory_stated | 16 | 16 | 0 | 0 | 0 | 80.6%-100.0% |
| hybrid | domain | 16 | 8 | 4 | 0 | 4 | 28.0%-72.0% |
| hybrid | TOTAL | 160 | 127 | 15 | 3 | 15 | 72.5%-84.9% |

### Gold v2

| Method | Field | n | Correct | Wrong | Fabricated | Missed | 95% Wilson |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| rules | post_type | 5 | 4 | 1 | 0 | 0 | 37.6%-96.4% |
| rules | title | 5 | 4 | 1 | 0 | 0 | 37.6%-96.4% |
| rules | domain | 5 | 3 | 0 | 0 | 2 | 23.1%-88.2% |
| rules | multi_session | 5 | 4 | 0 | 0 | 1 | 37.6%-96.4% |
| rules | window_open | 5 | 5 | 0 | 0 | 0 | 56.6%-100.0% |
| rules | window_close | 5 | 5 | 0 | 0 | 0 | 56.6%-100.0% |
| rules | duration_minutes_stated | 5 | 5 | 0 | 0 | 0 | 56.6%-100.0% |
| rules | registration_deadline | 5 | 5 | 0 | 0 | 0 | 56.6%-100.0% |
| rules | mode | 5 | 2 | 1 | 1 | 1 | 11.8%-76.9% |
| rules | location | 5 | 4 | 0 | 0 | 1 | 37.6%-96.4% |
| rules | audience_text | 5 | 2 | 1 | 1 | 1 | 11.8%-76.9% |
| rules | audience_scope | 5 | 5 | 0 | 0 | 0 | 56.6%-100.0% |
| rules | mandatory_stated | 5 | 5 | 0 | 0 | 0 | 56.6%-100.0% |
| rules | recognition_stated | 5 | 5 | 0 | 0 | 0 | 56.6%-100.0% |
| rules | points_stated | 5 | 5 | 0 | 0 | 0 | 56.6%-100.0% |
| rules | fee | 5 | 5 | 0 | 0 | 0 | 56.6%-100.0% |
| rules | registration_url | 5 | 5 | 0 | 0 | 0 | 56.6%-100.0% |
| rules | join_url | 5 | 5 | 0 | 0 | 0 | 56.6%-100.0% |
| rules | completion_requirements | 5 | 5 | 0 | 0 | 0 | 56.6%-100.0% |
| rules | TOTAL | 95 | 83 | 4 | 2 | 6 | 79.2%-92.6% |
| llm | post_type | 5 | 4 | 1 | 0 | 0 | 37.6%-96.4% |
| llm | title | 5 | 4 | 1 | 0 | 0 | 37.6%-96.4% |
| llm | domain | 5 | 3 | 0 | 0 | 2 | 23.1%-88.2% |
| llm | multi_session | 5 | 4 | 0 | 0 | 1 | 37.6%-96.4% |
| llm | window_open | 5 | 5 | 0 | 0 | 0 | 56.6%-100.0% |
| llm | window_close | 5 | 5 | 0 | 0 | 0 | 56.6%-100.0% |
| llm | duration_minutes_stated | 5 | 5 | 0 | 0 | 0 | 56.6%-100.0% |
| llm | registration_deadline | 5 | 5 | 0 | 0 | 0 | 56.6%-100.0% |
| llm | mode | 5 | 2 | 1 | 1 | 1 | 11.8%-76.9% |
| llm | location | 5 | 4 | 0 | 0 | 1 | 37.6%-96.4% |
| llm | audience_text | 5 | 2 | 1 | 1 | 1 | 11.8%-76.9% |
| llm | audience_scope | 5 | 5 | 0 | 0 | 0 | 56.6%-100.0% |
| llm | mandatory_stated | 5 | 5 | 0 | 0 | 0 | 56.6%-100.0% |
| llm | recognition_stated | 5 | 5 | 0 | 0 | 0 | 56.6%-100.0% |
| llm | points_stated | 5 | 5 | 0 | 0 | 0 | 56.6%-100.0% |
| llm | fee | 5 | 5 | 0 | 0 | 0 | 56.6%-100.0% |
| llm | registration_url | 5 | 5 | 0 | 0 | 0 | 56.6%-100.0% |
| llm | join_url | 5 | 5 | 0 | 0 | 0 | 56.6%-100.0% |
| llm | completion_requirements | 5 | 5 | 0 | 0 | 0 | 56.6%-100.0% |
| llm | TOTAL | 95 | 83 | 4 | 2 | 6 | 79.2%-92.6% |
| hybrid | post_type | 5 | 4 | 1 | 0 | 0 | 37.6%-96.4% |
| hybrid | title | 5 | 4 | 1 | 0 | 0 | 37.6%-96.4% |
| hybrid | domain | 5 | 3 | 0 | 0 | 2 | 23.1%-88.2% |
| hybrid | multi_session | 5 | 4 | 0 | 0 | 1 | 37.6%-96.4% |
| hybrid | window_open | 5 | 5 | 0 | 0 | 0 | 56.6%-100.0% |
| hybrid | window_close | 5 | 5 | 0 | 0 | 0 | 56.6%-100.0% |
| hybrid | duration_minutes_stated | 5 | 5 | 0 | 0 | 0 | 56.6%-100.0% |
| hybrid | registration_deadline | 5 | 5 | 0 | 0 | 0 | 56.6%-100.0% |
| hybrid | mode | 5 | 2 | 1 | 1 | 1 | 11.8%-76.9% |
| hybrid | location | 5 | 4 | 0 | 0 | 1 | 37.6%-96.4% |
| hybrid | audience_text | 5 | 2 | 1 | 1 | 1 | 11.8%-76.9% |
| hybrid | audience_scope | 5 | 5 | 0 | 0 | 0 | 56.6%-100.0% |
| hybrid | mandatory_stated | 5 | 5 | 0 | 0 | 0 | 56.6%-100.0% |
| hybrid | recognition_stated | 5 | 5 | 0 | 0 | 0 | 56.6%-100.0% |
| hybrid | points_stated | 5 | 5 | 0 | 0 | 0 | 56.6%-100.0% |
| hybrid | fee | 5 | 5 | 0 | 0 | 0 | 56.6%-100.0% |
| hybrid | registration_url | 5 | 5 | 0 | 0 | 0 | 56.6%-100.0% |
| hybrid | join_url | 5 | 5 | 0 | 0 | 0 | 56.6%-100.0% |
| hybrid | completion_requirements | 5 | 5 | 0 | 0 | 0 | 56.6%-100.0% |
| hybrid | TOTAL | 95 | 83 | 4 | 2 | 6 | 79.2%-92.6% |

## fake/closed-labels

Labelled posts: 21. Mean/max seconds per post: 3.000/3.000. Peak VRAM: 0.000 GiB.
Selection counts: {'correct': 37, 'fabricated': 0, 'seconds': 3}

classify: valid 21/21 (100.0%); recorded retry 0/21 (0.0%).
roles: valid 21/21 (100.0%); recorded retry 0/21 (0.0%).
Error codes: {}

### Gold v1

| Method | Field | n | Correct | Wrong | Fabricated | Missed | 95% Wilson |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| rules | title | 16 | 9 | 7 | 0 | 0 | 33.2%-76.9% |
| rules | window_open | 16 | 13 | 2 | 1 | 0 | 57.0%-93.4% |
| rules | window_close | 16 | 15 | 0 | 0 | 1 | 71.7%-98.9% |
| rules | registration_deadline | 16 | 15 | 0 | 0 | 1 | 71.7%-98.9% |
| rules | mode | 16 | 12 | 1 | 0 | 3 | 50.5%-89.8% |
| rules | location | 16 | 11 | 1 | 0 | 4 | 44.4%-85.8% |
| rules | fee | 16 | 15 | 0 | 0 | 1 | 71.7%-98.9% |
| rules | registration_url | 16 | 13 | 0 | 2 | 1 | 57.0%-93.4% |
| rules | mandatory_stated | 16 | 16 | 0 | 0 | 0 | 80.6%-100.0% |
| rules | domain | 16 | 8 | 4 | 0 | 4 | 28.0%-72.0% |
| rules | TOTAL | 160 | 127 | 15 | 3 | 15 | 72.5%-84.9% |
| llm | title | 16 | 0 | 0 | 0 | 16 | 0.0%-19.4% |
| llm | window_open | 16 | 4 | 0 | 0 | 12 | 10.2%-49.5% |
| llm | window_close | 16 | 8 | 0 | 0 | 8 | 28.0%-72.0% |
| llm | registration_deadline | 16 | 7 | 0 | 0 | 9 | 23.1%-66.8% |
| llm | mode | 16 | 3 | 0 | 0 | 13 | 6.6%-43.0% |
| llm | location | 16 | 11 | 1 | 0 | 4 | 44.4%-85.8% |
| llm | fee | 16 | 15 | 0 | 0 | 1 | 71.7%-98.9% |
| llm | registration_url | 16 | 3 | 0 | 0 | 13 | 6.6%-43.0% |
| llm | mandatory_stated | 16 | 16 | 0 | 0 | 0 | 80.6%-100.0% |
| llm | domain | 16 | 0 | 0 | 0 | 16 | 0.0%-19.4% |
| llm | TOTAL | 160 | 67 | 1 | 0 | 92 | 34.5%-49.6% |

### Gold v2

| Method | Field | n | Correct | Wrong | Fabricated | Missed | 95% Wilson |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| rules | post_type | 5 | 4 | 1 | 0 | 0 | 37.6%-96.4% |
| rules | title | 5 | 4 | 1 | 0 | 0 | 37.6%-96.4% |
| rules | domain | 5 | 3 | 0 | 0 | 2 | 23.1%-88.2% |
| rules | multi_session | 5 | 4 | 0 | 0 | 1 | 37.6%-96.4% |
| rules | window_open | 5 | 5 | 0 | 0 | 0 | 56.6%-100.0% |
| rules | window_close | 5 | 5 | 0 | 0 | 0 | 56.6%-100.0% |
| rules | duration_minutes_stated | 5 | 5 | 0 | 0 | 0 | 56.6%-100.0% |
| rules | registration_deadline | 5 | 5 | 0 | 0 | 0 | 56.6%-100.0% |
| rules | mode | 5 | 2 | 1 | 1 | 1 | 11.8%-76.9% |
| rules | location | 5 | 4 | 0 | 0 | 1 | 37.6%-96.4% |
| rules | audience_text | 5 | 2 | 1 | 1 | 1 | 11.8%-76.9% |
| rules | audience_scope | 5 | 5 | 0 | 0 | 0 | 56.6%-100.0% |
| rules | mandatory_stated | 5 | 5 | 0 | 0 | 0 | 56.6%-100.0% |
| rules | recognition_stated | 5 | 5 | 0 | 0 | 0 | 56.6%-100.0% |
| rules | points_stated | 5 | 5 | 0 | 0 | 0 | 56.6%-100.0% |
| rules | fee | 5 | 5 | 0 | 0 | 0 | 56.6%-100.0% |
| rules | registration_url | 5 | 5 | 0 | 0 | 0 | 56.6%-100.0% |
| rules | join_url | 5 | 5 | 0 | 0 | 0 | 56.6%-100.0% |
| rules | completion_requirements | 5 | 5 | 0 | 0 | 0 | 56.6%-100.0% |
| rules | TOTAL | 95 | 83 | 4 | 2 | 6 | 79.2%-92.6% |
| llm | post_type | 5 | 0 | 5 | 0 | 0 | 0.0%-43.4% |
| llm | title | 5 | 0 | 0 | 0 | 5 | 0.0%-43.4% |
| llm | domain | 5 | 0 | 0 | 0 | 5 | 0.0%-43.4% |
| llm | multi_session | 5 | 0 | 0 | 0 | 5 | 0.0%-43.4% |
| llm | window_open | 5 | 1 | 0 | 0 | 4 | 3.6%-62.4% |
| llm | window_close | 5 | 1 | 0 | 0 | 4 | 3.6%-62.4% |
| llm | duration_minutes_stated | 5 | 5 | 0 | 0 | 0 | 56.6%-100.0% |
| llm | registration_deadline | 5 | 3 | 0 | 0 | 2 | 23.1%-88.2% |
| llm | mode | 5 | 1 | 0 | 0 | 4 | 3.6%-62.4% |
| llm | location | 5 | 4 | 0 | 0 | 1 | 37.6%-96.4% |
| llm | audience_text | 5 | 2 | 1 | 1 | 1 | 11.8%-76.9% |
| llm | audience_scope | 5 | 5 | 0 | 0 | 0 | 56.6%-100.0% |
| llm | mandatory_stated | 5 | 5 | 0 | 0 | 0 | 56.6%-100.0% |
| llm | recognition_stated | 5 | 5 | 0 | 0 | 0 | 56.6%-100.0% |
| llm | points_stated | 5 | 5 | 0 | 0 | 0 | 56.6%-100.0% |
| llm | fee | 5 | 5 | 0 | 0 | 0 | 56.6%-100.0% |
| llm | registration_url | 5 | 1 | 0 | 0 | 4 | 3.6%-62.4% |
| llm | join_url | 5 | 5 | 0 | 0 | 0 | 56.6%-100.0% |
| llm | completion_requirements | 5 | 5 | 0 | 0 | 0 | 56.6%-100.0% |
| llm | TOTAL | 95 | 53 | 6 | 1 | 35 | 45.8%-65.4% |

## Measured policy

```json
{
  "post_type": "agree_else_review",
  "activity_type": "rules",
  "domain": "rules",
  "mode": "agree_else_review",
  "title": "rules",
  "multi_session": "rules",
  "window_open": "rules",
  "window_close": "rules",
  "registration_deadline": "rules",
  "registration_url": "rules",
  "join_url": "rules",
  "_evidence": {
    "post_type": {
      "n": 5,
      "rules": {
        "correct": 4,
        "wrong": 1
      },
      "llm": {
        "correct": 4,
        "wrong": 1
      },
      "wins": 0,
      "null_wins": 0,
      "null_losses": 0
    },
    "activity_type": {
      "n": 0,
      "rules": {},
      "llm": {},
      "wins": 0,
      "null_wins": 0,
      "null_losses": 0
    },
    "domain": {
      "n": 21,
      "rules": {
        "wrong": 4,
        "missed": 6,
        "correct": 11
      },
      "llm": {
        "wrong": 4,
        "missed": 6,
        "correct": 11
      },
      "wins": 0,
      "null_wins": 0,
      "null_losses": 0
    },
    "mode": {
      "n": 21,
      "rules": {
        "correct": 14,
        "wrong": 2,
        "missed": 4,
        "fabricated": 1
      },
      "llm": {
        "correct": 14,
        "wrong": 2,
        "missed": 4,
        "fabricated": 1
      },
      "wins": 0,
      "null_wins": 0,
      "null_losses": 0
    },
    "title": {
      "n": 21,
      "rules": {
        "correct": 13,
        "wrong": 8
      },
      "llm": {
        "correct": 13,
        "wrong": 8
      },
      "wins": 0,
      "null_wins": 0,
      "null_losses": 0
    },
    "multi_session": {
      "n": 5,
      "rules": {
        "correct": 4,
        "missed": 1
      },
      "llm": {
        "correct": 4,
        "missed": 1
      },
      "wins": 0,
      "null_wins": 0,
      "null_losses": 0
    },
    "window_open": {
      "n": 21,
      "rules": {
        "correct": 18,
        "fabricated": 1,
        "wrong": 2
      },
      "llm": {
        "correct": 18,
        "fabricated": 1,
        "wrong": 2
      },
      "wins": 0,
      "null_wins": 0,
      "null_losses": 0
    },
    "window_close": {
      "n": 21,
      "rules": {
        "correct": 20,
        "missed": 1
      },
      "llm": {
        "correct": 20,
        "missed": 1
      },
      "wins": 0,
      "null_wins": 0,
      "null_losses": 0
    },
    "registration_deadline": {
      "n": 21,
      "rules": {
        "correct": 20,
        "missed": 1
      },
      "llm": {
        "correct": 20,
        "missed": 1
      },
      "wins": 0,
      "null_wins": 0,
      "null_losses": 0
    },
    "registration_url": {
      "n": 21,
      "rules": {
        "correct": 18,
        "fabricated": 2,
        "missed": 1
      },
      "llm": {
        "correct": 18,
        "fabricated": 2,
        "missed": 1
      },
      "wins": 0,
      "null_wins": 0,
      "null_losses": 0
    },
    "join_url": {
      "n": 5,
      "rules": {
        "correct": 5
      },
      "llm": {
        "correct": 5
      },
      "wins": 0,
      "null_wins": 0,
      "null_losses": 0
    }
  },
  "_model_id": "fake/rules-fallback",
  "_prompt_versions": {
    "classify": "sp1_classify_v2 1.0.0",
    "roles": "sp1_roles_v2 1.0.0"
  }
}
```
