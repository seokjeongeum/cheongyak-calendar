# Reusable history facts and focused official-source fixes · 2026-10-09

Generic winning/special-winning history now requires the actual person, event kind and date, with the special-supply fact where relevant. A project identifier is required only for an explicit same-project rule or original-project contract ownership. Missing project identity cannot be used to assume that an event belongs to a different project. Existing complete/no-history answers retain their exact person identities; a new family member receives no invented absence.

The restriction form distinguishes actual ineligible-winner and detected resale/supply-order violation histories from a current restriction lookup. Explicit lifetime absence is reused across original notice dates without asking a change date. A current inactive answer is not converted into lifetime absence. Conflicting current or saved past active restrictions request correction. Saved facts that already cover a notice date cause no additional lifetime-history question. Collective absence is cleared when household identities change; applicant facts are retained.

Supply summaries group identical comparisons across housing types even when the source repeats a condition in different paragraphs. The status, actual requirement, dates, input and comparison detail remain part of the group identity. Different thresholds or results remain separate; expanded combinations retain every source quotation.

## First-home ancestor ownership

The [current Article 53, effective 2026-06-15](https://www.law.go.kr/LSW/lsSideInfoP.do?docCls=jo&joNo=0053&joBrNo=00&lsiSeq=286965&urlMode=lsScJoRltInfoR) and [MOLIT's first-home Q&A](https://www.korea.kr/news/policyNewsView.do?newsId=148878382) support excluding a qualifying ancestor's current and past ownership. The official Q&A establishes this particular ownership exception; its older spouse, income and allocation rules are not imported. The announcement-age reference is additionally corroborated by the [MOLIT first-home Q&A](https://www.molit.go.kr/USR/policyTarget/dtl.jsp?idx=168), indexed with its notice-date example; the page itself did not load in the verification browser.

The browser applies only the first-home private-apartment branch from 2026-06-15 through the evaluation date, with the notice's verified Article 53 ancestor clause attached to the same SHA-256 document hash. It reuses the canonical ancestor's birth date and notice-date family roster. A missing birth date points to that family input. Applicant, descendant, younger ancestor and unsupported other Article 53 histories remain explicit reviews. The spouse's documented pre-marriage acquisition-and-disposal exception can combine with the ancestor exception; it does not waive other owners. Public rental and elder-parent supply receive no first-home carve-out. The official guidance link appears next to the existing source evidence when applied.

This browser correction works with already stored reviewed clauses, avoiding a global document reprocessing pass.

## Current official sources

| Notice | Document SHA-256 | Verified behavior |
| --- | --- | --- |
| 산곡역자이힐스테이트앤하늘채 · 2026000458 · 2026-10-08 | `10597652e7b524abfc4b6609e00f430793f820b0732c130f94c788585285e67b` | General regional ordering and both area bands' 40% points / 60% lottery on page 26; first-home income → region → lottery on page 21; multi-child Incheon 50% and Seoul/Gyeonggi 50% on page 14, with unsuccessful Incheon applicants advancing without local priority in the remaining quota. |
| 당산역 더클래스 한강 · 2026950087 · 2026-10-06 | `99df9ab26e35d6af38b68c4d39f3d2d9b830460c232d77d725868a31dfda9804` | Current 11-page PDF, domestic adult age 19, unrestricted application region, no apartment rank or required account. The applicant paragraph's reordered PDF date is checked against the reviewed October 6 announcement date. |

[Sangok current attachment](https://static.applyhome.co.kr/ai/aia/getAtchmnfl.do?houseManageNo=2026000458&pblancNo=2026000458&atchmnflSeqNo=1995089&atchmnflSn=2) · [Dangsan current attachment](https://static.applyhome.co.kr/ai/aia/getAtchmnfl.do?houseManageNo=2026950087&pblancNo=2026950087&atchmnflSeqNo=1988261&atchmnflSn=4).

The Sangok test inventory uses the API stock schema, with all housing-type counts cross-checked against page 6's official table (1,289 total, 604 general and 685 special). It is a constructed regression input representing that inventory, not a claimed live API response. No address-derived region or assumed statutory default ratio is used. Missing percentages, changed hashes and mismatching notice identities stay unverified.

Only these two matching notice-number/date pairs receive a new focused processing marker. The global parser and download pipeline versions are unchanged. A collection attempts the new review once, records its processing result, and preserves ordinary retry behavior and unrelated same-day audits. Applying the code does not itself prove that the live background collection has finished processing both records.

## Validation

- API suite: **520 passed**, including focused official-document and one-attempt processing tests.
- Web suite: **547 passed**; TypeScript and Vite production build passed.
- Offline Chromium: **79 checks passed** on 365px, 375px and 1280px. Entire unavailable notices and unavailable supply branches start closed; other possible or unresolved notices stay open. Keyboard expansion, official/Hogangnono links, optional generic project IDs, exact-person history edits and browser-only storage were verified.
- Browser build: `/assets/index-DRsKdZAZ.js`; QA output: `/tmp/cheongyak-notice-profile-v15-qa`. All app assets and API responses were served from local fixtures. No real profile, credential, production collection or list response was used by this browser test.
- Deadline ordering, retained gray items, three-hour collection configuration, contract-today/KST date comparisons and no focus-return requests remain covered by the existing suites.

No pricing/competition/original/revision deletion, credential change, paid hosting or allowance upgrade is included. The separate [Neon transfer validation](neon-transfer-reduction-validation.md) describes the already deployed reductions and their measurement limits.
