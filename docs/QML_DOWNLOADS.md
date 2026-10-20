# QML downloads

The Downloads route queues direct artifacts selected in ROM/Recovery build details. The existing
provider parsers and hardened platform.net.download service remain the source of bytes and checks.
This page does not install, unpack, choose partitions or create flash plans.

## Data and lifecycle

- Catalog stores private Build snapshots separately from public QML rows. queueSelected() resolves
  the current selection and sends a copied Build to the Python manager. QML supplies no arbitrary URL,
  destination, headers or command. Website-only results keep their publisher-page action.
- One worker processes the FIFO queue. Actual byte counters are strings in QML, avoiding Qt's 32-bit
  signal overflow. Unknown totals and hashing/checksum-fetch phases are indeterminate. The themed
  progress component respects the existing motion preference.
- TWRP's existing checksum parser runs before image transfer when necessary. SHA-256/legacy/size-only/
  absent checks stay distinct; metadata is not described as a publisher signature or compatibility proof.
- Pause, Pause all, Resume/Retry, Recheck, Open folder and Remove from history are working actions.
  Pause is cooperative and waits for an active network request (up to the backend timeout). Normal
  shell close is refused while work is active. Removing history retains final/partial files.
- History is atomically persisted to download-queue.json in application data, capped at 50 records.
  Files are under downloads/<record-id>/<codename>/<filename>. IDs and path components are validated;
  raw URLs/headers and worker tracebacks are not exposed in QML rows. Only current providers' public
  Referer headers are supported; private credentials require a future secret-storage design.
- A QLockFile permits one history writer. A second instance can inspect history but displays a
  read-only error and cannot start transfers/overwrite records; close it and reopen after the writer exits.
  Runtime releases the lock after normal shutdown. Corrupt/unsupported history is preserved, not replaced
  with an empty queue. Storage errors stay visible.
- Interrupted tasks restore paused and never start network work automatically. Restored completed files
  require Recheck; checksum/size verification runs on the actual file before counting it complete again.
  When no checksum/expected size exists, Check availability only establishes that the file is present;
  the UI still explicitly says no publisher checksum or expected size.

## Executed validation

Before the execution environment became unavailable, Linux/Python 3.12.14/PySide6 6.12.0 ran
**204 tests successfully in 9.65s**, **2497/3365 = 74.21% statement coverage**.
The 23 new cases use controlled publisher HTTP with actual file writes/shared verification. They cover
queue snapshots/deduplication, FIFO advancement, hash failure/retry, pause/restore/new-process history,
local tampering/recheck, absent integrity metadata, unsafe artifacts, corrupt history, permission errors,
concurrent instances, TWRP checksum parsing, folder routing, multi-GiB counters, responsive close deferral,
and actual QML mouse interactions in both themes/sizes. No physical phone or destructive command is used.
Wheel assets, source smoke and a fresh Linux PyInstaller GUI build/render smoke also passed locally.

The interrupted publication was recovered through GitHub from the recorded source edits and already
uploaded image blobs. Final-head native CI is reviewed separately in the PR; local results above are
historical evidence, not a claim that the recovered commit was rerun in the unavailable local environment.

## Actual publisher download and visual evidence

The application searched lavender through its production recovery providers, downloaded
twrp-3.7.0_9-0-lavender.img from TWRP using verified HTTPS, fetched the published .sha256, and
matched the **35,225,600-byte** file to:

    77a3b799e9b6748bdbb8352431166a834a547db95884885f1026dfe9167a93fe

Actual Qt Quick captures show both themes at 1260×900 and dark at 920×680. The final local capture run
reopened and rechecked the real downloaded file; no artifact bytes, providers or devices were injected.
Transient notifications expired naturally before capture. capture.json records actual controller states;
source-provenance.json records URL, time, size and expected/observed digests. The development instance
had no platform-tools/device selected. No generated mockup or TLS bypass was used.
Three image blobs were recovered and published; the fourth light 920×680 capture remained in the
unavailable local environment when transfer was interrupted.

    QT_QPA_PLATFORM=offscreen QT_QUICK_BACKEND=software python -m curseofdroid.gui.capture \
      --pages downloads --catalog-query lavender --download-project TWRP \
      --output docs/screenshots/downloads

## Remaining work

Signatures/trusted installation manifests, profile-aware QML GSI/wizard pages, disk cleanup/orphan-file
management, queue reordering/concurrency, automatic bounded retries, native desktop accessibility/GPU
validation and translations remain separate stages. Existing P0 flash/guard/executor findings remain
open. A completed download does not approve installing it on any connected device.
