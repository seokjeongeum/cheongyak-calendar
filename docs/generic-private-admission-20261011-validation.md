# Generic private and nonranked source facts

The active official parser uses applicant-section headings, printed predicates,
table headers and reconciled numeric cells. It does not select a review by
project name, notice number, document hash or fixed page.

- Private general, institution, first-home, elderly-parent and newborn facts keep
  their actual supply scope and source quotation. Unsupported remarriage, prior
  ownership and childbirth alternatives remain explicit conditional review gaps.
- The first-home solo-household area predicate also covers a source note that all
  offered homes exceed its limit; that note does not create a second eligibility
  question.
- Cancellation-resupply special routes use their own operative applicant tables.
  A general route absent from the current inventory does not impose general-only
  facts on those applicants. Unreviewed special-history requirements still prevent
  full eligibility certification.
- Exclusive areas require the model code, its independent exclusive-area column,
  the type alias and the exclusive-plus-common subtotal to agree. Interleaved PDF
  headers are supported; advertised supply area is not substituted.
- Price-cap facts require this offering's direct declaration in one sentence.
  Statutory example rows cannot override it, and contradictory declarations leave
  the cap unverified.
- Nonranked income alternatives reconcile their policy amount with the household
  asset table. Additional-person income uses the printed formula and percentage,
  with consistency checks against the table's last row.
- Common applicant geography is reviewed separately from narrower special routes.
  HWPX evidence is cited as a section, preserving the distinction from a PDF page.
- New office eligibility predicates do not need an existing fact-name match to
  remain unreviewed. Known submission/application procedures are removed as
  closed statements, and unknown conditions inside the base applicant paragraph
  or a familiar children's parenthesis remain visible to the audit.

Regression cases change the notice identity, date, hash and page positions. They
also exercise interleaved area columns, statutory price-cap examples, conflicting
declarations, missing mandatory clauses and unknown requirements sharing a known
applicant sentence. All data comes from offline official-document fixtures or
synthetic mutations; no personal input or live database is used.

Validation: **177 passed** across the private, Hangang, Sangok, v3 official,
generic admission/audit/nonranked, official-rules, unranked, family, regional and
selection suites. One existing Starlette/httpx deprecation warning remains.
The independent source audit also passed 20 admission-audit and generic-region
tests after checking subtype geography, cap declarations and numeric tables.
