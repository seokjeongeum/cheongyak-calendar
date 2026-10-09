# Complete notice disclosure and factual profile browser validation

Validated on 2026-10-09: **76 real Chromium checks passed** against production
build asset `/assets/index-BQtWgNst.js`, at 365px, 375px, and 1280px. Its SHA-256 is
`f6882dd22dd5d9d29d7aae9cf77961ba0daf03717dffa3ee700d5b348881fc44`.
The isolated
pages had no JavaScript exceptions, horizontal overflow, POST requests, or
additional API requests after disclosure, profile-input, or focus actions.
See `docs/qa/notice-profile-v14/result.json` and the ten screenshots beside it.

The browser test uses the built application in `web/dist`, completely synthetic
profiles, and synthetic public API responses. Playwright fulfills every request
to `https://qa.invalid` directly from those local files and fixtures. Requests for
external assets are fulfilled locally; the test does not contact the production
app, follow official or Hogangnono links, or use any API/admin keys.

Run after the final web production build:

```sh
cd web
npm run build
cd ..
CHEONGYAK_QA_OUT=docs/qa/notice-profile-v14 python web/tests/notice_profile_v14_browser_qa.py
```

The 365px, 375px, and 1280px cases exercise:

- A confirmed outside-region notice begins with its whole body closed while its
  title, address, unavailable badge, official source, and Hogangnono link remain
  visible.
- Native keyboard disclosure opens schedules, prices, and source links, and
  closes those sections again without issuing an API request.
- Possible, unresolved, and mixed supply notices remain expanded. A failed
  special supply does not collapse the available general supply.
- Hogangnono queries contain the apartment name only. Numbered apartment phases
  are retained; the repeated application suffix is removed.
- The profile omits the ordinary applicant-register affirmation and the
  history-completeness affirmation. A real registration exception and dated
  history events remain editable.
- Choosing the concrete institution reason `해당 없음` makes only institution
  supply unavailable and saves the fact in the existing browser profile.
- Adding and deleting an applicant event preserves the spouse's exact saved
  no-history answer. Adding a new canonical parent asks only that person's
  actual history and saves a positive event with the same canonical person ID.
- Layout stays within the viewport and profile edits or focus return cause no
  API request, POST, or JavaScript exception.

The generated `result.json` records the built JavaScript asset and its SHA-256,
the passed checks, fixture API requests, and JavaScript exceptions. Screenshots
show the closed and opened notices and the factual institution input.
