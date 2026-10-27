# Installation artifact and target preflight

Installation now requires an explicit device serial, a confirmed unlocked bootloader, a known device
codename and an individual SHA-256 reference for every ROM, recovery, add-on and GSI. Missing information
stops planning. The generic download feature remains usable for browsing/downloading artifacts that do
not meet these installation requirements.

## Reviewed sidecar format

For `rom.zip`, supply `rom.zip.manifest.json` in the same directory. For `system.img`, the reference is
`system.img.manifest.json`. Each file has its own reference; a ROM reference cannot authorize a recovery
or add-on. UTF-8 JSON is limited to 64 KiB and rejects duplicate/unknown fields, unsupported versions,
missing targets, invalid sizes and weak or malformed hashes. Symlinks and special files are refused.

The following is a schema example, not an installable reference. Replace the example fields with
independently obtained publisher metadata and reviewed device-specific installation instructions.

```json
{
  "version": 1,
  "filename": "system.img",
  "kind": "gsi",
  "size": 1234567890,
  "sha256": "REPLACE_WITH_THE_64_HEX_DIGIT_PUBLISHER_REFERENCE_FOR_THIS_RAW_IMAGE",
  "source_url": "https://publisher.example/releases/checksums.txt",
  "devices": ["REVIEWED_DEVICE_CODENAME"],
  "abi": "arm64-v8a",
  "layout": "system-as-root"
}
```

Kinds are `rom`, `recovery`, `addon`, and `gsi`. Only GSI references include `abi` and `layout`.
`size` is the exact positive byte count, not compressed download size or expanded partition capacity.
`devices` names the reviewed target device(s), even for a generic image. The source must be an HTTPS
reference without embedded credentials or fragments.

This format is **not a signed manifest or proof of publisher identity**. The URL and compatibility fields
are reviewed assertions; this change does not fetch or authenticate them. A locally calculated checksum,
MD5/SHA1, matching size, a download-history record or a saved “verified” flag cannot establish publisher
trust. Use an independent trusted reference. If no strong reference exists for the exact raw image,
installation remains blocked. Do not fill in a locally computed digest simply to bypass the check.

## Planning and execution

1. Planning reads bounded metadata and regular-file identity/size, captures immutable requirements and
   binds a copy of the target serial/codenames and slot/layout snapshot. It uses absolute file paths. It does **not** claim to have
   hashed the file; large-file hashing stays out of the Widgets plan-preview handler.
2. CLI `install --dry-run` and `gsi --install ... --dry-run` run the complete guard and SHA-256 validation
   and print the plan. They do not reboot, erase, unlock or write to a phone. Normal CLI installation also
   validates before the initial start prompt.
3. Before its first command, Executor checks the whole plan, every referenced file and its expected hash.
   A bad late artifact therefore prevents an earlier reboot too. Files without a captured requirement,
   duplicate bindings, wrong artifact roles and different/implicit executor serials are refused.
4. Immediately before each file operation, Executor checks the concrete command and re-hashes the file.
   Changes during confirmation, file replacement, size changes and same-size edits stop the operation.
   It also refuses command-level device selectors in a bound installation, including selectors added
   after initial validation. Replacing the JSON sidecar cannot replace the in-memory reference.

File identity retains the complete open-handle timestamp tuple. Path-to-handle comparisons use compatible
identity/size/mtime fields; ctime is compared within the same API, avoiding the differing Windows meanings
reported in [CPython #157671](https://github.com/python/cpython/issues/157671). SHA-256 checks remain mandatory.
Windows input handles allow concurrent readers but deny writes/deletes for the lifetime of each read;
an already open writer prevents the verified read. Unix continues using no-follow/nonblocking opens and
identity checks. Neither closes the final stream-close-to-tool-open race; private staging remains pending.

Widgets execution already runs in a worker. Failed plan creation clears the previous plan and disables
its Install action. QML Dashboard/themes/catalog/downloads retain their existing presentation; this
backend gate does not expose a QML flash/unlock primitive. A subsequent
[read-only QML installation plan page](QML_INSTALL_PREVIEW.md) uses these same planner/hash checks
without enabling device execution.

GSI admission additionally requires confirmed Treble, arm64-v8a, known dynamic/legacy and A/B layouts,
an active slot for A/B, and system-as-root for A-only. Manifest ABI/layout must agree. Unknown dynamic
layout is never interpreted as legacy. Automatic 32-bit/binder-64 installation is deferred until those
capabilities can be validated. `gsi --install` requires a raw `.img`; it no longer implicitly extracts an
unreviewed `.xz` or reuses a cached unpacked file. GSI browsing/download is unchanged. A reference for
the compressed `.xz` is not a reference for the raw `.img`.

## Validation and remaining work

Tests use actual temporary file bytes and injected transports. They cover metadata bounds/schema,
SHA-256 mismatches, file changes and replacement, target/role conflicts, preflight unknowns, exact
serial selection, dry runs and the Widgets failed-plan path. No physical device operation is validation
evidence. Executed counts, coverage and native CI links are recorded in the PR.

Fresh device identity, slot, mode and partition capacity checks are now required for bound installation
plans; see [fresh device preflight](FRESH_DEVICE_PREFLIGHT.md), including its blocked sideload and
aggregate-wipe paths. Before QML installation is enabled, remaining work includes publisher-authenticated
verification and provider/download-receipt integration; image filesystem/ABI inspection; device-specific
recovery/firmware and wipe rules; snapshot/merge-state checks; stronger
consent/operation context; and a private staging strategy to narrow the race between the final hash
check and the external tool opening the filename. Reported device identity does not detect serial spoofing and sequential probes cannot guarantee
an atomic device state. A verified digest and matching declared ABI do not prove an image can boot.

[ROM ZIP inspection](PACKAGE_INSPECTION.md) now bounds directory/text reads and decompression, supports
metadata cancellation and binds its captured file identity to ROM/add-on requirements. Shared hashing also
supports cancellable progress in QML. Full archive/image validation, other decompression paths and hardware
tests remain. Existing command/device gates are not bypassed.
