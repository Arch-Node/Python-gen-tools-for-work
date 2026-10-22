use std::io::{self, Write};
use std::time::Duration;

pub const MAX_PENDING_DIAGNOSTICS: usize = 5_000;

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
pub enum Level {
    Info,
    Debug,
    Trace,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Category {
    Clipboard,
    KeyboardInput,
    PointerInput,
    Control,
    Session,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Direction {
    ServerToClient,
    ClientToServer,
    Local,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Outcome {
    Forwarded,
    Denied,
    Rejected,
    Disconnected,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum EventKind {
    SessionOpened,
    SessionRestarted,
    ProtocolNegotiated,
    SessionReady,
    Message,
    SessionClosed,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Reason {
    Policy,
    Malformed,
    QueueLimit,
    PeerClosed,
    Timeout,
    PairTimeout,
    HandshakeTimeout,
    IncompleteFrameTimeout,
    Cancelled,
    NotApplicable,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Event {
    pub level: Level,
    pub kind: EventKind,
    pub category: Category,
    pub direction: Direction,
    pub outcome: Outcome,
    pub reason: Reason,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum InputKind {
    Keyboard,
    Pointer,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum InputOutcome {
    Forwarded,
    Denied,
}

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct InputSummary {
    pub window: Duration,
    pub keyboard_forwarded: u64,
    pub keyboard_denied: u64,
    pub pointer_forwarded: u64,
    pub pointer_denied: u64,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Record {
    Event(Event),
    InputSummary(InputSummary),
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DiagnosticsBatch {
    pub records: Vec<Record>,
    pub dropped_records: u64,
}

pub struct LogRecorder<W: Write> {
    minimum_level: Level,
    writer: W,
}

impl<W: Write> LogRecorder<W> {
    pub fn new(writer: W, minimum_level: Level) -> Self {
        Self {
            minimum_level,
            writer,
        }
    }

    pub fn record_event(&mut self, event: Event) -> io::Result<()> {
        if event.level >= self.minimum_level {
            writeln!(
                self.writer,
                "event level={} kind={} category={} direction={} outcome={} reason={}",
                level_name(event.level),
                event_kind_name(event.kind),
                category_name(event.category),
                direction_name(event.direction),
                outcome_name(event.outcome),
                reason_name(event.reason)
            )?;
        }
        Ok(())
    }

    pub fn record_summary(&mut self, summary: InputSummary) -> io::Result<()> {
        if self.minimum_level <= Level::Info {
            writeln!(
                self.writer,
                "input summary interval_ms={} keyboard_forwarded={} keyboard_denied={} pointer_forwarded={} pointer_denied={}",
                summary.window.as_millis(),
                summary.keyboard_forwarded,
                summary.keyboard_denied,
                summary.pointer_forwarded,
                summary.pointer_denied
            )?;
        }
        Ok(())
    }

    pub fn into_inner(self) -> W {
        self.writer
    }
}

fn level_name(level: Level) -> &'static str {
    match level {
        Level::Info => "info",
        Level::Debug => "debug",
        Level::Trace => "trace",
    }
}

fn category_name(category: Category) -> &'static str {
    match category {
        Category::Clipboard => "clipboard",
        Category::KeyboardInput => "keyboard",
        Category::PointerInput => "pointer",
        Category::Control => "control",
        Category::Session => "session",
    }
}

fn event_kind_name(kind: EventKind) -> &'static str {
    match kind {
        EventKind::SessionOpened => "session-opened",
        EventKind::SessionRestarted => "session-restarted",
        EventKind::ProtocolNegotiated => "protocol-negotiated",
        EventKind::SessionReady => "session-ready",
        EventKind::Message => "message",
        EventKind::SessionClosed => "session-closed",
    }
}

fn direction_name(direction: Direction) -> &'static str {
    match direction {
        Direction::ServerToClient => "server-to-client",
        Direction::ClientToServer => "client-to-server",
        Direction::Local => "local",
    }
}

fn outcome_name(outcome: Outcome) -> &'static str {
    match outcome {
        Outcome::Forwarded => "forwarded",
        Outcome::Denied => "denied",
        Outcome::Rejected => "rejected",
        Outcome::Disconnected => "disconnected",
    }
}

fn reason_name(reason: Reason) -> &'static str {
    match reason {
        Reason::Policy => "policy",
        Reason::Malformed => "malformed",
        Reason::QueueLimit => "queue-limit",
        Reason::PeerClosed => "peer-closed",
        Reason::Timeout => "timeout",
        Reason::PairTimeout => "pair-timeout",
        Reason::HandshakeTimeout => "handshake-timeout",
        Reason::IncompleteFrameTimeout => "incomplete-frame-timeout",
        Reason::Cancelled => "cancelled",
        Reason::NotApplicable => "not-applicable",
    }
}

pub struct MemoryRecorder {
    minimum_level: Level,
    records: Vec<Record>,
}

impl MemoryRecorder {
    pub fn new(minimum_level: Level) -> Self {
        Self {
            minimum_level,
            records: Vec::new(),
        }
    }

    pub fn record_event(&mut self, event: Event) {
        if event.level >= self.minimum_level {
            self.records.push(Record::Event(event));
        }
    }

    pub fn record_summary(&mut self, summary: InputSummary) {
        self.records.push(Record::InputSummary(summary));
    }

    pub fn records(&self) -> &[Record] {
        &self.records
    }
}

pub struct InputSummaryTracker {
    interval: Duration,
    next_deadline: Duration,
    counts: InputSummary,
}

impl InputSummaryTracker {
    pub fn new(interval: Duration, started_at: Duration) -> Self {
        let interval = interval.max(Duration::from_nanos(1));
        let next_deadline = started_at.checked_add(interval).unwrap_or(Duration::MAX);
        Self {
            interval,
            next_deadline,
            counts: InputSummary {
                window: interval,
                ..InputSummary::default()
            },
        }
    }

    pub fn record(&mut self, kind: InputKind, outcome: InputOutcome) {
        let count = match (kind, outcome) {
            (InputKind::Keyboard, InputOutcome::Forwarded) => &mut self.counts.keyboard_forwarded,
            (InputKind::Keyboard, InputOutcome::Denied) => &mut self.counts.keyboard_denied,
            (InputKind::Pointer, InputOutcome::Forwarded) => &mut self.counts.pointer_forwarded,
            (InputKind::Pointer, InputOutcome::Denied) => &mut self.counts.pointer_denied,
        };
        *count = count.saturating_add(1);
    }

    pub fn take_due(&mut self, now: Duration) -> Option<InputSummary> {
        if now < self.next_deadline {
            return None;
        }
        let summary = self.counts;
        self.counts = InputSummary {
            window: self.interval,
            ..InputSummary::default()
        };
        self.next_deadline = self
            .next_deadline
            .checked_add(self.interval)
            .unwrap_or(Duration::MAX);
        Some(summary)
    }

    pub fn reset(&mut self, now: Duration) {
        self.counts = InputSummary {
            window: self.interval,
            ..InputSummary::default()
        };
        self.next_deadline = now.checked_add(self.interval).unwrap_or(Duration::MAX);
    }
}
