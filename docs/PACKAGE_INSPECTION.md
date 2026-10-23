# Bounded ROM ZIP inspection

ROM/add-on metadata inspection now uses a bounded ZIP reader before constructing Python's `ZipFile`.
This is shared by CLI, Widgets and the QML installation preview. It does not extract any entry, execute an
installer, decompress a payload/image, authenticate the publisher or enable installation.

## Resource policy

| Resource | Limit |
| --- | --- |
| Central directory | 8 MiB |
| Directory entries | 50,000, checked against the actual directory records |
| Encoded entry name | 4096 bytes; decoded names are also capped at 4096 characters |
| Supported text entries | Android metadata and legacy updater-script, at most two |
| Expanded text per entry | 512 KiB |
| Compressed text per entry | 1 MiB |
| Host read per call | At most 8 MiB, including reads requested by `ZipFile` |
| Cumulative returned host bytes | 32 MiB for one inspection |
| Metadata input/output chunk | At most 64 KiB |
| Embedded device names | At most 32 ASCII device identifiers, at most 128 characters each |

These are application admission limits, not a claim about a ZIP file's authenticity or an exact process
memory/CPU quota. They do not cap the whole ROM's physical/logical file size: ZIP64 directory offsets can
exceed 4 GiB and the reader seeks past payload bytes. A large archive with small metadata can remain
inspectable. An archive exceeding the directory/text policy remains unsupported even if independently
known to be legitimate; the program does not raise limits automatically.

The file is opened once as a regular host file. Descriptor identity is checked around reads and directory
scanning; path-to-handle checks use the existing Windows-compatible identity comparison. The result captures
the descriptor identity. The planner requires the ROM/add-on artifact reference to capture that same identity,
so metadata from an earlier file cannot silently bind to a replacement with a newly supplied sidecar.
Full SHA-256 validation is still required separately.

## Accepted subset and consistency checks

The inspector accepts ordinary single-disk ZIP directories and standard fixed-size ZIP64 end records,
including bounded archive comments, local ZIP64 size fields and streaming data-descriptor writers. It checks
end-record/directory offsets, actual record counts and variable field bounds before `ZipFile` allocates the
member list. The guarded file wrapper continues limiting reads during the library constructor, so changing
an end record after the initial budget check cannot authorize an unbounded read.

Self-extracting/prefixed archives, multi-disk or extensible ZIP64 end records, trailing archive bytes and
ambiguous end records are not supported. Ordinary non-ZIP input is classified as unknown. ZIP comments
containing an embedded end-record signature may be refused rather than interpreting a different directory
from the Python ZIP reader. Unknown raw `.img` contents keep the existing image classification; this API
does not inspect their filesystem or ABI.

All directory names must be canonical: no traversal/dot/empty components, absolute or backslash/drive paths,
control/NUL aliases or duplicate names/local headers. Encrypted entries are refused. Critical markers/text
cannot be case aliases, directories, symlinks or special files. This prevents ambiguous package classification;
it is not an extraction path sanitizer or a claim that every noncritical payload entry was validated.

Only stored or raw-deflate text metadata with supported flags is decoded; patched, enhanced-deflate
and reserved metadata flags are refused. Local metadata headers/names/flags/methods and,
when present without data descriptors, size/CRC fields must agree with the directory. Metadata cannot
cross another listed local header or the directory. The decoder consumes the complete bounded compressed
stream, requires its end marker with no trailing compressed data, checks actual output length and CRC,
and decodes UTF-8 strictly. Forging a small declared size and a CRC for just that prefix cannot hide more
expanded output. Deflate calls always have a positive output limit; zero never means unlimited output.

Duplicate or malformed `pre-device` declarations are refused. The legacy script pattern remains only a
bounded fallback for reported targets: the code does not interpret the script's execution logic. A payload or
update-binary marker and matching declared targets do not prove that the ROM is safe or compatible.
The whole payload, installer binary, data descriptors and archive signatures are not validated by inspection.

## Cancellation and error handling

`inspect(path, cancelled=callback)` checks cancellation before opening and around reads, bounded metadata
decoding and directory scanning. QML passes its existing cancellation event for both ROM and add-on input.
Cancelling during this phase stops before hash validation and discards the preview through its existing
request-generation policy. An already blocked OS read/stat and the bounded `ZipFile` directory constructor
cannot be forcibly interrupted by this callback.

`PackageError` is an `ArtifactError`: the CLI returns a readable planning error before any start prompt.
Widgets now catches inspection errors inside plan creation, clears the old plan and keeps Install disabled.
The classic Widgets preview handler remains synchronous; QML performs inspection in its existing worker.
No validation verdict is persisted or promoted into execution authorization.

## Validation and remaining limits

Tests use real temporary ZIP bytes, standard stored/deflated ZIPs, ZIP64 end/local records, streaming writers,
malformed offsets/counts/headers, compression bombs, forged smaller sizes/CRCs, duplicates/aliases, local
file changes, reader budgets and cancellation. A virtual sparse byte source checks directory offsets above
4 GiB without allocating a physical 4-GiB file on Windows. CLI and actual Qt/QML worker regressions cover
error display, stale-plan clearing and cancellation during metadata before hashing. Executed counts and
native CI are in the PR. No device write, wipe, unlock, reboot or sideload is performed.

Publisher-authenticated metadata/download receipts, archive signatures and full payload validation, actual
image ABI/filesystem/boot inspection, device-specific wipe/recovery/snapshot rules, private staging and
hardware validation remain. The final identity-check-to-tool-open race is not closed. GSI `.xz` download
extraction is a separate path; these ZIP metadata limits do not apply to every decompression operation.

Format/API references:

- [PKWARE ZIP APPNOTE, directory/end-record and local-header structures](https://pkware.cachefly.net/webdocs/casestudies/APPNOTE.TXT)
- [Python 3.13 zipfile documentation and resource limitations](https://docs.python.org/3.13/library/zipfile.html)
