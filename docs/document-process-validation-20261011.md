# Stored notice dates in the public document process

The production reprocess job downloaded valid PDF files but recorded decoding
failures for all four readable documents. Their hashes matched the locally
readable originals. A clean installed wheel with the production dependencies
also read the same files successfully.

The failure occurred before the child process: retained notice payloads from
`_existing_payload()` contain Python `date` values in the announcement and
application events. The subprocess request used plain `json.dumps()`, which
raised `TypeError` for those dates. Empty-payload tests did not cover this path.

The request now encodes only `date`/`datetime` as ISO strings and still rejects
other unsupported objects. It does not mutate the stored original. The child
retains its memory, input/output and timeout limits. Failures expose only a
fixed allowlist of exception names and processing stages, without messages,
traces or values. The pipeline version changes so previous unreadable results
can be retried on the same day.

Regression checks use a nonblank PDF and an actual retained `Notice` plus
`NoticeEvent` payload with dates. Additional checks cover unknown object
rejection, sanitized diagnostics and retry of the previous pipeline's decode
failure. No applicant profile or API key is used.

Runtime, diagnostics, retry, condition-retention and region/contract regression:
102 passed in 10.80 seconds. Actual LH and Hangang PDFs also passed in a clean
installed-wheel environment using the production dependencies, with retained
date values in the request. Earlier requests with those dates raised `TypeError`
before creating a child process.

Production reprocess run `38135794640` completed successfully. Hangang,
Hyangnam, Sangok and Busan Yeonji now have V15 source interpretation and
successful PDF decode diagnostics. Busan Yeonji's general branch is complete;
private-document special branches retain their explicit conditional gaps.
Seonun's official attachment remains unavailable and is reported as a discovery
failure without a fabricated document hash or regional eligibility.

The four existing document hashes and all existing price/competition rows
were retained. Each updated public snapshot adds a revision rather than
deleting history. Comparing the previous revision against the actual new rule
set with the source-aware retention policy found no missing compatible
admission facts in the three private documents.

A separate persistence regression was also corrected: partial same-hash
reprocessing could filter out a compatible unanswered fact solely because its
original parser version differed. Persistence now reuses the same existing
retention policy as enrichment. Explicit waivers, replacements, complete
source reviews and changed document hashes still retire old facts. The
reprocess/condition-retention checks pass 48 tests, including preserved dates,
prices, source provenance, history and idempotence.

The final browser check against the new production snapshots found a separate
area-table regression: Hyangnam's PDF joins the four-decimal common and supply
area cells without whitespace, so only one of eight exclusive areas survived
the stricter column parser. The parser now supports that fixed-precision layout
and still requires agreement between the model, alias and printed exclusive
area, plus a valid exclusive/common/subtotal sum. Spaced variable-precision
cells remain supported; wrong sums and ambiguous precision are rejected.

Parser V16 triggers another review of V15 partial results and preserves V15
facts while that review is pending. Generic area, retry, region/contract and
reprocess checks pass 77 tests. The full Hyangnam PDF, processed in the child
with retained date values, produces all eight exclusive areas from page 8 with
the original document hash. Synthetic new unit codes also pass; this change
does not depend on a notice name, number or catalog of areas.
