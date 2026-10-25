use std::collections::VecDeque;
use std::io::{self, Read, Write};
use std::net::{Shutdown, SocketAddr, TcpListener, TcpStream};
use std::sync::Arc;
use std::sync::atomic::{AtomicBool, Ordering};
use std::thread;
use std::time::{Duration, Instant};

use crate::framing::{FrameError, decode_frame_at_eof};
use crate::session::{Endpoint, Session, SessionError, SessionState};

const READ_BUFFER_SIZE: usize = 8192;
const IDLE_POLL_INTERVAL: Duration = Duration::from_millis(10);
const ACCEPT_POLL_INTERVAL: Duration = Duration::from_millis(10);
pub const KEEPALIVE_INTERVAL: Duration = Duration::from_secs(3);
pub const MISSED_KEEPALIVES_UNTIL_TIMEOUT: u32 = 3;
pub const SESSION_IDLE_TIMEOUT: Duration =
    Duration::from_secs(KEEPALIVE_INTERVAL.as_secs() * MISSED_KEEPALIVES_UNTIL_TIMEOUT as u64);
pub const DEFAULT_PAIR_TIMEOUT: Duration = Duration::from_secs(30);
pub const DEFAULT_HANDSHAKE_TIMEOUT: Duration = Duration::from_secs(30);
pub const DEFAULT_INCOMPLETE_FRAME_TIMEOUT: Duration = Duration::from_secs(10);

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct TransportTimeouts {
    pub pair: Duration,
    pub handshake: Duration,
    pub incomplete_frame: Duration,
}

impl Default for TransportTimeouts {
    fn default() -> Self {
        Self {
            pair: DEFAULT_PAIR_TIMEOUT,
            handshake: DEFAULT_HANDSHAKE_TIMEOUT,
            incomplete_frame: DEFAULT_INCOMPLETE_FRAME_TIMEOUT,
        }
    }
}

#[derive(Clone, Default)]
pub struct CancellationToken {
    cancelled: Arc<AtomicBool>,
}

impl CancellationToken {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn cancel(&self) {
        self.cancelled.store(true, Ordering::Release);
    }

    pub fn is_cancelled(&self) -> bool {
        self.cancelled.load(Ordering::Acquire)
    }
}

pub struct FrameBuffer {
    maximum_payload: usize,
    bytes: Vec<u8>,
    expected_frame_length: Option<usize>,
}

impl FrameBuffer {
    /// Creates a decoder that retains at most one incomplete frame.
    pub fn new(maximum_payload: usize) -> Self {
        Self {
            maximum_payload,
            bytes: Vec::new(),
            expected_frame_length: None,
        }
    }

    /// Adds stream bytes and returns each complete payload in order.
    pub fn push(&mut self, input: &[u8]) -> Result<Vec<Vec<u8>>, FrameError> {
        let mut frames = Vec::new();
        let mut offset = 0;

        while offset < input.len() {
            if self.expected_frame_length.is_none() {
                let header_bytes_needed = 4 - self.bytes.len();
                let copied = header_bytes_needed.min(input.len() - offset);
                self.bytes
                    .extend_from_slice(&input[offset..offset + copied]);
                offset += copied;
                if self.bytes.len() < 4 {
                    break;
                }

                let declared = u32::from_be_bytes([
                    self.bytes[0],
                    self.bytes[1],
                    self.bytes[2],
                    self.bytes[3],
                ]);
                if declared == 0 {
                    return Err(FrameError::EmptyPayload);
                }
                let payload_length = usize::try_from(declared)
                    .ok()
                    .filter(|length| *length <= self.maximum_payload)
                    .ok_or(FrameError::PayloadTooLarge {
                        declared,
                        maximum: self.maximum_payload,
                    })?;
                self.expected_frame_length = Some(payload_length.checked_add(4).ok_or(
                    FrameError::PayloadTooLarge {
                        declared,
                        maximum: self.maximum_payload,
                    },
                )?);
            }

            let expected = self.expected_frame_length.expect("frame header was parsed");
            let frame_bytes_needed = expected - self.bytes.len();
            let copied = frame_bytes_needed.min(input.len() - offset);
            self.bytes
                .extend_from_slice(&input[offset..offset + copied]);
            offset += copied;

            if self.bytes.len() == expected {
                frames.push(self.bytes[4..].to_vec());
                self.bytes.clear();
                self.expected_frame_length = None;
            }
        }

        Ok(frames)
    }

