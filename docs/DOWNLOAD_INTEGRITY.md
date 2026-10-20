# Download integrity and resume

This change uses the existing `platform.net.download` API for CLI, Widgets and subsequent QML work.
It does not authorize installation or certify device compatibility.

- Only HTTPS file URLs are downloaded; HTTPS redirects cannot downgrade to HTTP. Certificate and
  hostname verification stay enabled. certifi is supplemented with host-trusted roots, so frozen
  portability and administrators' system CA configuration can coexist.
- A partial resumes only with matching URL, expected size/checksums, header fingerprint, final URL
  and a strong ETag. `Range` + `If-Range` requests must receive the exact suffix in `Content-Range`.
  Weak/missing validators, old sidecar-less partials and changed metadata restart from zero.
  A server's 200 response replaces the partial; 416 triggers one fresh request, never promotion alone.
- Content length/range, expected size and disk space are checked. Encoded, truncated, overlong and
  invalid-range responses cannot replace the final file. Available hashes are streamed in one pass.
  Failed hash checks invalidate resume metadata. The final file is replaced only after all checks.
- Cancellation is cooperative before requests, between 1 MiB reads and during hashing. Partial bytes
  remain available. A blocked network read can take up to the 60-second timeout. No general automatic
  retry is added; callers can explicitly retry using the retained partial.
- Publisher filenames and codenames are checked as portable path components in CLI/Widgets. Symlink
  targets and escaping paths are rejected. A hostile local process racing filesystem operations is
  outside this boundary; these checks are not an OS sandbox.
- CLI/Widgets distinguish SHA-256/SHA-512 checksum matching, weak legacy checksum matching, size-only
  checks and absent checks. A checksum match is not a verified publisher signature. Unpacked images
  are not mislabeled with the checksum of their compressed download. Legacy Qt progress uses percent
  values to avoid 32-bit overflow on multi-GiB artifacts.

## Executed validation

Linux, Python 3.12.14, PySide6 6.12.0: **181 passed in 6.75s**, statement coverage
**2247/3035 = 74.04%** (`pytest -q --cov=curseofdroid --cov-report=term --cov-fail-under=65`).
New cases exercise malformed ranges, changed ETags/resources/metadata, no validators, 200/416 restart,
truncation/overrun/hash failure, disk budget, cancellation, hostile filenames, downgrade refusal and
accurate CLI/Widgets messages. The loopback HTTPS server exercises real TLS cancellation/resume with
SHA-256 and proves that an untrusted certificate is rejected. Each test generates an ephemeral localhost key/certificate in a temporary directory; no key material
is committed or published. The test-only `cryptography>=43` dependency supplies key/certificate creation
(dual Apache-2.0/BSD-3-Clause). Installed transitive dev packages are cffi (MIT-0) and pycparser
(BSD-3-Clause), compatible with this GPL-3.0-or-later project. Runtime requirements are unchanged.
The fixture follows the [upstream X.509 API](https://cryptography.io/en/stable/x509/tutorial/).

The revised verified TLS context fetched the real LineageOS oriole device API (HTTP 200, 283 bytes) and
TWRP lavender index (HTTP 200, 13,719 bytes) in this environment. No TLS verification was disabled and no
phone was attached. These metadata requests do not certify every provider or a release archive.

## Remaining work

QML queue/persistence is a separate PR. Publisher signatures, trusted installation manifests, pinned
tool bootstrap hashes, automatic bounded backoff and archive/decompression budgets remain open.
The pre-existing P0 flash/executor/guard findings are unchanged.
