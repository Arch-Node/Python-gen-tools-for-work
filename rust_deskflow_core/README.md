# Rust Deskflow Core

Experimental Rust protocol and transport work for a personal Deskflow fork.
This is a framing/handshake library with in-memory session, policy, and diagnostic
models, not a live gateway.

See [Process Flow And Working Plan](process_flow.md) for the draft architecture,
message flow, milestones, and open decisions to refine as development progresses.
See [Test Plan And Stubs](tests/README.md) for Cargo commands and coverage status:
fifty-six tests pass, while three planned tests remain explicitly ignored.

## Current Implementation

The dependency-free [Cargo library](Cargo.toml) exposes `framing::decode_frame`.
It reads a four-byte big-endian payload length, enforces the caller's size limit,
and returns borrowed payload/remainder slices. Incomplete input returns `Ok(None)`;
the caller retains the bytes and retries with the accumulated slice.
At stream closure, `framing::decode_frame_at_eof` returns complete frames,
accepts empty input as a clean end, and reports truncated headers or payloads.
Drain complete frames by repeatedly passing the returned remainder before
handling a clean end or error.
`framing::encode_frame` allocates a frame with the same big-endian prefix and
preserves payload bytes. It rejects empty payloads, lengths outside the 32-bit
wire format, and payloads above the caller's limit. Both decoders reject a
zero-length prefix as `EmptyPayload`; this explicit prototype policy differs
from upstream's ambiguous empty-envelope handling. Empty input without a prefix
still means "need more bytes" or clean EOF. There is no general message parser.

The [transport module](src/transport.rs) adds a bounded `FrameBuffer` for
fragmented/coalesced TCP reads and `forward_session` for two already-connected
loopback streams. `LoopbackForwarder` binds two explicitly loopback-only
listeners and accepts one peer on each per run, creating a fresh `Session` for
each generation. Cancellable APIs stop accept waits and active forwarding,
close both streams, and return a distinct cancellation error. Once Ready, the
bridge times out after three missed 3-second keepalive intervals (9 seconds
without a complete message), matching the pinned Deskflow heartbeat alarm. It
forwards `CALV` frames but does not synthesize keepalive traffic itself.
Local safeguards also limit pairing to 30 seconds total across both accepts,
the handshake to 30 seconds after both peers connect, and each incomplete frame
to 10 seconds from its first byte. These are configurable local defaults, not
Deskflow protocol requirements; each timeout returns a distinct error and
closes the session with a typed diagnostic reason.
The bridge validates each complete payload through `Session`, preserves frame
order, and handles partial writes. It does not initiate outbound connections
or retry automatically.

The [handshake module](src/handshake.rs) parses complete server/client greeting
payloads for the `Barrier` and `Synergy` identifiers, with a 1024-byte limit and
borrowed client-name bytes. Separate pure functions reproduce the pinned
client/server version checks. Names are not decoded as UTF-8 or treated as an
authenticated identity. Parsing and version acceptance do not establish session
readiness, authorize a peer, or implement that version's later message formats.
Offline compatibility coverage now includes exact upstream-documented hello
and DINF wire examples plus source-defined startup, keyboard, pointer,
screen-transition, and chunked clipboard messages. It checks fixed bytes through
the parser and in-memory session, and checks malformed fixed-width input closes
the session. This is a small protocol-1.8 fixture set, not proof of broad or
live Deskflow interoperability.

The [session model](src/session.rs) adds a deliberately restricted protocol-1.8
startup sequence, matching protocol identifiers, pre-ready input gating, and
bounded FIFO output queues. It rejects stale generation-tagged operations,
clears both logical endpoint states on failure, and requires a fresh handshake
after restart. It also buffers typed lifecycle, protocol, policy, and rejection
events plus ten-second aggregate input summaries for the caller to drain with
`take_diagnostics`; the caller owns formatting and sink errors. Unknown/malformed
messages cause closure. Logical readiness/closure is not authentication, actual
socket delivery, or physical held-key/button cleanup.

The [clipboard module](src/clipboard.rs) and session model now enforce local
endpoint-relative send/receive permissions, denied by default. Allowed ownership
and chunks retain their bytes/order; denied transfers are consumed without
queueing content. Local permissions survive restart and cannot be relaxed by
remote options. Revocation purges unsent clipboard frames, or closes the model
if a transfer start has already been drained. See the [test guide](tests/README.md)
for strict parsing rules, cutover semantics, and unverified live-peer behavior.

The [diagnostics module](src/diagnostics.rs) provides enum-only event metadata,
a testable in-memory recorder, a writer-backed text logger, and deterministic
keyboard/pointer outcome summaries. Its logger accepts only fixed diagnostic
types and propagates writer errors; it cannot accept arbitrary strings,
payloads, key values, modifiers, or per-key times. Session diagnostics are
buffered up to 5,000 records. If the cap is reached, oldest records are dropped
and `take_diagnostics` reports the drop count. No durable storage or retention
is implemented. Summary counts and their monotonic interval continue across a
generation restart.