    /// Checks whether EOF followed a complete frame boundary.
    pub fn finish(&self) -> Result<(), FrameError> {
        if self.bytes.is_empty() {
            return Ok(());
        }
        decode_frame_at_eof(&self.bytes, self.maximum_payload).map(|_| ())
    }

    fn has_incomplete_frame(&self) -> bool {
        !self.bytes.is_empty()
    }
}

#[derive(Debug)]
pub enum TransportError {
    Io(io::Error),
    Frame(FrameError),
    Session(SessionError),
    Cancelled,
    PairTimedOut,
    HandshakeTimedOut,
    IncompleteFrameTimedOut,
    SessionTimedOut,
}

impl std::fmt::Display for TransportError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Io(error) => write!(formatter, "transport I/O error: {error}"),
            Self::Frame(error) => write!(formatter, "transport frame error: {error:?}"),
            Self::Session(error) => write!(formatter, "session error: {error:?}"),
            Self::Cancelled => formatter.write_str("transport cancelled"),
            Self::PairTimedOut => formatter.write_str("timed out waiting for loopback peers"),
            Self::HandshakeTimedOut => formatter.write_str("session handshake timed out"),
            Self::IncompleteFrameTimedOut => formatter.write_str("incomplete frame timed out"),
            Self::SessionTimedOut => formatter.write_str("session keepalive timed out"),
        }
    }
}

impl std::error::Error for TransportError {
    fn source(&self) -> Option<&(dyn std::error::Error + 'static)> {
        match self {
            Self::Io(error) => Some(error),
            Self::Frame(_)
            | Self::Session(_)
            | Self::Cancelled
            | Self::PairTimedOut
            | Self::HandshakeTimedOut
            | Self::IncompleteFrameTimedOut
            | Self::SessionTimedOut => None,
        }
    }
}

impl From<io::Error> for TransportError {
    fn from(error: io::Error) -> Self {
        Self::Io(error)
    }
}

impl From<FrameError> for TransportError {
    fn from(error: FrameError) -> Self {
        Self::Frame(error)
    }
}

impl From<SessionError> for TransportError {
    fn from(error: SessionError) -> Self {
        Self::Session(error)
    }
}

/// Runs an in-memory session over two already-connected loopback TCP streams.
///
/// The streams are shut down when the session closes or either peer disconnects.
pub fn forward_session(
    server: TcpStream,
    client: TcpStream,
    session: &mut Session,
    generation: u64,
) -> Result<(), TransportError> {
    forward_session_cancellable(
        server,
        client,
        session,
        generation,
        &CancellationToken::new(),
    )
}

/// Runs a loopback session until closure, peer loss, timeout, or cancellation.
pub fn forward_session_cancellable(
    server: TcpStream,
    client: TcpStream,
    session: &mut Session,
    generation: u64,
    cancellation: &CancellationToken,
) -> Result<(), TransportError> {
    forward_session_with_timeouts_cancellable(
        server,
        client,
        session,
        generation,
        cancellation,
        TransportTimeouts::default(),
    )
}

pub fn forward_session_with_timeouts_cancellable(
    server: TcpStream,
    client: TcpStream,
    session: &mut Session,
    generation: u64,
    cancellation: &CancellationToken,
    timeouts: TransportTimeouts,
) -> Result<(), TransportError> {
    validate_loopback(&server)?;
    validate_loopback(&client)?;
    server.set_nonblocking(true)?;
    client.set_nonblocking(true)?;
    let mut streams = [server, client];
    let result = forward_loop(&mut streams, session, generation, cancellation, timeouts);
    let server_shutdown = streams[0].shutdown(Shutdown::Both);
    let client_shutdown = streams[1].shutdown(Shutdown::Both);

    match result {
        Err(error) => Err(error),
        Ok(()) => {
            server_shutdown?;
            client_shutdown?;
            Ok(())
        }
    }
}

/// Accepts paired server/client peers on loopback and runs fresh sessions.
pub struct LoopbackForwarder {
    server_listener: TcpListener,
    client_listener: TcpListener,
    maximum_payload: usize,
    maximum_queued_bytes: usize,
    timeouts: TransportTimeouts,
}

impl LoopbackForwarder {
    /// Binds two loopback-only listeners. Use port zero to request free ports.
    pub fn bind(
        server_address: SocketAddr,
        client_address: SocketAddr,
        maximum_payload: usize,
        maximum_queued_bytes: usize,
    ) -> io::Result<Self> {
        Self::bind_with_timeouts(
            server_address,
            client_address,
            maximum_payload,
            maximum_queued_bytes,
            TransportTimeouts::default(),
        )
    }

