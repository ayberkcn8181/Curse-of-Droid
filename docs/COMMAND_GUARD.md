# Plan command boundary

The executor accepts complete argument vectors from known plan builders. It checks every command before
the first step and checks each resolved command again before transport execution. Unknown commands,
unrecognized options, extra operands, empty tokens and control characters cause refusal. A refusal from
the final check is reported as a normal StepFailed error, so UI callers can display it.

## Supported grammar

| Tool | Commands |
| --- | --- |
| ADB | reboot with no target or bootloader/recovery/fastboot; sideload with exactly one host filename; devices with optional -l; get-state; get-serialno |
| fastboot reads / transitions | devices with optional -l; getvar with one variable name; reboot with no target or bootloader/recovery/fastboot; reboot-bootloader; reboot-recovery; reboot-fastboot; continue |
| fastboot image operations | boot with one host filename; flash with one allowlisted partition and one host filename |
| fastboot data / slots | erase or format (optionally :ext4 or :f2fs) for userdata/metadata/cache only; -w without operands; set_active or --set-active with a or b |
| fastboot vendor flow | Exact flashing unlock/get_unlock_ability and oem unlock/get_unlock_data/device-info commands, only with the existing explicit unlock context |

The only supported leading fastboot modifiers are --slot (a/b/all) and --skip-reboot on supported
partition writes. Duplicate modifiers and arbitrary flags are rejected. One leading device selector
is supported: -s with a bounded serial, or ADB-only -t with a positive transport ID. Repeated selectors
are rejected. No argument is silently dropped.

Every ADB shell/exec operation is refused in installation plans, including raw dd/mkfs operations that
previously passed the narrow blocklist. No current ROM/GSI or automated vendor plan needs a shell command.
Read-only device discovery retains its separate transport probes. Adding a future shell-based feature
requires a separately reviewed operation rather than a generic shell escape hatch.

fastboot boot/reboot/getvar/slot/vendor commands cannot carry another command as an unchecked tail.
Unknown format variants, flash:raw, batch update/flashall, firmware partition writes, arbitrary vendor
commands, EDL/download reboot targets, verified-boot disable flags and relock/critical-lock operations
are refused. Existing partition and fastbootd/legacy logical-partition rules still apply.

Motorola's {answer} token is accepted only during preflight of a step with a question and an explicit
unlock context. Before execution it must resolve to one bounded ASCII code; option-like codes, injected
shell text and unresolved tokens are refused. Host image/package paths are single argv elements, so
spaces and Windows path separators do not require shell parsing. Leading-dash/blank filenames are refused.

## Regression coverage and validation

tests/test_guard_allowlist.py covers the former ADB fall-through, fastboot extra-command/option paths,
malformed selectors and tokens, supported Windows/POSIX filenames, current automated vendor plans and
Motorola substitution. Executor tests use only an injected runner: an invalid later step must reject the
whole plan before even the earlier reboot reaches that runner. Another test changes a previously valid
command during confirmation and verifies refusal immediately before transport.

Existing recovery-sideload, dynamic GSI/fastbootd, legacy GSI, partition and vendor tests remain enabled.
The existing CI matrix runs the full suite on Linux, Windows and macOS, with Python 3.10 and 3.13.
Executed commit-specific results and CI links are recorded in the PR. The local execution environment
was unavailable for this stage; no local run, coverage measurement or physical-device execution is claimed.

## Remaining installation work

This boundary constrains syntax; it does not establish artifact trust or device compatibility. Image
existence/content, trusted verification manifests, unknown bootloader/Treble/ABI/layout refusal, fresh
device/slot/partition revalidation, immutable serial binding and hardened consent/operation context still
need independent implementation and review. The QML installation wizard remains deferred until that
work is ready. This change does not enable a new QML flashing primitive or claim hardware validation.
