# QML installation plan preview

The Installation plan page brings shared ROM/GSI planning and SHA-256 reference validation into Qt Quick.
It is a **read-only planning workflow**. It never constructs an Executor, discovers devices, runs transport
commands, reboots, erases or transfers a package. Device discovery remains the Dashboard's explicit action.

## Use the page

1. Open Installation plan from the sidebar or Dashboard. Select an identified device, or Refresh discovery.
   The page labels its device data as a snapshot, with a shortened serial. It does not claim to have run the
   fresh execution checks from [PR #9](https://github.com/ayberkcn8181/Curse-of-Droid/pull/9).
2. Choose ROM ZIP or GSI system image. ROM preview optionally accepts a temporary-boot recovery image
   and one add-on ZIP. Switching type clears previous file selections. Recovery flashing and multiple add-ons
   are not exposed here yet. GSI input must be an unpacked `.img`.
3. Each selected file needs its own adjacent `<filename>.manifest.json`; see
   [the reference format](INSTALL_PREFLIGHT.md). The page cannot generate a trusted manifest from a local
   hash and does not promote a download-history flag to installation authorization.
4. Choose whether to include data erase in the proposed steps. This is a planning option, not consent to
   erase anything. Retaining data is appropriate only when the specific ROM/device instructions permit it.
5. Verify & prepare plan reads package/reference metadata and runs the shared planner and full guard/hash
   validation in a worker. Progress counts all referenced file bytes using Python integers, including files
   larger than 2 GiB. Cancel cooperates between 1 MiB hash reads and bounded ZIP metadata reads/decoding;
   it cannot interrupt an already blocked filesystem operation or the bounded Python ZIP directory constructor.
   See [package inspection limits](PACKAGE_INSPECTION.md).
6. Review human-readable steps, explicit data-loss/system-write labels, individual file/reference details,
   and selectable plain-text commands. The success message means **SHA-256 references matched**.
   Publisher authenticity, image ABI/filesystem/boot compatibility and live device execution authorization
   have not been established.

Standard automatic sideload and aggregate `fastboot -w` blockers from the shared safety policy remain visible.
They do not prevent hash validation and offline plan review. There is no Install/Run action on this page,
including for a GSI plan that omits aggregate wipe. Installation execution requires its own later supported
workflow; this page never bypasses the CLI/Widgets gates.

## State and lifetime

- No saved verification verdict, file path selection or plan is restored at startup. Theme settings continue
  to persist through the existing theme manager.
- A changed file choice, installation type, data option, device selection, device profile, discovery state or
  disconnect immediately clears the previous files, steps and command preview. Discovery activity messages
  alone do not invalidate an unchanged device snapshot.
- Worker inputs are copied. Cancellation/input changes increment a request generation; late progress or
  success from that generation cannot publish a plan. A new check waits until the old worker finishes.
- Cancelling after hashing finishes but before its queued result arrives still discards that result.
- Window closing is deferred while verification is active. Cancel/wait before closing. No successful or
  partial plan is retained on failure/cancellation. File edits on disk after a completed preview require a
  new verification; a preview is not ongoing monitoring or authorization for a later operation.
- The shared artifact verifier and whole-plan validator accept optional progress/cancellation callbacks;
  existing execution callers retain mandatory full hashing with their default arguments.

## Evidence

Tests use actual temporary files, real SHA-256 checks and QML windows. Device profiles are controlled test
fixtures; tests forbid Executor and Tool.run calls from the preview. Coverage includes ROM/recovery/add-on
references, bad/missing manifests and hashes, GSI plans, stale inputs, worker threads, cancellation races,
large progress counts, duplicate serials, responsive GUI/deferred close, both themes and 1260×900/920×680.
Executed test counts, wheel validation and native CI results are recorded in the PR.

Actual application captures, without injected devices or synthetic success data:

| Theme | 1260 × 900 | 920 × 680 |
| --- | --- | --- |
| Dark | [Window](screenshots/install-preview/install-dark.png) | [Small window](screenshots/install-preview/install-dark-small.png) |
| Light | [Window](screenshots/install-preview/install-light.png) | [Small window](screenshots/install-preview/install-light-small.png) |

Reproduce with:

```sh
QT_QPA_PLATFORM=offscreen QT_QUICK_BACKEND=software python -m curseofdroid.gui.capture --pages install --output docs/screenshots/install-preview
```

[capture.json](screenshots/install-preview/capture.json) records Qt/Python/platform and actual backend state.
This environment has no platform-tools or connected phone; screenshots therefore show the real unselected
state. Successful preview behavior is covered with explicitly controlled file/device fixtures in tests.

## Remaining work

Publisher-authenticated metadata and download receipts, archive signatures/full-payload validation, actual image compatibility
inspection, recovery identity/manual handoff, device-specific wipe/partition/snapshot rules, private staging,
stronger execution consent and hardware validation remain. ZIP metadata now has bounded, cooperative
cancellation; not every filesystem operation or decompression path can be interrupted. File/reference matching does not establish authenticity or bootability. See
[fresh-device limits](FRESH_DEVICE_PREFLIGHT.md) before designing execution.
