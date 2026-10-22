# Fresh device and partition preflight

This stage adds mandatory read-only observations to **bound installation plans**. It builds on the
[artifact preflight](INSTALL_PREFLIGHT.md). It does not enable QML device execution. The subsequent
[QML installation preview](QML_INSTALL_PREVIEW.md) can review these plans and blockers without running them. The QML
Dashboard, theme persistence, catalog and download manager remain on their separate UI branches.

## Before each operation

- Capture the serial, codenames, A/B layout, active slot and dynamic/legacy layout by value when planning.
  ROM plans now require a known A/B layout and, for A/B, a known active slot too.
- Re-hash the captured artifact after consent, then list both transports without a selector. Require one
  unambiguous entry for the captured serial; direct every subsequent probe to that exact serial.
  Other attached devices cannot substitute for the selected one. Duplicate entries or simultaneous ADB
  and fastboot entries for that serial stop execution.
- In Android/recovery, read a fresh full `getprop`. Require matching reported serial(s), a matching
  codename, explicit unlocked properties without conflicting lock flags, matching A/B/slot and captured
  dynamic layout. SDK presence alone cannot authorize an A-only layout; an explicit negative A/B
  property is also required. Some A-only GSIs report A/B system properties: these require device rules,
  rather than weakening the gate.
- In fastboot, require fresh `serialno`, `product`, `unlocked`, `slot-count` and, for A/B, `current-slot`.
  Query `is-userspace` to distinguish bootloader fastboot from fastbootd; listing labels and a plan's
  `fastbootd=True` do not authorize a logical write.
- For flash/erase/format, query `has-slot:<base>`, `is-logical:<resolved>` and
  `partition-size:<resolved>`. Resolve slotted writes to the captured slot, e.g. `system_a`; never let
  fastboot silently choose a newly active slot. Reject conflicting explicit suffixes. Logical writes
  require actual fastbootd and the captured dynamic layout. Legacy system writes require a reported
  physical partition. Missing/unsupported variables stop execution, including on older bootloaders.
- Compare raw image bytes or structurally validated Android sparse **expanded** bytes with the current
  partition capacity. Temporary `fastboot boot` requires bootloader mode, a non-sparse image and a
  fresh `max-download-size` large enough for the file. This is sizing, not boot-header/ABI validation.
- Re-read partition layout/capacity (or download limit), then critical identity/unlock/slot and mode.
  Check host file identity again after these probes. The authorization is not reused for later commands
  or after mode transitions. Manual installation instructions also require a fresh identity after consent.

Probe failures, timeouts, unknown states, duplicates, malformed sizes, oversized output and inconsistent
snapshots stop with a concise error, without copying raw probe diagnostics. Each probe has a 10-second
transport timeout and an accepted-output bound of 1 MiB (the subprocess runner still captures output
before that bound is checked). A missing device may be polled during a mode wait; a failed probe stops
immediately. Every write/wipe needs a bound target and its matching `system-write`/`data-loss` consent
class. Selectors/options cannot hide a wipe from that risk check.

## Deliberately blocked execution paths

The whole plan is checked before any reboot, manual wipe or transfer. CLI dry runs still verify hashes
and print reviewable plans with the blocking reason; they return success for a valid offline preview.
Normal CLI installation stops before the Start prompt. Widgets preview shows the reason and disables
Install; direct invocation of its action checks the policy too.

- **Automatic ADB sideload:** standard recovery minadbd does not expose ordinary shell/getprop in
  sideload mode. A cached pre-transition profile does not prove the current recipient's identity.
  ROM/add-on plans containing sideload therefore remain previewable but cannot execute any step.
  A reviewed recovery identity protocol or separately designed manual handoff is still needed.
- **Aggregate `fastboot -w`:** AOSP fastboot can implicitly erase/format userdata, cache and metadata.
  Checking only userdata would misstate its effects. Plans containing this option stop before starting.
  The current default GSI wipe plan is consequently preview-only. `--keep-data` omits it, but must only
  be used when independently reviewed device/ROM instructions permit retaining data; it is not a
  substitute for a required format-data step. A device-specific wipe workflow is still needed.
- Bound installation plans cannot add fastboot modifiers, change active slots, continue boot or invoke
  vendor/unlock commands. Separate legacy official vendor unlock plans retain their existing command
  guard and consent flow; this stage does not claim to give them fresh installation authorization.

## Sparse sizing

The parser follows the Android sparse v1.0 header and RAW/FILL/DONT_CARE/CRC32 chunk accounting.
It validates header/chunk bounds, block counts, payload lengths and exact EOF. It limits header lengths,
block size, chunk count and expanded size, uses seeks, and never allocates expanded image data. It does
not verify sparse CRC values, filesystem contents, CPU ABI, boot headers, signatures or device support.
A sparse image's downloaded file length must still match its separate SHA-256 sidecar reference.

## Validation and limits

Tests use real temporary host files and injected ADB/fastboot responses. They cover successful explicit
slot writes, legacy physical system writes, temporary boot, Android → bootloader → fastbootd → Android
transitions, sparse extents and malformed chunks, stale/changed identities, capacity changes, consent
mutation, transport failures, file edits during probes, selectors, blocked paths and UI/CLI messaging.
They do not run a real phone write, wipe, unlock or reboot. Executed counts and native CI are in the PR.

Reported identity is not cryptographic hardware attestation and cannot detect serial/codename spoofing.
Several sequential observations cannot form an atomic device transaction. State may change after the
last probe; a file may change after the final identity check and before fastboot opens it. Private staging,
publisher-authenticated metadata/receipts, real image ABI/filesystem inspection, device-specific partition
and recovery rules, snapshot/merge-state checks, cancellable hashing, operation-specific consent and
hardware validation remain before a supported QML installation flow is enabled. Partition capacity does
not establish AVB compatibility or bootability; the app does not issue explicit
partition-resize commands. Platform-tools may implement additional internal work for a flash operation;
version-specific behavior still needs review before a supported installation flow.

Protocol references:

- [AOSP fastboot protocol](https://android.googlesource.com/platform/system/core/+/refs/heads/main/fastboot/README.md)
- [Android fastbootd requirements](https://source.android.com/docs/core/architecture/bootloader/fastbootd)
- [AOSP sparse format](https://android.googlesource.com/platform/system/core/+/f0dd09c8898a94d58bf4ad950202e6cc21f1604c/libsparse/sparse_format.h)
- [Recovery minadbd services](https://android.googlesource.com/platform/bootable/recovery/+/98244a3368bde75b4c62486529aedc01fa4adfed/minadbd/minadbd_services.cpp)
- [AOSP aggregate wipe implementation](https://android.googlesource.com/platform/system/core/+/683f225ad4c259d0fe63d583e051840b12039d00/fastboot/fastboot.cpp)
