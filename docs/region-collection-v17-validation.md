# Generic regional clauses and interrupted feed recovery

The current Sangdong official attachment states that applicants must reside in
Seoul, Incheon or Gyeonggi and belong to a household without a home. Its cover
summary and operative table list those same provinces in different orders.
The parser now treats a regional OR list as a set and retains the actual
applicant table's evidence instead of replacing it with the cover summary.

The verified attachment is the October 6, 2026 notice, attachment sequence
1991039 / 2, with SHA-256
`8c4d8a5c9f46e7ec5c73439ffc4f008d592f60c12f6a99242f477ee1063387bc`.
Its page 8 applicant and selection table supports the capital-region scope,
the homeless-household condition, and a shared random draw without a regional
division. The parser uses headings and clauses, never a notice ID, title, hash
or fixed page. A synthetic new identity, date, hash and shifted pages produces
the same interpretation. Current clauses with a genuinely different region
remain incomplete. An explicit priority in separate current general notes is
retained with its own evidence; a random draw cannot erase it.

Parser V17 keeps compatible V16 facts while reprocessing. The browser also
compares regional OR sets independently of printed order, including nested
priority-region alternatives. Actual conditions, priority durations, exceptions,
criterion dates and scope completeness still distinguish offers. Inputs and
source objects are not mutated.

The production collector previously saved 23 current Cheongyakhom notices but
reached its 600-second feed deadline while fetching historical unit models
serially. Historical rows were only returned after all model queries finished.
Model queries now have at most three concurrent requests and commit ready
batches of six, while current notices retain precedence. Each successful iH
page is also delivered for persistence before the next page is fetched. Ready
sibling rows are saved before an error is propagated. Duplicate current/final
callbacks do not write the same unchanged row again. Tests verify preservation
of existing prices, document hashes and revision history after a later failure.

Known transient public-data result codes 01/02/04/05 now retry even when their
error envelope arrives with HTTP 200. Authentication, quota and other
nontransient errors stop immediately. The existing three-attempt limit and
HTTPS/TLS verification remain in place. Nested network errors expose only a
small static allowlist of cause categories; exception text, URLs, keys, traces
and unrecognized class names are omitted.

Seonun's July 8 original remains unavailable. The actual GMCC URL failed in
the HTTP path and an independent Firecrawl live fetch; both correct Myhome
sale-detail mirrors also failed. Earlier March/June notices and July news
articles were not substituted as official proof. A page-download failure no
longer also claims that its uninspected page contains no attachment. A retrieved
page with no attachment remains a separate diagnostic.

Validation before deployment:

- Full isolated API suite: 843 passed, 2 PostgreSQL opt-in cases skipped.
- Final regional/priority regression after independent review: 99 passed.
- Final safe network-cause regression: 43 passed.
- Frontend: all 593 tests passed; production build passed.
- The full downloaded Sangdong source with its public API inventory produces
  a complete general-supply review and page 8 regional/home-ownership evidence.

Production validation:

- Commit `023e3c74fb17cf72f84a228ec269180d39e8211d` deployed successfully on
  free Render at 2026-10-11 20:05 UTC, with browser asset `index-iDPuMwe4.js`.
- Explicit document reprocessing run `38170826402` completed successfully.
  Sangdong's public response is version 8 with V17 page 8 capital-region and
  homeless-household evidence, the original SHA-256, and documented shared
  random selection. All 7 prices and its competition rows are unchanged;
  revision history grew from 7 to 8. Seonun is version 6, retains its original
  null hash and empty prices/results, and retains all 6 revisions. Its failed
  official-page download is reported without an extra unsupported claim that
  no attachment exists.
- Actual deployed collection-status refresh made a new coverage GET and
  updated its status time. Shared-key labels agree across services, saved
  password inputs remain empty, no private facts or POSTs were transmitted,
  there were no JavaScript errors, and the 375px page had no overflow.
- Deployed-asset Chromium checks for synthetic new notices passed all 12
  checks: equivalent regional sets retain admission and reception candidates,
  genuinely differing scopes remain separate, and the excluded supply stays
  closed with its reason available. Focus/visibility return makes no API query.
- Strict source-only Chromium validation of the refreshed production Sangdong
  DTO passed all 16 checks. Hwaseong is admitted without a regional division;
  an outside-capital-region profile has the official province-range reason
  visible on its closed card. Source hash, announcement date and page evidence
  agree with the baseline and refreshed API. There are no extra focus requests,
  personal facts in API traffic, JavaScript exceptions or 375px overflow.

## Collector deadline follow-up

An older scheduled collection remained active well after its cooperative feed
and competition deadlines. Code inspection confirms synchronous database work
and competition branches with no await can delay those timers. It does not
establish which database operation caused that production delay. The run
eventually completed successfully as `38168617049`; its already committed
source data remained available throughout.

CLI collection now uses a separate PostgreSQL engine with a 10-second connect
timeout and transaction-local 5-second lock and 30-second statement limits.
The shared session factory is bound only inside the CLI cycle; web, migration,
schema initialization and SQLite keep their existing engines. A heartbeat
captures its own bounded factory so a delayed final renewal cannot switch to
the restored web factory. Both save and competition loops yield to overdue
timers on every path. A failed audit rolls back before reading recovery state.
Raw-page and document-review progress labels use explicit phases.

Validation after this follow-up:

- Full isolated API suite: 860 passed, 2 opt-in cases skipped (156.29 seconds).
- Focused lifecycle, deadline and recovery regression: 97 passed.
- Actual local PostgreSQL: 4 checks passed using only a connection-private
  temporary table and a unique test advisory lock. The server reports the
  expected 5s/30s limits. Reduced per-transaction test limits trigger query
  cancellation (`57014`) and lock timeout (`55P03`); rollback retains the
  previously committed row and the next transaction is reusable. Ordinary
  sessions retain their original settings. No application tables, roles or
  persistent schemas were changed.
- Independent final review confirmed heartbeat binding, rollback and phase
  handling with no remaining confirmed blocker.

PostgreSQL statement limits bound server execution, not every possible stalled
network socket read. The latest predeployment iH failure was a first-page
`ConnectError`; its upstream cause was not yet established. No-key public
probes from this workspace reach both API hosts (401/400), which does not prove
authorized collection from the GitHub runner. Incremental persistence and
retries improve recovery but do not prove external service availability.
