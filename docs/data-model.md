# Data model

SQLite via SQLAlchemy 2.0 async. Three tables.

## `calls`
| column         | type          | notes                                    |
| -------------- | ------------- | ---------------------------------------- |
| `id`           | `str` PK      | `call_<12 hex>`                          |
| `source`       | `str`         | `upload` \| `live`                       |
| `started_at`   | `datetime`    | UTC. Used as `t = now − started_at`.     |
| `ended_at`     | `datetime?`   | set by `POST /api/calls/{id}/end`        |
| `metrics_json` | `JSON`        | latest `MetricsSnapshot` (DTO-shaped)    |
| `assist_json`  | `JSON`        | latest `OperatorAssist` (DTO-shaped)     |

Metrics + assist are stored as JSON on the call row. We don't need a history for
the demo and it keeps reads to a single statement.

## `transcript_segments`
| column          | type      | notes                                 |
| --------------- | --------- | ------------------------------------- |
| `id`            | `str` PK  | stable across partial→final updates   |
| `call_id`       | FK        | `ON DELETE CASCADE`                   |
| `t_start`       | `float`   | seconds since `started_at`            |
| `t_end`         | `float`   |                                       |
| `speaker`       | `str`     | `caller` \| `bystander` \| `operator` \| `unknown` |
| `text`          | `text`    |                                       |
| `is_final`      | `bool`    |                                       |
| `confidence`    | `float`   | 0..1                                  |
| `entities_json` | `JSON`    | list of `{type, text, field?}`        |

Partial → final is `repository.transcript.upsert()` — same `id`, fields overwritten.

## `incident_fields`
| column                    | type     | notes                                 |
| ------------------------- | -------- | ------------------------------------- |
| `call_id`                 | FK PK    | composite PK with `field`             |
| `field`                   | `str` PK | one of the 11 names in `FIELD_NAMES`  |
| `value`                   | `text?`  |                                       |
| `status`                  | `str`    | `missing` \| `heard` \| `suggested` \| `confirmed_by_operator` \| `uncertain` \| `contradicted` |
| `confidence`              | `float`  | 0..1                                  |
| `source_segment_ids_json` | `JSON`   | list of segment ids                   |
| `updated_at_t`            | `float?` | seconds since `started_at`            |

On `POST /api/calls`, all 11 rows are seeded with `status='missing'`.
`repository.incident.upsert_extracted()` will not overwrite a row whose status
is already `confirmed_by_operator` — only the operator can move out of that
state, via `PATCH /api/calls/{id}/incident`.

## Coverage math (assembled, not stored)

Computed in `repository.incident.assemble_card()` whenever a card is read:

```
field_coverage      = populated / 11
confirmed_coverage  = confirmed / 11
dispatch_readiness  = 0.5 * field_coverage + 0.5 * confirmed_coverage
```

Where `populated` excludes `missing` rows and `confirmed` counts only
`confirmed_by_operator`.
