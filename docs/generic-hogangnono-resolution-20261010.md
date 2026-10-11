# Generic public detail-link discovery

The runtime contains no project-to-Hogangnono-ID catalog. The collector searches the notice's public title, reads the provider's published structured search data, and verifies candidate public detail pages before persisting a detail link. Search URLs are never projected into the app.

A verified detail requires the corresponding apartment/officetel type and either the exact official Applyhome `houseManageNo` + `pblancNo` published on the provider page, or the exact normalized complex name, phase/block, local address and complete parcel/road number. An explicit different numbered phase or block is rejected. The exact official announcement identity can confirm a changed marketing name or redevelopment parcel; a search suggestion or partial address cannot. Two confirmed provider details remain unresolved. Unicode, spacing, `&`/`앤`, and announcement/type suffixes are normalized without project aliases.

Only the ingestion audit pass performs provider HTTP, outside the database transaction. Each lookup allows one search and at most three detail requests, with an eight-second request timeout and a twenty-second total budget. Response bodies are bounded to 1.5 MB. Positive evidence is cached for 90 days; ambiguous/unconfirmed identities for seven days; transient provider errors retry at the next three-hour cycle. A 256-entry memory cache shares repeated identities within a process; a small rule metadata record preserves the result across restarts and ordinary API polls. Changed title/address/type/official identity invalidates reuse. List and detail serialization validates this stored evidence and exposes `hogangnono_url` without provider HTTP or extra database queries. No personal eligibility inputs are used or sent.

Validation on 2026-10-10 KST:

- New fictional project identifiers, apartment/officetel separation, phases, city/district/address mismatches, ambiguity, malformed/changed provider layout, HTTP 503, bounded memory/retries and persisted-cache serialization are covered by `api/tests/test_detail_links.py`.
- A small fixture records the actual public provider schema for the Osan officetel; it is test evidence, not a runtime catalog.
- Live generic discovery resolved 더샵 오산역아크시티 오피스텔 to `https://hogangnono.com/apt/gZL96` and 산곡역자이힐스테이트앤하늘채 to `https://hogangnono.com/apt/faQec`, each by the provider's exact current official Applyhome announcement identity. The Sangok provider name uses `&` and the redevelopment parcel is `10-1`; the official notice uses `앤` and `10`. Resolution relied on the published official identity rather than a guessed parcel equivalence.
- Unavailable or unconfirmed provider data leaves the link absent; it does not invent an ID or fall back to a user-facing search link.
