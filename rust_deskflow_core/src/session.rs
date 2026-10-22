use std::collections::VecDeque;
use std::time::Duration;

use crate::clipboard::{self, ClipboardKind, ClipboardPermissions, Transfer};
use crate::diagnostics::{
    Category, DiagnosticsBatch, Direction, Event, EventKind, InputKind, InputOutcome,
    InputSummaryTracker, Level, MAX_PENDING_DIAGNOSTICS, Outcome, Reason, Record,
};
use crate::framing::encode_frame;
use crate::handshake::{
    CURRENT_VERSION, ProtocolName, negotiate_server_version, parse_client_hello,
    parse_server_hello, validate_client_version,
};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Endpoint {
    Server,
    Client,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SessionState {
    AwaitServerHello,
    AwaitClientHello,
    AwaitQueryInfo,
    AwaitClientInfo,
    AwaitInfoAck,
    AwaitOptions,
    Ready,
    Closed,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SessionSnapshot {
    pub generation: u64,
    pub state: SessionState,
    pub endpoints_open: [bool; 2],
    pub queued_bytes: usize,
    pub accepted_frames: u64,
}

#[derive(Debug, PartialEq, Eq)]
pub enum SessionError {
    StaleGeneration,
    Closed,
    AlreadyOpen,
    InvalidGeneration,
    UnexpectedMessage,
    MalformedMessage,
    UnsupportedVersion,
    ProtocolMismatch,
    QueueLimit { maximum: usize },
    Handshake(crate::handshake::HandshakeError),
    Framing(crate::framing::FrameError),
}

struct QueuedFrame {
    bytes: Vec<u8>,
    clipboard: Option<ClipboardKind>,
}

pub struct Session {
    generation: u64,
    state: SessionState,
    protocol: Option<ProtocolName>,
    endpoints_open: [bool; 2],
    queues: [VecDeque<QueuedFrame>; 2],
    clipboard_permissions: [ClipboardPermissions; 2],
    clipboard_transfers: [Option<Transfer>; 2],
    clipboard_started: [bool; 2],
    queued_bytes: usize,
    accepted_frames: u64,
    maximum_payload: usize,
    maximum_queued_bytes: usize,
    diagnostics: VecDeque<Record>,
    dropped_diagnostics: u64,
    input_summaries: InputSummaryTracker,
}

impl Session {
    pub fn set_clipboard_permissions(
        &mut self,
        generation: u64,
        endpoint: Endpoint,
        permissions: ClipboardPermissions,
    ) -> Result<(), SessionError> {
        self.check_generation(generation)?;
        self.check_open()?;
        let previously_allowed = [self.clipboard_allowed(0), self.clipboard_allowed(1)];
        self.clipboard_permissions[endpoint_index(endpoint)] = permissions;
        for (source, was_allowed) in previously_allowed.into_iter().enumerate() {
            let destination = 1 - source;
            if self.clipboard_allowed(source) {
                continue;
            }
            if was_allowed {
                self.record_event(Event {
                    level: Level::Debug,
                    kind: EventKind::Message,
                    category: Category::Clipboard,
                    direction: direction_from(if source == 0 {
                        Endpoint::Server
                    } else {
                        Endpoint::Client
                    }),
                    outcome: Outcome::Denied,
                    reason: Reason::Policy,
                });
            }
            if self.clipboard_started[destination] {
                self.close_current(Reason::Policy, Direction::Local);
                return Ok(());
            }
            if let Some(transfer) = self.clipboard_transfers[source].as_mut() {
                transfer.forward = false;
            }
            self.queues[destination].retain(|frame| frame.clipboard.is_none());
        }
        self.queued_bytes = self
            .queues
            .iter()
            .flatten()
            .map(|frame| frame.bytes.len())
            .sum();
        Ok(())
    }

    pub fn new(generation: u64, maximum_payload: usize, maximum_queued_bytes: usize) -> Self {
        Self {
            generation,
            state: SessionState::AwaitServerHello,
            protocol: None,
            endpoints_open: [true, true],
            queues: [VecDeque::new(), VecDeque::new()],
            clipboard_permissions: [ClipboardPermissions::default(); 2],
            clipboard_transfers: [None; 2],
            clipboard_started: [false; 2],
            queued_bytes: 0,
            accepted_frames: 0,
            maximum_payload,
            maximum_queued_bytes,
            diagnostics: VecDeque::from([Record::Event(Event {
                level: Level::Info,
                kind: EventKind::SessionOpened,
                category: Category::Session,
                direction: Direction::Local,
                outcome: Outcome::Forwarded,
                reason: Reason::NotApplicable,
            })]),
            dropped_diagnostics: 0,
            input_summaries: InputSummaryTracker::new(Duration::from_secs(10), Duration::ZERO),
        }
    }

    pub fn snapshot(&self) -> SessionSnapshot {
        SessionSnapshot {
            generation: self.generation,
            state: self.state,
            endpoints_open: self.endpoints_open,
            queued_bytes: self.queued_bytes,
            accepted_frames: self.accepted_frames,
        }
    }

    pub(crate) fn maximum_payload(&self) -> usize {
        self.maximum_payload
    }

    pub fn receive(
        &mut self,
        generation: u64,
        from: Endpoint,
        payload: &[u8],
    ) -> Result<(), SessionError> {
        self.check_generation(generation)?;
        self.check_open()?;
        let result = self.receive_current(from, payload);
        if result.is_err() {
            let reason = if matches!(&result, Err(SessionError::QueueLimit { .. })) {
                Reason::QueueLimit
            } else {
                Reason::Malformed
            };
            if let Some(kind) = input_kind(payload) {
                self.input_summaries.record(kind, InputOutcome::Denied);
            }
            self.record_event(Event {
                level: Level::Debug,
                kind: EventKind::Message,
                category: if is_clipboard_message(payload) {
                    Category::Clipboard
                } else {
                    Category::Control
                },
                direction: direction_from(from),
                outcome: Outcome::Rejected,
                reason,
            });
            self.close_current(reason, direction_from(from));
        }
        result
    }

    pub fn take_diagnostics(&mut self, now: Duration) -> DiagnosticsBatch {
        if let Some(summary) = self.input_summaries.take_due(now) {
            self.push_diagnostic(Record::InputSummary(summary));
        }
        DiagnosticsBatch {
            records: self.diagnostics.drain(..).collect(),
            dropped_records: std::mem::take(&mut self.dropped_diagnostics),
        }
    }

    pub fn take_next(
        &mut self,
        generation: u64,
        destination: Endpoint,
    ) -> Result<Option<Vec<u8>>, SessionError> {
        self.check_generation(generation)?;
        self.check_open()?;
        let destination = endpoint_index(destination);
        let frame = self.queues[destination].pop_front();
        if let Some(frame) = frame.as_ref() {
            self.queued_bytes -= frame.bytes.len();
            match frame.clipboard {
                Some(ClipboardKind::Start) => self.clipboard_started[destination] = true,
                Some(ClipboardKind::End) => self.clipboard_started[destination] = false,
                _ => {}
            }
        }
        Ok(frame.map(|frame| frame.bytes))
    }

    pub fn disconnect(&mut self, generation: u64, from: Endpoint) -> Result<(), SessionError> {
        self.check_generation(generation)?;
        self.close_current(Reason::PeerClosed, direction_from(from));
        Ok(())
    }

    pub(crate) fn timeout(&mut self, generation: u64) -> Result<(), SessionError> {
        self.check_generation(generation)?;
        self.close_current(Reason::Timeout, Direction::Local);
        Ok(())
    }

    pub(crate) fn pair_timeout(&mut self, generation: u64) -> Result<(), SessionError> {
        self.check_generation(generation)?;
        self.close_current(Reason::PairTimeout, Direction::Local);
        Ok(())
    }

    pub(crate) fn handshake_timeout(&mut self, generation: u64) -> Result<(), SessionError> {
        self.check_generation(generation)?;
        self.close_current(Reason::HandshakeTimeout, Direction::Local);
        Ok(())
    }

    pub(crate) fn incomplete_frame_timeout(&mut self, generation: u64) -> Result<(), SessionError> {
        self.check_generation(generation)?;
        self.close_current(Reason::IncompleteFrameTimeout, Direction::Local);
        Ok(())
    }

    pub(crate) fn cancel(&mut self, generation: u64) -> Result<(), SessionError> {
        self.check_generation(generation)?;
        self.close_current(Reason::Cancelled, Direction::Local);
        Ok(())
    }

    pub fn restart(&mut self, generation: u64) -> Result<(), SessionError> {
        if self.state != SessionState::Closed {
            return Err(SessionError::AlreadyOpen);
        }
        if generation <= self.generation {
            return Err(SessionError::InvalidGeneration);
        }
        let permissions = self.clipboard_permissions;
        let pending_diagnostics = std::mem::take(&mut self.diagnostics);
        let dropped_diagnostics = std::mem::take(&mut self.dropped_diagnostics);
        let input_summaries = std::mem::replace(
            &mut self.input_summaries,
            InputSummaryTracker::new(Duration::from_secs(10), Duration::ZERO),
        );
        let mut replacement =
            Self::new(generation, self.maximum_payload, self.maximum_queued_bytes);
        replacement.diagnostics = pending_diagnostics;
        replacement.dropped_diagnostics = dropped_diagnostics;
        replacement.record_event(Event {
            level: Level::Info,
            kind: EventKind::SessionRestarted,
            category: Category::Session,
            direction: Direction::Local,
            outcome: Outcome::Forwarded,
            reason: Reason::NotApplicable,
        });
        replacement.input_summaries = input_summaries;
        *self = replacement;
        self.clipboard_permissions = permissions;
        Ok(())
    }

    fn check_generation(&self, generation: u64) -> Result<(), SessionError> {
        if generation != self.generation {
            return Err(SessionError::StaleGeneration);
        }
        Ok(())
    }

    fn check_open(&self) -> Result<(), SessionError> {
        if self.state == SessionState::Closed {
            return Err(SessionError::Closed);
        }
        Ok(())
    }

    fn close_current(&mut self, reason: Reason, direction: Direction) {
        if self.state == SessionState::Closed {
            return;
        }
        self.state = SessionState::Closed;
        self.endpoints_open = [false, false];
        self.queues.iter_mut().for_each(VecDeque::clear);
        self.queued_bytes = 0;
        self.protocol = None;
        self.clipboard_transfers = [None; 2];
        self.clipboard_started = [false; 2];
        self.record_event(Event {
            level: Level::Info,
            kind: EventKind::SessionClosed,
            category: Category::Session,
            direction,
            outcome: Outcome::Disconnected,
            reason,
        });
    }

    fn record_event(&mut self, event: Event) {
        self.push_diagnostic(Record::Event(event));
    }

    fn push_diagnostic(&mut self, record: Record) {
        if self.diagnostics.len() == MAX_PENDING_DIAGNOSTICS {
            self.diagnostics.pop_front();
            self.dropped_diagnostics = self.dropped_diagnostics.saturating_add(1);
        }
        self.diagnostics.push_back(record);
    }

    fn clipboard_allowed(&self, source: usize) -> bool {
        self.clipboard_permissions[source].send && self.clipboard_permissions[1 - source].receive
    }

    fn receive_current(&mut self, from: Endpoint, payload: &[u8]) -> Result<(), SessionError> {
        let previous_state = self.state;
        let (next, protocol) = self.next_state(from, payload)?;
        if next == SessionState::Closed {
            self.close_current(Reason::PeerClosed, direction_from(from));
            return Ok(());
        }
        let clipboard = if matches!(payload.get(..4), Some(b"CCLP" | b"DCLP")) {
            let declared = u32::try_from(payload.len()).map_err(|_| {
                SessionError::Framing(crate::framing::FrameError::PayloadLengthOutOfRange {
                    length: payload.len(),
                })
            })?;
            if payload.len() > self.maximum_payload {
                return Err(SessionError::Framing(
                    crate::framing::FrameError::PayloadTooLarge {
                        declared,
                        maximum: self.maximum_payload,
                    },
                ));
            }
            let message = clipboard::parse(payload).map_err(|_| SessionError::MalformedMessage)?;
            let source = endpoint_index(from);
            let allowed = self.clipboard_allowed(source);
            let forward =
                clipboard::advance(&mut self.clipboard_transfers[source], &message, allowed)
                    .map_err(|_| SessionError::MalformedMessage)?;
            if !forward {
                self.accepted_frames = self.accepted_frames.saturating_add(1);
                if matches!(
                    message.kind,
                    ClipboardKind::Ownership | ClipboardKind::Start | ClipboardKind::End
                ) {
                    self.record_event(Event {
                        level: Level::Debug,
                        kind: EventKind::Message,
                        category: Category::Clipboard,
                        direction: direction_from(from),
                        outcome: Outcome::Denied,
                        reason: Reason::Policy,
                    });
                }
                return Ok(());
            }
            Some(message.kind)
        } else {
            None
        };
        let queued_bytes = payload
            .len()
            .checked_add(4)
            .and_then(|length| self.queued_bytes.checked_add(length))
            .filter(|length| *length <= self.maximum_queued_bytes)
            .ok_or(SessionError::QueueLimit {
                maximum: self.maximum_queued_bytes,
            })?;
        let encoded = encode_frame(payload, self.maximum_payload).map_err(SessionError::Framing)?;
        let destination = match from {
            Endpoint::Server => Endpoint::Client,
            Endpoint::Client => Endpoint::Server,
        };
        self.queues[endpoint_index(destination)].push_back(QueuedFrame {
            bytes: encoded,
            clipboard,
        });
        self.queued_bytes = queued_bytes;
        self.accepted_frames = self.accepted_frames.saturating_add(1);
        let protocol_negotiated =
            previous_state == SessionState::AwaitClientHello && from == Endpoint::Client;
        let event_kind = if protocol_negotiated {
            EventKind::ProtocolNegotiated
        } else {
            EventKind::Message
        };
        if let Some(kind) = input_kind(payload) {
            self.input_summaries.record(kind, InputOutcome::Forwarded);
        } else if protocol_negotiated
            || matches!(
                clipboard,
                Some(ClipboardKind::Ownership | ClipboardKind::Start | ClipboardKind::End)
            )
            || !is_keepalive(payload)
        {
            self.record_event(Event {
                level: if event_kind == EventKind::ProtocolNegotiated {
                    Level::Info
                } else {
                    Level::Trace
                },
                kind: event_kind,
                category: if clipboard.is_some() {
                    Category::Clipboard
                } else {
                    Category::Control
                },
                direction: direction_from(from),
                outcome: Outcome::Forwarded,
                reason: Reason::NotApplicable,
            });
        }
        self.state = next;
        if let Some(protocol) = protocol {
            self.protocol = Some(protocol);
        }
        if self.state == SessionState::Ready && previous_state != SessionState::Ready {
            self.record_event(Event {
                level: Level::Info,
                kind: EventKind::SessionReady,
                category: Category::Session,
                direction: Direction::Local,
                outcome: Outcome::Forwarded,
                reason: Reason::NotApplicable,
            });
        }
        Ok(())
    }

    fn next_state(
        &self,
        from: Endpoint,
        payload: &[u8],
    ) -> Result<(SessionState, Option<ProtocolName>), SessionError> {
        use Endpoint::{Client, Server};
        use SessionState::*;

        if self.state == AwaitServerHello {
            if from != Server {
                return Err(SessionError::UnexpectedMessage);
            }
            let hello = parse_server_hello(payload).map_err(SessionError::Handshake)?;
            let version =
                negotiate_server_version(hello.version).map_err(SessionError::Handshake)?;
            if version != CURRENT_VERSION {
                return Err(SessionError::UnsupportedVersion);
            }
            return Ok((AwaitClientHello, Some(hello.protocol)));
        }
        if self.state == AwaitClientHello {
            if from != Client {
                return Err(SessionError::UnexpectedMessage);
            }
            let hello = parse_client_hello(payload).map_err(SessionError::Handshake)?;
            let version =
                validate_client_version(hello.version).map_err(SessionError::Handshake)?;
            if version != CURRENT_VERSION {
                return Err(SessionError::UnsupportedVersion);
            }
            if self.protocol.as_ref() != Some(&hello.protocol) {
                return Err(SessionError::ProtocolMismatch);
            }
            return Ok((AwaitQueryInfo, None));
        }

        let code = payload.get(..4).ok_or(SessionError::MalformedMessage)?;
        if code == b"CALV" || code == b"CNOP" {
            check_length(payload, 4)?;
            return Ok((self.state, None));
        }
        if code == b"CBYE" && from == Server {
            check_length(payload, 4)?;
            return Ok((Closed, None));
        }
        let next = match (self.state, from, code) {
            (AwaitQueryInfo, Server, b"QINF") => {
                check_length(payload, 4)?;
                AwaitClientInfo
            }
            (AwaitClientInfo, Client, b"DINF") => {
                check_info(payload)?;
                AwaitInfoAck
            }
            (AwaitInfoAck, Server, b"CIAK") => {
                check_length(payload, 4)?;
                AwaitOptions
            }
            (AwaitOptions, Server, b"CROP") => {
                check_length(payload, 4)?;
                AwaitOptions
            }
            (AwaitOptions, Server, b"DSOP") => {
                check_options(payload)?;
                Ready
            }
            (Ready, _, _) => {
                check_ready_message(from, payload)?;
                Ready
            }
            _ => return Err(SessionError::UnexpectedMessage),
        };
        Ok((next, None))
    }
}

fn direction_from(endpoint: Endpoint) -> Direction {
    match endpoint {
        Endpoint::Server => Direction::ServerToClient,
        Endpoint::Client => Direction::ClientToServer,
    }
}

fn is_clipboard_message(payload: &[u8]) -> bool {
    matches!(payload.get(..4), Some(b"CCLP" | b"DCLP"))
}

fn is_keepalive(payload: &[u8]) -> bool {
    matches!(payload, b"CALV" | b"CNOP")
}

fn input_kind(payload: &[u8]) -> Option<InputKind> {
    match payload.get(..4)? {
        b"DKDL" | b"DKRP" | b"DKUP" => Some(InputKind::Keyboard),
        b"DMDN" | b"DMUP" | b"DMMV" | b"DMRM" | b"DMWM" | b"CINN" | b"COUT" => {
            Some(InputKind::Pointer)
        }
        _ => None,
    }
}

fn endpoint_index(endpoint: Endpoint) -> usize {
    match endpoint {
        Endpoint::Server => 0,
        Endpoint::Client => 1,
    }
}

fn check_length(payload: &[u8], expected: usize) -> Result<(), SessionError> {
    if payload.len() != expected {
        return Err(SessionError::MalformedMessage);
    }
    Ok(())
}

fn check_info(payload: &[u8]) -> Result<(), SessionError> {
    check_length(payload, 18)?;
    let width = i16::from_be_bytes([payload[8], payload[9]]);
    let height = i16::from_be_bytes([payload[10], payload[11]]);
    if width <= 0 || height <= 0 {
        return Err(SessionError::MalformedMessage);
    }
    Ok(())
}

fn check_options(payload: &[u8]) -> Result<(), SessionError> {
    if payload.len() < 8 {
        return Err(SessionError::MalformedMessage);
    }
    let count = u32::from_be_bytes([payload[4], payload[5], payload[6], payload[7]]);
    let expected = usize::try_from(count)
        .ok()
        .filter(|count| count % 2 == 0)
        .and_then(|count| count.checked_mul(4))
        .and_then(|length| length.checked_add(8));
    if expected != Some(payload.len()) {
        return Err(SessionError::MalformedMessage);
    }
    Ok(())
}

fn check_variable_field(payload: &[u8], offset: usize) -> Result<(), SessionError> {
    let Some(header) = payload
        .get(offset..)
        .and_then(|tail| tail.first_chunk::<4>())
    else {
        return Err(SessionError::MalformedMessage);
    };
    let expected = usize::try_from(u32::from_be_bytes(*header))
        .ok()
        .and_then(|length| length.checked_add(offset + 4));
    if expected != Some(payload.len()) {
        return Err(SessionError::MalformedMessage);
    }
    Ok(())
}

fn check_ready_message(from: Endpoint, payload: &[u8]) -> Result<(), SessionError> {
    let code = payload.get(..4).ok_or(SessionError::MalformedMessage)?;
    match (from, code) {
        (_, b"CCLP" | b"DCLP") => Ok(()),
        (Endpoint::Client, b"DINF") => check_info(payload),
        (Endpoint::Server, b"QINF" | b"CIAK" | b"CROP" | b"COUT") => check_length(payload, 4),
        (Endpoint::Server, b"DSOP") => check_options(payload),
        (Endpoint::Server, b"DMDN" | b"DMUP") => check_length(payload, 5),
        (Endpoint::Server, b"DMMV" | b"DMRM" | b"DMWM") => check_length(payload, 8),
        (Endpoint::Server, b"DKUP") => check_length(payload, 10),
        (Endpoint::Server, b"DKDL") => check_variable_field(payload, 10),
        (Endpoint::Server, b"DKRP") => check_variable_field(payload, 12),
        (Endpoint::Server, b"CINN") => check_length(payload, 14),
        _ => Err(SessionError::UnexpectedMessage),
    }
}