    pub fn bind_with_timeouts(
        server_address: SocketAddr,
        client_address: SocketAddr,
        maximum_payload: usize,
        maximum_queued_bytes: usize,
        timeouts: TransportTimeouts,
    ) -> io::Result<Self> {
        if !server_address.ip().is_loopback() || !client_address.ip().is_loopback() {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                "loopback forwarder addresses must be loopback IPs",
            ));
        }
        if maximum_payload == 0 {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                "maximum payload must be nonzero",
            ));
        }
        if timeouts.pair.is_zero()
            || timeouts.handshake.is_zero()
            || timeouts.incomplete_frame.is_zero()
        {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                "pair, handshake, and incomplete-frame timeouts must be nonzero",
            ));
        }

        let server_listener = TcpListener::bind(server_address)?;
        let client_listener = TcpListener::bind(client_address)?;
        server_listener.set_nonblocking(true)?;
        client_listener.set_nonblocking(true)?;
        Ok(Self {
            server_listener,
            client_listener,
            maximum_payload,
            maximum_queued_bytes,
            timeouts,
        })
    }

    /// Returns the bound server-side and client-side addresses.
    pub fn local_addrs(&self) -> io::Result<(SocketAddr, SocketAddr)> {
        Ok((
            self.server_listener.local_addr()?,
            self.client_listener.local_addr()?,
        ))
    }

    /// Accepts one peer on each listener and bridges them through a new session.
    ///
    /// This call blocks while waiting for either peer. A later call with a
    /// greater generation creates a separate session using the same listeners.
    pub fn run_once(&self, generation: u64) -> Result<(), TransportError> {
        self.run_once_cancellable(generation, &CancellationToken::new())
    }

    /// Accepts both peers with cancellation support and runs a fresh session.
    pub fn run_once_cancellable(
        &self,
        generation: u64,
        cancellation: &CancellationToken,
    ) -> Result<(), TransportError> {
        let pair_deadline = Instant::now() + self.timeouts.pair;
        let mut session = Session::new(generation, self.maximum_payload, self.maximum_queued_bytes);
        let server = match accept_cancellable(&self.server_listener, cancellation, pair_deadline) {
            Ok((stream, _)) => stream,
            Err(error) => {
                if matches!(&error, TransportError::PairTimedOut) {
                    session.pair_timeout(generation)?;
                } else if matches!(&error, TransportError::Cancelled) {
                    session.cancel(generation)?;
                }
                return Err(error);
            }
        };
        let client = match accept_cancellable(&self.client_listener, cancellation, pair_deadline) {
            Ok((stream, _)) => stream,
            Err(error) => {
                if matches!(&error, TransportError::PairTimedOut) {
                    session.pair_timeout(generation)?;
                } else if matches!(&error, TransportError::Cancelled) {
                    session.cancel(generation)?;
                }
                return Err(error);
            }
        };
        forward_session_with_timeouts_cancellable(
            server,
            client,
            &mut session,
            generation,
            cancellation,
            self.timeouts,
        )
    }
}

fn accept_cancellable(
    listener: &TcpListener,
    cancellation: &CancellationToken,
    deadline: Instant,
) -> Result<(TcpStream, SocketAddr), TransportError> {
    loop {
        if cancellation.is_cancelled() {
            return Err(TransportError::Cancelled);
        }
        if Instant::now() >= deadline {
            return Err(TransportError::PairTimedOut);
        }
        match listener.accept() {
            Ok(peer) => return Ok(peer),
            Err(error) if error.kind() == io::ErrorKind::WouldBlock => {
                thread::sleep(ACCEPT_POLL_INTERVAL);
            }
            Err(error) if error.kind() == io::ErrorKind::Interrupted => {}
            Err(error) => return Err(error.into()),
        }
    }
}

fn validate_loopback(stream: &TcpStream) -> io::Result<()> {
    if stream.local_addr()?.ip().is_loopback() && stream.peer_addr()?.ip().is_loopback() {
        return Ok(());
    }
    Err(io::Error::new(
        io::ErrorKind::InvalidInput,
        "session forwarding accepts loopback TCP streams only",
    ))
}

