# Neon free transfer reduction · 2026-10-09

Reported project allowance: 4.2 GB used of 5 GB. Already transferred bytes cannot be recovered by a code change. No hosting upgrade, database deletion, snapshot truncation, credential change, or collection interval change is part of this fix.

The Notice ORM previously eagerly loaded every NoticeRevision, including full historical JSON, on list reads and collector concurrency refreshes. Revisions now load only on explicit history access; original payload JSON is separately deferred until explicitly accessed. Public detail history still exposes every saved version/hash/time. The listing discovers matching and superseded notice identities with scalar columns and reads current canonical/duplicate records in one batch, rather than rereading current rules and querying duplicates per notice.

A regression records executed SQL with a 600,000-character preserved original: list and collector lock reads issue zero revision queries; detail reads revision metadata without the payload column; direct payload access returns the original unchanged. Existing corrected-notice, duplicate, result, price and retention regressions run unchanged.

The browser still polls collection progress every 30 seconds while collection runs. Progress now coalesces automatic full calendar/agenda reloads to at most once per three minutes, including when a pending change stops progressing. Source completion appears immediately. Manual refresh still starts an immediate refresh, hidden tabs still avoid polling, and focus return still performs no network request. Initial status reads do not cause a duplicate initial notice load.

These changes reduce repeated database downloads. This does not assert the observed project's exact bytes saved or current remaining allowance; verification uses local synthetic data and avoids further production list polling.
