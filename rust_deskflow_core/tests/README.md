# Test Plan And Stubs

[protocol_tests.rs](protocol_tests.rs) contains 62 Rust integration tests grouped
by behavior. Fourteen framing, three handshake, eleven session, ten clipboard,
six diagnostics, ten transport, and three compatibility tests exercise the Cargo
library; three remaining stubs are ignored and contain `todo!`.

The current run reports **59 passed, 3 ignored**. Executing a remaining ignored
test explicitly fails until its body is implemented. No dependencies, live
endpoints, Bluetooth adapters, or network access are required for active tests.

## Read Each Test Specification

Every test in [protocol_tests.rs](protocol_tests.rs) has four documentation lines:

- **Setup:** input bytes, local policy, fake clocks/transports, or real endpoints
   that the scenario needs.
- **Exercise:** the action or message sequence to drive, including interruption
   and retry cases where relevant.
- **Expect:** observable payloads, errors, state changes, or non-delivery outcomes
   that should become assertions.
- **Scope:** boundaries, unresolved prerequisites, or limits on what the test
   establishes. A future requirement here is not already verified coverage.

For active tests, read the assertions alongside the description.
For ignored tests, the documentation is an implementation specification: no
live-endpoint compatibility or Bluetooth behavior is implemented merely because
its expected outcome is now described. Diagnostics tests cover typed metadata,
the writer-backed text formatter, verbosity filtering, writer failures, payload
exclusion, and a deterministic in-memory summary tracker. Session tests now
verify typed lifecycle/policy events, failure/restart records, interval input
summaries, and payload-free formatted output. Transport tests cover incremental
frame buffering, size and EOF errors, a loopback TCP bridge through a synthetic
session handshake, loopback-only listener binding, repeated peer sessions,
cancellation during accept/forwarding, the nine-second idle timeout after
session establishment, and injected-timeout tests for pairing, handshake, and
incomplete frames. These local deadlines are not protocol requirements. They do
not test real-peer interoperability, Bluetooth, or production operability.
There is no durable or retained logging backend.
Two active compatibility tests check exact wire examples/message formats from
the pinned Deskflow source through framing, handshake parsing, and the
in-memory session. Fixtures now cover startup, keyboard events, pointer events,
screen transitions, clipboard chunking, and malformed message shapes. These do
not constitute a full differential compatibility suite.

Work through one scenario at a time. Resolve its open decisions, build deterministic
fixtures, replace its `todo!` with assertions against the real API, and remove
`#[ignore]`. Keep tests independent of timing and external machines unless their
description explicitly requires an opt-in integration environment. Split a broad
scenario into named cases when implementation makes that clearer; update the
inventory and counts afterward.

## Coverage Inventory

| Group | Total Tests | Intended checks |
| --- | --- | --- |
| `framing` | 14 (all active) | Big-endian length, split reads, combined frames, limits, EOF, zero-length rejection, encoding |
| `handshake` | 3 (all active) | Complete greeting payloads, role-specific versions, malformed/oversized input |
| `clipboard_policy` | 10 (all active) | Direction, chunks, local denial, continued input, queue cutover, malformed transfers, defaults, stale policy, limits |
| `diagnostics` | 6 (all active) | Enum-only event metadata, safe text formatting, verbosity and sink errors, content/key non-disclosure, deterministic interval summaries |
| `session` | 11 (all active) | In-memory closure, generation isolation, queues, readiness, direction/shape validation, redacted diagnostics, aggregate input summaries, bounded diagnostic buffering |
| `transport` | 13 (all active) | Fragmented/coalesced frames, early size rejection, EOF truncation, loopback forwarding/listeners, repeated fresh sessions, bind validation, cancellation, 9-second keepalive timeout, pair/handshake/incomplete-frame deadlines |
| `compatibility` | 3 (2 active, 1 ignored) | Pinned-source protocol-1.8 fixtures for startup/input/clipboard; explicit real-endpoint integration remains ignored |
| `bluetooth` | 2 | Frame/order preservation and fresh sessions after reconnect |

