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

Production deployment, explicit source reprocessing and browser verification
are recorded separately once completed. The latest predeployment iH failure
was a first-page `ConnectError`; its upstream cause was not yet established.
Incremental persistence improves recovery but does not itself prove that the
external service is reachable.
