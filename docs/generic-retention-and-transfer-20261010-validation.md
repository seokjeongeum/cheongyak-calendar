# Generic source retention and database transfer validation

The current parser does not import the archived notice-specific review catalogs.
Eligibility retirement uses the current document hash, parser provenance,
reviewed clauses, and supply/unit scope.

## Source retention

- A partial review retains unanswered conditions for the same document bytes.
- An explicit `waived_rule_kind` topic retires only that condition in the source-reviewed
  supply/unit scope. It requires current parser provenance, a reviewed page and a quotation.
  It cannot retire a global condition, another supply, rank, or selection condition.
- A model may state `supersedes_rule_kinds` when its current source clause replaces an older
  condition model. The new clause must retain official source/hash/page/text evidence.
- An unrelated `unparsed` exception cannot supersede an older known requirement.
- A malformed scope or topic cannot become complete through filtering or an empty `all()`.
  Generic completion requires positive integer pages and verified-condition count,
  explicit empty missing topics, and valid review metadata. Office and unranked scopes
  may omit a topic list; legacy sparse scopes remain compatible.
- Whole-source retirement additionally requires every offered supply, unrestricted unit
  coverage, and actual current admission conditions.
- Projection never rewrites preserved original notice or competition revisions.

## Database transfer

- Competition selection/locking and the initial winning-score identity lookup defer
  complete condition JSON, including a fresh-session stale-version check.
- The last competition revision lookup requests only its content hash.
- PostgreSQL merges winning-score metadata in the database, preserving other condition
  order and retaining old score rows after a failed refresh. The update is version-guarded.
- Raw feed checksums are separate from the merged document snapshot. Unchanged archived
  polls lock only notice scalars and skip retained condition JSON, historical payloads,
  competition rows and repeated revision writes. A notice-version change invalidates
  the shortcut, while a small document checkpoint supports parser/pipeline retries.
- A separate structural source checksum marks title, announcement/document identity,
  application schedule, unit or API inventory corrections pending on the same day.
  Poll and observation timestamps do not cause additional document audits. Ordered
  qualification stages retain their order in that checksum.
- Provider streaming callbacks and the final returned feed share durable identities;
  an unchanged row is not written again when a callback or the final response repeats it.
- Reprocessing compares the normalized stored patch, so equivalent parser price fields
  are not reported as another correction on every run.

## Validation

`python -m pytest -q tests/test_coverage_metadata.py tests/test_document_condition_retention.py tests/test_repository_api.py tests/test_score_transfer.py tests/test_competition.py`

Result: **143 passed**, with one existing Starlette/httpx deprecation warning.
Tests use temporary SQLite databases and mocked public responses. SQL capture verifies
that condition and historical revision payloads are not selected by these refresh paths.
PostgreSQL JSONB merge SQL was reviewed independently and tested with a narrow-session
double; it was not executed against a PostgreSQL server in this environment.

Additional final checks: **150 passed** across reprocessing, repository projection,
competition/score, feed transfer and retention, and **112 passed** across worker fairness,
collectors, parser/download retries and one-time database copy. The archive SQL capture
uses 24 notices with large source reviews and saved competition rows; a missing legacy
retry checkpoint does not force their original JSON to be transferred on each poll.
