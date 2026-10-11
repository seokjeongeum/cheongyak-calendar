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
