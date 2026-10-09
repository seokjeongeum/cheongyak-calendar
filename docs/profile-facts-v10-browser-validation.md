# Profile factual-input browser verification

Verified 2026-10-09 with real Chromium at 375px and 1280px against local Vite and controlled public API responses. Each case used a fresh browser context and synthetic profile facts. No API credentials or existing user profile were read. This verifies the input interface and browser privacy behavior; it does not establish production deployment or official-source collection success.

All **34 browser checks passed**. The complete results are in [result.json](qa/profile-facts-v10/result.json). Native input-to-next-paint latency over eight amount-input events was **47ms maximum, 33.5ms mean**. Only `Date` was fixed for reproducible announcement comparisons; performance timing and animation frames stayed native.

- Confirmation-only household, points-family and ownership completeness questions are absent. An empty household asks the factual presence of other registered family members; answering no computes the applicant-only scope.
- Existing family DOB, register relationship, continuous registration date, home ownership and that parent's spouse ownership appear together in the parent-support summary. The section asks only a missing support start and writes it to the same identity-linked family fact.
- Multiple ancestors require an explicit identity choice. Switching parents reuses the selected person's own facts. A confirmed parent age of 60 against the official minimum of 65 stops further questions for that supply path.
- Historical gaps navigate to the original household or points input, change the visible step and focus its control. The points-history link also works when the notice has no general-supply selection-method rule.
- Official property value explains applicable public-price timing and keeps acquisition transaction price separate. Rights use the original supply contract amount with options and resale premium excluded. Both bank rank dates and the actual income-family denominator are explained.
- Changes autosave, persist when the dialog reopens and retain separate private/national bank dates. Profile editing, closing/reopening and focus/visibility return generate no API requests. Recorded public requests were GETs with no body.
- Both viewport sizes show no horizontal overflow or JavaScript exception.

Screenshots use synthetic facts:

| Case | Evidence |
| --- | --- |
| Parent facts reused at 375px | [Screenshot](qa/profile-facts-v10/parent-reuse-375.png) |
| Parent facts reused at 1280px | [Screenshot](qa/profile-facts-v10/parent-reuse-1280.png) |
| Parent age mismatch stops questions | [Screenshot](qa/profile-facts-v10/parent-age-stop-375.png) |
| Original points-history control receives focus | [Screenshot](qa/profile-facts-v10/parent-history-points-375.png) |
| Income denominator and source scope | [Screenshot](qa/profile-facts-v10/income-scope-375.png) |
| Official property/right price explanation | [Screenshot](qa/profile-facts-v10/official-price-375.png) |

Run `web/tests/profile_facts_v10_browser_qa.py` with `CHEONGYAK_QA_BASE` pointing to the local web server. Python Playwright and `/usr/bin/chromium` are required. Output defaults to `/tmp/cheongyak-profile-facts-v10-qa` and can be redirected with `CHEONGYAK_QA_OUT`.

## Regional sources and common-key display

The additional focused 375px Chromium run passed **14 checks** using the actual `parse_official_rules` output from `api/tests/fixtures/current-oct8-regions.json`. Hanyang's source was bound to the exact attachment hash `09d15961d3307e8c0fb398bd3d60fc7818e441e18f907afc0b77bd273a832600` and October 8 notice date. The upcoming reception event was synthetic to keep this case visible; the source name, region paragraphs, cutoff and hash came from the official fixture.

- Current province code `12` with each of the five mapped districts (`12210`, `12240`, `12270`, `12300`, `12330`) and sufficient continuous stay receives Hanyang local priority.
- Jin-do county `12860`, within the former Jeonnam territory, is admitted as other-region without extending former Gwangju priority to the entire merged province.
- Hwaseong remains outside that notice's region union when the applicant's dated military-serving fact is false.
- A recent move into a mapped district shows `과거 거주 이력 확인 필요`, preserves the possibility of earlier continuous residence across those districts, and offers no invented input control. Failed alternative districts do not add a misleading regional mismatch to this unresolved path; this absence was checked after the final explanation fix.
- All five saved public-service rows display `공통 키 연결됨` and retain their respective service approval links. Only configured flags were mocked; credential inputs stayed empty. No private residence facts were transmitted, and no JavaScript exception or page overflow occurred.

Results: [regional/key JSON](qa/regional-keys-v10/result.json). Evidence: [mapped local](qa/regional-keys-v10/hanyang-mapped-local-375.png), [recent residence gap](qa/regional-keys-v10/hanyang-recent-history-375.png), [common-key labels](qa/regional-keys-v10/common-key-labels-375.png).

Run `web/tests/regional_keys_v10_browser_qa.py` with the same local server variables. This run certifies the tested regional interpretation and display, not completion of every eligibility condition or a production deployment.