fn forward_loop(
    streams: &mut [TcpStream; 2],
    session: &mut Session,
    generation: u64,
    cancellation: &CancellationToken,
    timeouts: TransportTimeouts,
) -> Result<(), TransportError> {
    let mut server_decoder = FrameBuffer::new(session.maximum_payload());
    let mut client_decoder = FrameBuffer::new(session.maximum_payload());
    let mut pending_frames: [VecDeque<Vec<u8>>; 2] = [VecDeque::new(), VecDeque::new()];
    let mut pending_writes: [Option<(Vec<u8>, usize)>; 2] = [None, None];
    let mut read_buffer = [0u8; READ_BUFFER_SIZE];
    let mut last_message = None;
    let handshake_deadline = Instant::now() + timeouts.handshake;
    let mut incomplete_frame_since: [Option<Instant>; 2] = [None, None];

    loop {
        if cancellation.is_cancelled() {
            session.cancel(generation)?;
            return Err(TransportError::Cancelled);
        }
        let state = session.snapshot().state;
        if state != SessionState::Ready && Instant::now() >= handshake_deadline {
            session.handshake_timeout(generation)?;
            return Err(TransportError::HandshakeTimedOut);
        }
        if incomplete_frame_since
            .iter()
            .flatten()
            .any(|since| since.elapsed() >= timeouts.incomplete_frame)
        {
            session.incomplete_frame_timeout(generation)?;
            return Err(TransportError::IncompleteFrameTimedOut);
        }
        let mut made_progress = false;

        for (index, stream) in streams.iter_mut().enumerate() {
            if !pending_frames[index].is_empty() {
                continue;
            }
            let decoder = if index == 0 {
                &mut server_decoder
            } else {
                &mut client_decoder
            };
            let frame_was_incomplete = decoder.has_incomplete_frame();
            match stream.read(&mut read_buffer) {
                Ok(0) => {
                    let result = decoder.finish();
                    session.disconnect(generation, endpoint(index))?;
                    result?;
                    return Ok(());
                }
                Ok(read) => {
                    made_progress = true;
                    let frames = decoder.push(&read_buffer[..read])?;
                    let completed_frame = !frames.is_empty();
                    pending_frames[index].extend(frames);
                    incomplete_frame_since[index] = if decoder.has_incomplete_frame() {
                        if frame_was_incomplete && !completed_frame {
                            incomplete_frame_since[index]
                        } else {
                            Some(Instant::now())
                        }
                    } else {
                        None
                    };
                }
                Err(error) if error.kind() == io::ErrorKind::WouldBlock => {}
                Err(error) if error.kind() == io::ErrorKind::Interrupted => {}
                Err(error) => return Err(error.into()),
            }
        }

        for (index, frames) in pending_frames.iter_mut().enumerate() {
            if let Some(payload) = frames.pop_front() {
                made_progress = true;
                session.receive(generation, endpoint(index), &payload)?;
                if session.snapshot().state == SessionState::Ready {
                    last_message = Some(Instant::now());
                }
                if session.snapshot().state == SessionState::Closed {
                    return Ok(());
                }
            }
        }

        for (index, stream) in streams.iter_mut().enumerate() {
            if pending_writes[index].is_none() {
                pending_writes[index] = session
                    .take_next(generation, endpoint(index))?
                    .map(|bytes| (bytes, 0));
            }

            while let Some((bytes, offset)) = pending_writes[index].as_mut() {
                match stream.write(&bytes[*offset..]) {
                    Ok(0) => {
                        return Err(io::Error::new(
                            io::ErrorKind::WriteZero,
                            "TCP stream accepted no frame bytes",
                        )
                        .into());
                    }
                    Ok(written) => {
                        made_progress = true;
                        *offset += written;
                        if *offset == bytes.len() {
                            pending_writes[index] = None;
                            pending_writes[index] = session
                                .take_next(generation, endpoint(index))?
                                .map(|next| (next, 0));
                        }
                    }
                    Err(error) if error.kind() == io::ErrorKind::WouldBlock => break,
                    Err(error) if error.kind() == io::ErrorKind::Interrupted => continue,
                    Err(error) => return Err(error.into()),
                }
            }
        }

        if session.snapshot().state == SessionState::Closed {
            return Ok(());
        }
        if session.snapshot().state == SessionState::Ready {
            let last_message = last_message.get_or_insert_with(Instant::now);
            if last_message.elapsed() >= SESSION_IDLE_TIMEOUT {
                session.timeout(generation)?;
                return Err(TransportError::SessionTimedOut);
            }
        }
        if !made_progress {
            thread::sleep(IDLE_POLL_INTERVAL);
        }
    }
}

fn endpoint(index: usize) -> Endpoint {
    if index == 0 {
        Endpoint::Server
    } else {
        Endpoint::Client
    }
}
