# QML ROM and recovery catalogs

This slice is based on UI PR #2 (`1484b303`), with no main merge. It uses one shared CatalogPage and
QObject projection for ROM and recovery views, so the provider, worker, filter and safety semantics
remain consistent. It does not include independent transport PR #3.

## Implemented

- All 19 existing ROM provider classes remain registered; no reduced hardcoded provider list.
- TWRP, OrangeFox and explicitly named LineageOS `recovery.img` artifacts in the recovery view.
  `boot.img`, `vendor_boot.img` and `init_boot.img` are not guessed to be recovery installation methods.
- Manual validated codename or explicitly selected device/aliases, background requests, streaming
  per-provider results and isolated source failures using the existing `find_builds`/Provider parsers.
- Cooperative cancellation between requests. The current HTTP request completes/times out; it is
  not forcefully interrupted. Closing the shell is deferred while either catalog worker is active.
- Selected-device searches are invalidated on identity/selection changes; in-flight results are
  discarded. Result IDs are never reused during the controller lifetime, blocking stale selections.
- Text/project/Android/release-age filters, newest/oldest/project sorting, virtualized ListView cards,
  scrollable details, optional filter expansion on smaller windows and expandable provider errors.
- Published filenames, versions, dates, variants, notes, related artifacts and valid publisher checksum
  metadata. No downloaded file is described as verified. Missing metadata stays unknown.
- Existing ended-project and own-installer notes are preserved. Release age is separate from project
  maintenance; official/community status is explicitly not separately recorded by the current backend.
- Only selected-record HTTPS source/instruction/project links can open. Credentials, non-web schemes,
  control characters and literal private/local destinations are rejected. No arbitrary URL or command
  execution slot exists. DNS resolution/redirect policy remains the external browser's responsibility.
- Search start/finish events reach the existing session Activity view.

## Boundaries

No flash, unlock, partition selection or automated download primitive was added. Existing CLI and
Widgets download/GSI/install workflows remain available, with their audited limitations. Catalog
matches do not establish variant/firmware/installation compatibility. MD5/SHA1 metadata is labeled
as such, not promoted to stronger verification. TWRP checksums remain lazy in the existing download
workflow. GSI discovery still requires the existing profile-aware CLI/Widgets workflow.

## Test evidence

Linux, Python 3.12.14, PySide6 6.12.0:

```
QT_QPA_PLATFORM=offscreen QT_QUICK_BACKEND=software python -m pytest -q \
  --cov=curseofdroid --cov-report=term --cov-report=json:coverage.json --cov-fail-under=65
142 passed in 5.05s; 1997/2901 covered statements = 68.84%
```

The 32 new parameterized cases use real provider parsers with controlled HTTP responses, not real
USB. They cover all provider registrations, source failure isolation, recovery roles, filters, future
and missing dates, invalid codenames/links, browser routing, streaming, cancellation, device changes,
stale result IDs, worker shutdown deferral, QML search/details/error expansion and both themes/sizes.
No test performs destructive commands. The wheel includes the new Python/QML assets. The source and
frozen Linux GUI smoke render passed with no QML output; CLI help/version and compile/diff checks
also passed. Reusing prior local PyInstaller output encountered a symlink collision; a clean isolated
GUI build succeeded. Native release archives remain unverified. See the PR for CI status.

## Real screenshot provenance

`docs/screenshots/catalog/` contains actual Qt Quick captures at 1260×900 and 920×680 in both themes.
They use the production registry and parsers, not test providers or fabricated builds. ROM query:
`oriole`; recovery query: `lavender`. No physical device is attached.

The development proxy's CA is accepted by the environment's TLS-verified curl, while the app's current
certifi-only context rejects that chain. Exact public publisher responses were downloaded with curl
**without disabling TLS verification**, placed in an isolated normal `fetch_text` cache, then consumed
by the actual application. The source URLs, sizes and SHA-256 payload digests are in
`source-provenance.json`. Responses are unmodified. Remaining source errors stay visible; results are
marked partial. This demonstrates cached discovery, not successful live access to every provider.

```sh
QT_QPA_PLATFORM=offscreen QT_QUICK_BACKEND=software python -m curseofdroid.gui.capture \
  --pages roms --catalog-query oriole --output docs/screenshots/catalog/roms
QT_QPA_PLATFORM=offscreen QT_QUICK_BACKEND=software python -m curseofdroid.gui.capture \
  --pages recovery --catalog-query lavender --output docs/screenshots/catalog/recovery
```

## Follow-ups

Publisher metadata needs dedicated official/community, device maintenance and firmware/method fields;
those filters cannot be implemented honestly from the current Build model. Persistent discovery cache
management, profile-aware QML GSI UI, translated messages, checksum fetching/download queues and
verified installation manifests remain separate stages. The audit's P0 flash findings remain open.

## Qt CI lifecycle

One initial Windows/Python 3.10 push job terminated with a native Qt access violation; the corresponding
PR matrix subsequently passed. It is not treated as a proven product fix or ignored as a green rerun.
GUI tests now share a session-scoped QApplication held across module boundaries, with explicit worker
and deferred-delete cleanup, rather than allowing separate module fixtures to release/recreate it.
The final head must be checked on the full native CI matrix.

A later Windows job also showed the native access violation, so session lifetime alone is insufficient.
Dashboard now has application ownership by default; Catalog has dashboard ownership by default.
This keeps asynchronous QObject result receivers alive across Python reference/GC boundaries. A GC
regression test drops the caller reference during an in-flight request and verifies queued completion.
CI uses verbose test names to identify any further native failure instead of suppressing it.
