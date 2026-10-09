# Factual profile, applicant branches and collection recovery

Validated on 2026-10-09 against parser `official-sections-2026-10-09-v12` and
document pipeline `official-downloads-2026-10-09-v13`.

## Resulting behavior

- Ordinary applicant registration no longer needs a yes/no affirmation. A
  stored explicit absence of registration remains an editable exception; older
  incomplete family rosters are not converted into complete rosters.
- Application history uses dated events and saved absence facts for exact
  canonical people. There is no history-completeness question. Adding a family
  member does not erase the applicant's or spouse's recorded facts; deleting an
  event does not create a no-history answer.
- Institution recommendation has the concrete `해당 없음` option. This and an
  explicit absence of nomination exclude that route even if the service has not
  acquired its source paragraph. Exact source lists also distinguish known
  excluded categories from unmodeled military/demolition subtypes; a generic
  missing-source label cannot rescue a named category the announcement excludes.
  Other offered routes compare independently.
- An unresolved exception cannot rescue a failure when dated facts exclude
  every recognized alternative. Known unmarried facts exclude the remarriage
  alternative; the historical Article 53 ownership exception remains a source
  review when its legal application has not been implemented.
- A notice with every application route unavailable starts closed. Its title,
  location, official source and apartment-name Hogangnono search remain visible.
  Expanding exposes the original schedules, prices and evidence. Mixed and
  unresolved notices remain open.

## Source-bound applicant reviews

Supplemental reviews require the complete page set, matching announcement
identity and exact document hash. Changed or incomplete documents do not borrow
the review. Previous compatible source facts remain available during reprocessing.

| Official announcement | Date | Pages | SHA-256 |
| --- | --- | --- | --- |
| 용인 양지 서희스타힐스 하이뷰 · 2026000386 | 2026-10-02 | 58 | `b08df1475867c4c75e2d7f3d2d94e63be338975dc9ae5578638aa8dc9e56cf96` |
| 향남역 그로브 스위첸 · 2026000463 · original | 2026-10-02 | 94 | `718d3a166be758bb8e4cae0617741b52c4d372050dcb399e5f8874583dafce01` |
| 향남역 그로브 스위첸 · 2026000463 · corrected | 2026-10-02 | 95 | `b5668bcd00f9606b110b21c9703fdce3994f5f690b43299fadeaf9ed2a73c61e` |
| 더샵 오산역아크시티 오피스텔 · 2026950086 | 2026-10-07 | 30 | `6ef50fdb5c67dc7a7e9ec8dcb2d558e37438deb0a24300bc419be7063fa06db4` |

The reviews add actual nomination categories, applicable account conditions,
family and tax branches, financial thresholds and their household scope. The
current account must remain available when applying; membership duration and
deposit proofs retain the announcement cutoff. Disabled/national-merit
nomination account exemptions do not waive other nomination categories.
Income/assets are marked inapplicable only for the explicitly exempt supplies.
Same-spouse remarriage, unsupported nomination subtypes, bank conversion dates
and conditional legal benefits retain their concrete review scopes.

Osan uses its own October 7 attachment (`atchmnflSeqNo=1988108`,
`atchmnflSn=5`). Its domestic-residence/age and unrestricted applicant-region
clauses include foreign applicants. Apartment account/rank conditions are not
inferred from its address or from a previous apartment notice.

## Durable collection and concurrent result proofs

All six provider lists are fetched before document audits, recording each
actual collection attempt. Reception/recent rows receive the first document
turns. Each turn saves that row's structured schedule/price and durable pending
audit before awaiting its public document. The source tasks share one fair
audit turn; a large historical source cannot monopolize every turn or require
every archival row to be saved before other providers start. Source state
distinguishes stored rows and pending review from a successful completed source.
Pending document state is durable across cancellation/restart. Previous
hash-bound rules, prices, rates, revisions and integration settings are retained.

On a rolling deployment the new API can observe the old owner's running job
before that owner records shutdown. A bounded, cancellable watcher observes
that exact job and uses the existing compare-and-swap claim only after it is
interrupted or its lease expires. It stops on completion, replacement or
shutdown, and does not displace a valid owner or resume without configured keys.

A competition result still must match the notice version it was fetched for.
The single competition pass starts after the first Cheongyak row is durably
saved, so an initial empty database is not sampled before any notice exists.
Absent, failed, empty and invalid feeds release the gate. Later newly stored
rows are eligible for the next regular cycle.
If a successful request becomes stale while a document audit commits, the
collector refetches against the refreshed notice once. A second change stays
pending; prior results/history remain. Failed requests are not retried by this
path, and rejected attempts do not inflate counts or write stale winning scores.

The existing three-hour collection interval is retained. Free-host inactivity
and an external scheduler are separate from these lifecycle safeguards.

## Verification

- Full API suite: **497 passed**, including list/detail projection,
  interruption/lease races, cancellation, source fairness, persistent pending
  audits and concurrent competition revisions.
- Full web suite: **531 passed**; TypeScript and production Vite build passed.
- Offline diagnosis against the current Hangang/Yongin/Hyangnam source
  snapshots: **33 checks passed**, including current account and nomination
  waivers, known unmarried exclusions and retained historical Article 53 review.
- Real Chromium: **76 checks passed** at 365px, 375px and 1280px, with no
  JavaScript exceptions, horizontal overflow, POST requests, or extra API
  requests after disclosure, profile input or focus return. The built asset was
  `/assets/index-BQtWgNst.js`. See
  [browser validation](notice-profile-v14-browser-validation.md) and its
  synthetic-profile screenshots/result JSON.
- Public Hogangnono search returned HTTP 200 with normal TLS verification.
- `git diff --check` passed.

Before deployment, public collection state still showed the previous job
interrupted at 09:24:41 UTC, with 59 Cheongyak records and other feeds unattempted.
The first rollout (`d422766`) deployed and resumed that collection, but live
progress exposed a slow global save barrier across 434 archival feed rows.
The per-row durability/fairness refinement above removes that barrier. This
report records local verified behavior; production activation and live source
processing require checking the final deployed public APIs.