```bash
cargo test --offline
```

The current WSL installation requires the musl/linker command documented in the
[test guide](tests/README.md). The loopback bridge has synthetic socket tests,
but real Deskflow interoperability, Bluetooth connections, desktop input
capture, durable logging, and live clipboard enforcement have not been tested
or implemented.

## Initial Scope

- Parse a pinned Deskflow protocol version with bounded message framing.
- Test compatibility offline using synthetic input and clipboard messages.
- Add directional clipboard restrictions independently of transport.
- Explore Bluetooth transport after ordinary forwarding works reliably.
- Record diagnostic events without logging keystrokes or clipboard contents.

Keep OS input capture/injection and desktop integration in Deskflow initially.
This prototype is not a data diode or a proven sensitive-data boundary.

## AI Assistance Declaration

GitHub Copilot has assisted with design discussions, documentation research,
documentation, Cargo setup, the Rust framing/handshake/session/clipboard/diagnostics code, and tests. The first framing test
was observed failing before the decoder was implemented, then passing afterward.
The EOF truncation test also failed before its implementation and passed afterward.
The encoder and empty-frame tests also failed before implementation, then passed.
The three handshake tests likewise failed before implementation and passed afterward.
The four original session tests failed before implementation and passed afterward;
three additional session-boundary tests also pass.
The seven clipboard policy stubs failed before implementation and passed afterward;
three additional clipboard-boundary tests also pass.
The two deterministic summary tests failed before tracker implementation and
passed afterward; the typed event-schema tests passed with their first implementation.
Two tests now exercise writer-backed diagnostic formatting, verbosity filtering,
sink-error propagation, and encoded-payload exclusion. Three session tests cover
redacted lifecycle/policy events, failures/restart, and aggregate input
summaries. A fourth session test verifies the 5,000-record diagnostics cap and
drop reporting. Forty-four tests pass; the other four tests remain ignored
placeholders.
The license texts were copied from
Deskflow and verified against upstream; they were not authored by AI.

AI-assisted output may contain errors and is not evidence of compatibility,
correctness, or security. Maintainers remain responsible for reviewing,
understanding, and testing changes before use or distribution. Update this
declaration as implementation and testing progress, and disclose AI assistance
in future contributions according to the receiving project's rules.

## License

This subproject is licensed under **GPL-2.0-only WITH
LicenseRef-OpenSSL-Exception**, matching Deskflow's core licensing.
See [LICENSE](LICENSE) and [LICENSE-OpenSSL-exception](LICENSE-OpenSSL-exception).

The license texts are copied verbatim from Deskflow's
`LICENSES/GPL-2.0-only.txt` and `LICENSES/LicenseRef-OpenSSL-Exception.txt` at
commit `c1b19244a37bd238038ea2bf0ab56d9efc2de5d7`.
This declaration applies to `rust_deskflow_core`, not the rest of this repository.
Retain applicable upstream notices when incorporating code; third-party
dependencies retain their own licenses.

## Deskflow Documentation

- [Project repository](https://github.com/deskflow/deskflow) - Source code, releases, and project overview.
- [Documentation wiki](https://github.com/deskflow/deskflow/wiki) - Entry point for user and developer guides.
- [Protocol guide](https://github.com/deskflow/deskflow/wiki/Protocol) - Starting point for a compatible protocol implementation.
- [Protocol message definitions](https://github.com/deskflow/deskflow/blob/master/src/lib/deskflow/ProtocolTypes.h) - Message formats, version constants, and clipboard/input structures.
- [Generated developer documentation](https://deskflow.github.io/deskflow/) - API reference generated from source comments.
- [Build guide](https://github.com/deskflow/deskflow/wiki/Building) - Development environment and compilation instructions.
- [Unit testing](https://github.com/deskflow/deskflow/wiki/Unit-Testing) - Existing test framework and conventions.
- [Test tools](https://github.com/deskflow/deskflow/wiki/Test-Tools) - Tools for checking input behavior.
- [Command line](https://github.com/deskflow/deskflow/wiki/Command-Line) - Running Deskflow without its GUI.
- [Server configuration](https://github.com/deskflow/deskflow/wiki/Server-Text-Config) - Text-based configuration reference.
- [Contribution guidelines](https://github.com/deskflow/deskflow/wiki/Contributing) - Current contribution and AI-disclosure rules.
- [Code style](https://github.com/deskflow/deskflow/wiki/Code-Style) - Upstream source conventions.
- [Relationship with Synergy](https://github.com/deskflow/deskflow/wiki/Relationship-with-Synergy) - Upstream/downstream relationship and licensing overview.

These links follow the live project. Before implementing compatibility, pin a
specific Deskflow commit and use that revision's source as the reference; current
documentation does not establish compatibility with every Deskflow or Synergy
release. Upstream's contribution rules also apply to any future public submission;
these private AI-assisted notes are not an issue or PR description.