## Source Evidence And Unresolved Expectations

Initial framing evidence comes from Deskflow commit
`c1b19244a37bd238038ea2bf0ab56d9efc2de5d7`:

- [PacketStreamFilter.cpp](https://github.com/deskflow/deskflow/blob/c1b19244a37bd238038ea2bf0ab56d9efc2de5d7/src/lib/deskflow/PacketStreamFilter.cpp)
  writes a four-byte big-endian payload length. Its reader checks the declared
  size against `PROTOCOL_MAX_MESSAGE_LENGTH` before waiting for the full payload,
  and treats a partial payload at shutdown as a format error.
- [ProtocolTypes.h](https://github.com/deskflow/deskflow/blob/c1b19244a37bd238038ea2bf0ab56d9efc2de5d7/src/lib/deskflow/ProtocolTypes.h)
   supplies protocol versions, message formats, and the documented hello,
   DINF, DMDN, DKDL, DKRP, DMMV, DMRM, DMWM, CINN, COUT, CCLP, and DCLP
   examples/formats used by the compatibility fixture tests.
- [ProtocolTypes.cpp](https://github.com/deskflow/deskflow/blob/c1b19244a37bd238038ea2bf0ab56d9efc2de5d7/src/lib/deskflow/ProtocolTypes.cpp)
   supplies the message-code constants and confirms QINF, CIAK, and DSOP codes.
- [ProtocolUtil.cpp](https://github.com/deskflow/deskflow/blob/c1b19244a37bd238038ea2bf0ab56d9efc2de5d7/src/lib/deskflow/ProtocolUtil.cpp)
   establishes integer and length-prefixed string serialization used in hello
   replies and variable-length protocol fields.
- [Client.cpp](https://github.com/deskflow/deskflow/blob/c1b19244a37bd238038ea2bf0ab56d9efc2de5d7/src/lib/client/Client.cpp)
   defines client-side server-version negotiation and proxy availability.
- [ClientProxyUnknown.cpp](https://github.com/deskflow/deskflow/blob/c1b19244a37bd238038ea2bf0ab56d9efc2de5d7/src/lib/server/ClientProxyUnknown.cpp)
   defines client-reply limits and the server-side accepted-version table.
- [ProtocolTypes.h](https://github.com/deskflow/deskflow/blob/c1b19244a37bd238038ea2bf0ab56d9efc2de5d7/src/lib/deskflow/ProtocolTypes.h)
   sets `kKeepAliveRate` to 3 seconds and `kKeepAlivesUntilDeath` to three.
- [ClientProxy1_3.cpp](https://github.com/deskflow/deskflow/blob/c1b19244a37bd238038ea2bf0ab56d9efc2de5d7/src/lib/server/ClientProxy1_3.cpp)
   sends periodic keepalives and sets the three-interval heartbeat alarm.
- [ServerProxy.cpp](https://github.com/deskflow/deskflow/blob/c1b19244a37bd238038ea2bf0ab56d9efc2de5d7/src/lib/client/ServerProxy.cpp)
   echoes `CALV` and resets its keepalive alarm when messages arrive.
- [ServerProxy.cpp](https://github.com/deskflow/deskflow/blob/c1b19244a37bd238038ea2bf0ab56d9efc2de5d7/src/lib/client/ServerProxy.cpp)
   marks the client handshake complete after options, not the greeting alone.
- [ClientProxy1_0.cpp](https://github.com/deskflow/deskflow/blob/c1b19244a37bd238038ea2bf0ab56d9efc2de5d7/src/lib/server/ClientProxy1_0.cpp)
   requests client info and acknowledges valid positive display dimensions.
- [ClipboardChunk.cpp](https://github.com/deskflow/deskflow/blob/c1b19244a37bd238038ea2bf0ab56d9efc2de5d7/src/lib/deskflow/ClipboardChunk.cpp)
   defines decimal-string size declarations and start/data/end transfer behavior.
- [IClipboard.cpp](https://github.com/deskflow/deskflow/blob/c1b19244a37bd238038ea2bf0ab56d9efc2de5d7/src/lib/deskflow/IClipboard.cpp)
   defines marshalled content: format count, then format ID, byte length, and data.

The Rust compatibility baseline is still a candidate, not a completed validation.
The active fixture tests transcribe a small set of protocol examples and
formats from the pinned source; they do not prove broad compatibility or
replace differential testing against a Deskflow build. The protocol source
reference is pinned in [Cargo metadata](../Cargo.toml).
Live denial behavior, general size limits, and live-peer timeout behavior remain
unverified/unselected. The Rust transport applies the pinned 9-second idle
deadline after session readiness; handshake and separate partial-frame deadlines
are not configured.
The local policy and diagnostics requirements are not claims
about upstream behavior. No upstream C++ test bodies or implementation code have
been copied; the fixture test uses fixed wire bytes from documented upstream
examples and message definitions.

The active tests cover big-endian decoding, fragmented headers/payloads, two
coalesced frames, rejection of oversized declarations before payload arrival,
and the inclusive caller-specified size boundary. The decoder borrows slices;
tests retry with growing input slices, not an implemented internal buffer.

## Handshake Contract

The parsers take one complete greeting payload, after the framing layer removes
the packet-length prefix. They do not accept arbitrary stream fragments directly.

- A server greeting is exactly 11 bytes: `Barrier` or `Synergy` (seven bytes),
   then signed big-endian 16-bit major and minor version numbers.
- A client reply adds a four-byte big-endian name length and that many raw name
   bytes. With the 1024-byte payload limit, the maximum name is 1009 bytes.
- Names are borrowed bytes, not assumed UTF-8. A structurally empty name is
   parseable; endpoint-name validity and trust are separate, unimplemented checks.
- Nonpositive majors and negative minors are structurally invalid. Positive
   versions can parse even if the role-specific version check later rejects them.
- Errors reject oversized greetings, malformed identifiers, missing fields,
   oversized declared names, and trailing bytes. They contain metadata, not names.

Role-specific source-derived rules are intentionally asymmetric:

| Pure Check | Accepted Input | Result |
| --- | --- | --- |
| `negotiate_server_version` | Major 1, minor 6 or newer | Minor capped at 8; 1.6/1.7 retained |
| `validate_client_version` | Major 1, minor 0 through 8 | Same version returned |

The tests cover both identifiers, framed greeting plus next-frame preservation,
binary names, every truncated greeting field, negative version encodings, unknown
identifiers, trailing data, maximum name/greeting length, and both version tables.
Known-field and fixed-length checks are deliberately strict local validation;
matching all permissive behavior in upstream's generic format reader is not claimed.

These are parser and compatibility-decision tests only. In particular, the test
named `rejects_unsupported_versions_without_forwarding_input` checks rejection and
preservation of unread frame bytes, not a real forwarding gate. The session tests
below exercise in-memory gating and identifier matching. TLS and actual peer/input
authorization remain absent. Accepting 1.0 in a pure check does not mean
this Rust library implements 1.0 input/clipboard formats.

## In-Memory Session Contract

`Session::receive` takes a complete decoded payload and a local generation token;
it does not read sockets or stream fragments. This prototype only proceeds with
negotiated protocol 1.8 and matching `Barrier`/`Synergy` identifiers. A future
server minor may negotiate down to 1.8; legacy client replies are deliberately
refused by this model even when the standalone compatibility function accepts them.

The modeled startup is deliberately strict:

```text
server hello -> client reply -> QINF -> DINF -> CIAK -> [CROP] -> DSOP -> Ready
```

Readiness changes when a validated options frame is accepted into the output
queue, not when a real peer has received it. Same-destination FIFO ordering keeps
later input behind those startup frames. Upstream may allow additional control
orderings; this is not an implementation of every upstream startup sequence.

- `DINF` must have its fixed shape and positive dimensions; `DSOP` must contain
   an exact even-length list of option/value integers. Values are not applied.
- After both greetings, exact `CALV`/`CNOP` messages are permitted in either
   direction without advancing readiness. Server `CBYE` closes the model and
   clears queues rather than being queued for transmission.
- Before Ready, input is rejected. After Ready, the limited server-to-client
   subset includes `DKDL`, `DKRP`, `DKUP`, `DMDN`, `DMUP`, `DMMV`, `DMRM`, `DMWM`,
   `CINN`, and `COUT`, with exact fixed or language-field lengths checked.
- Ready-state info/options/control updates are structurally checked. Display
   changes do not yet gate pointer motion while awaiting a fresh acknowledgment.
- Clipboard ownership/chunks are supported only after Ready under the local
   contract below. File-transfer, unknown, wrong-direction input/control, and
   malformed messages close both logical endpoints and clear pending queues.

Each destination has a FIFO queue. The shared configured byte budget counts
encoded frame headers plus payloads in both queues. Exact-limit queuing succeeds;
overflow closes both logical endpoints and clears both queues, never silently
dropping a single input frame. This is not a cap on allocator overhead, temporary
input buffers, frames already drained into an adapter, or total process memory.
`take_next` removes a whole frame from the model; an eventual adapter must handle
partial writes and its own in-flight buffer correctly.

Disconnect is idempotent for the current generation. Restart requires a closed
session and a strictly greater caller-managed generation. Old receive, drain,
and disconnect operations return `StaleGeneration` before mutation. These tokens
are local lifecycle identifiers, not remote peer authentication. Snapshots contain
only state/metadata; accepted-frame counts include queued frames and validated
policy-denied clipboard frames, not actual delivery.

Tests check the original four session scenarios plus every pre-ready input stage,
early options, invalid display shape, supported input shapes with malformed tails,
both-direction queue accounting, and startup limits. They use logical endpoints,
not fake physical sockets. They do not prove physical key-release recovery, an
upstream COSMIC callback fix, application consent, peer identity, or live delivery.

## In-Memory Clipboard Contract

`Session::set_clipboard_permissions(generation, endpoint, ClipboardPermissions)`
configures local `send` and `receive` permissions. Both default to false.
A path requires the source's send permission AND destination's receive permission;
these directions do not depend on server/client role. The caller must identify
the work endpoint correctly; there is no identity/configuration system yet.

- `CCLP` is exactly nine bytes: code, clipboard ID (0 clipboard or 1 selection),
   and a big-endian `u32` sequence. It announces ownership, not content.
- `DCLP` is code, ID, sequence, one-byte mark, big-endian `u32` data length, and
   exactly that many bytes. Marks 1/2/3 mean start/data/end. Start carries an
   unsigned decimal ASCII size, not a binary integer. End has no data.
- There is one active transfer per direction, not one per clipboard ID. Data/end
   require the start's ID/sequence; total content must match its declared size.
   Orphan chunks, duplicate ends, overlapping starts, malformed lengths/IDs/marks,
   decimal overflow, or changing identity close the model even if policy denies.
- Strict digit-only size parsing, matching chunk identity, rejecting overlapping
   starts, and empty end data are local restrictions. Upstream permits some
   cases the prototype rejects; exact parser equivalence is not claimed.
- Allowed ownership and chunks retain bytes and FIFO order. Content formats are
   opaque: fixtures use marshalled text/HTML/binary-image bytes, but the library
   does not decode HTML/images or validate real OS clipboard compatibility.
- Denied ownership/chunks never enter output queues. Only bounded transfer
   metadata is retained, not cached content. A denied transfer stays denied
   through its end even if permissions become permissive halfway through.
   No acknowledgment or cancellation packets are invented; this is a model
   suppression rule, not a demonstrated live peer timeout/ownership solution.
- Revocation removes all unsent clipboard frames on newly denied paths without
   dropping unrelated queued input/control. If a start has already been returned
   by `take_next` without its end, revocation closes both ends and clears queues.
   This conservative cutoff cannot recall previously delivered or adapter-held
   bytes, remove remote cached content, or recover physically held keys.
- Disconnect discards transfer state. Restart retains local permissions, not
   old chunks. Stale-generation configuration changes fail before mutation.
   Remote `DSOP`/`CROP` cannot relax local policy; remote options are validated
   and forwarded but are not applied by this model.

All frames, including denied ones, must fit the payload limit. Allowed clipboard
frames share the existing combined encoded-byte queue budget; overflow closes
the session. The model does not buffer whole transfers, enforce a total transfer
size/time limit, or bound buffers held outside it. Independent sessions are tested,
not third-peer redistribution or cross-session content provenance. No diagnostic
sink, sockets, Bluetooth, TLS inspection, or OS clipboard access is implemented.

## Diagnostics Contract

The diagnostics module defines only fixed enums and numeric summary fields.
`Event` carries level, event kind, category, endpoint-relative direction,
outcome, and a fixed reason. It has no string or byte fields. `MemoryRecorder`
applies a minimum verbosity and stores typed records for tests. `LogRecorder`
formats those fixed events and numeric summaries to a caller-provided `Write`
sink, applies a minimum verbosity, and returns I/O errors to its caller. It
accepts no arbitrary text, payload bytes, or peer names and does not provide
rotation, retention, or durable storage.

`InputSummaryTracker` accepts only `Keyboard`/`Pointer` and `Forwarded`/`Denied`
categories. It emits fixed-interval counts using an injected `Duration` clock;
it has no API for keycodes, scan codes, modifiers, characters, payloads, or
per-event timestamps. In Session, `Forwarded` means accepted into its in-memory
output queue, not delivered to a peer. `Session::take_diagnostics(now)` drains
typed events and emits at most one due aggregate using a caller-supplied
monotonic `Duration`. The default interval is ten seconds. Restart preserves the tracker counts/deadline and undrained typed
records across a generation restart; the monotonic clock continues for the
lifetime of the Session value. The diagnostics queue is capped at 5,000
records; when full, it drops the oldest record and increments a saturating
counter. `take_diagnostics` returns that count in `DiagnosticsBatch` and resets
it, so callers can detect loss. Session code never calls the writer or formats
text, so sink errors are returned by `LogRecorder` to its caller and cannot
alter session-policy results.

Event tests cover open, negotiation, ready, policy, rejection, close, restart,
and queue overflow transitions, but this remains an in-memory model, not a
production logging pipeline. Callers should drain regularly; sustained overload
is observable as a nonzero dropped count. Crash reports, durable output, and
retention paths are not exercised; tests do not establish that unrelated
application logging or external sinks are safe.

## Encoder And Zero-Length Policy

`encode_frame` returns an allocated frame containing a four-byte big-endian
payload length followed by the unmodified payload. It checks the caller's size
limit and rejects lengths not representable as a `u32` before constructing the
output. Fixed-byte tests cover a 258-byte payload, embedded zeros/high bytes,
the exact permitted size, and a nonempty payload with a zero size limit.
The greater-than-`u32::MAX` slice case is guarded by checked conversion, but is
not exercised by allocating a multi-gigabyte test payload.

The pinned upstream writer can emit a zero-length envelope, while its reader's
ready condition requires a nonzero payload size. We do not reproduce that
ambiguous behavior: the prototype deliberately returns `EmptyPayload` for empty
encoding requests and zero-length prefixes in either decoder. Tests also verify
that an invalid empty envelope cannot be skipped to reach a following frame.
This is a stricter local policy, not a claim of exact upstream empty-frame
compatibility. It does not reject an empty input buffer without a header.

## EOF Contract

Use `decode_frame` while more bytes can arrive, then `decode_frame_at_eof` once
the byte stream has closed. Both borrow the caller's input without buffering it.

- Empty input at EOF returns `Ok(None)`, representing a clean end.
- A complete frame returns `Ok(Some(frame))`, even if its remainder is partial.
- Repeatedly decode the remainder until it is empty or produces an error.
- One to three remaining bytes produce `TruncatedHeader { received }`.
- A permitted length with too few payload bytes produces
   `TruncatedPayload { declared, received }`; `received` excludes the header.
- Oversized declarations remain `PayloadTooLarge`, even at EOF.
- A zero-length declaration remains `EmptyPayload`, even at EOF.

The errors contain counts, not input bytes. Tests check every partial-header
length, each missing-payload boundary for a four-byte example, clean EOF,
multiple complete frames followed by a partial header or payload, and size-error
precedence. Partial-header EOF rejection is an explicit Rust API contract; its
exact correspondence to upstream shutdown behavior is not yet differentially
validated.

## Run And Discover

From the project directory in a normal Rust development environment:

```bash
cargo test --offline
cargo test --offline --test protocol_tests -- --list
cargo test --offline --test protocol_tests framing::decodes_big_endian_payload_length -- --exact
cargo test --offline --test protocol_tests clipboard_policy::
```

The current standalone WSL installation has no C compiler/linker. With its
already-installed musl target and bundled Rust linker, use this instead:

```bash
export RUSTC="$HOME/.cargo/bin/rustc"
export RUSTDOC="$HOME/.cargo/bin/rustdoc"
export CARGO_TARGET_X86_64_UNKNOWN_LINUX_MUSL_LINKER="$HOME/.cargo/lib/rustlib/x86_64-unknown-linux-gnu/bin/rust-lld"
"$HOME/.cargo/bin/cargo" test --offline --target x86_64-unknown-linux-musl
```

To demonstrate that a selected placeholder is not a passing test:

```bash
cargo test --offline --test protocol_tests diagnostics::records_categories_direction_and_policy_outcome -- --ignored --exact
```

That command is expected to exit unsuccessfully with `not yet implemented`.
In the WSL setup above, add `--target x86_64-unknown-linux-musl` to the Cargo
arguments before the `--` separator. Do not use the expected placeholder failure
as a behavioral validation result. These commands do not start
Deskflow, capture typing, or open a network connection.

## Turn A Stub Into A Test

1. Resolve its expected behavior against the selected upstream source or an
   explicit local requirement, and record fixture provenance where applicable.
2. Replace `todo!` with assertions against the Rust library's
   actual public API. Do not duplicate the implementation inside the test.
3. Remove `#[ignore]` for offline tests and confirm the assertion fails before
   implementing the behavior, then passes afterward.
4. Keep hardware/live-endpoint tests explicitly opt-in with clear prerequisites.
5. Record what was tested in [the working plan](../process_flow.md); compiling
   stubs alone does not complete a milestone.

The first test was observed failing at the unimplemented decoder, then passing
after implementation. The EOF test was likewise observed failing before its
implementation, then passing. The encoder and zero-length rejection tests were
also observed failing before implementation and passing afterward. All three
handshake tests were observed failing at unimplemented APIs, then passing after
implementation. The four original session stubs likewise failed before the model
was implemented, then passed; three additional boundary tests pass. No framing,
handshake, or session stubs remain ignored. Directional clipboard policy and its
protocol transfer state are next; all clipboard traffic is currently unsupported.
Introduce independently checked fixtures before
claiming compatibility. Round-trip encode/decode tests alone are insufficient
because the encoder and decoder could share the same mistake.

These tests are now a normal Cargo integration target. The initial framing
library is not evidence of compatibility with live Deskflow or Synergy endpoints.