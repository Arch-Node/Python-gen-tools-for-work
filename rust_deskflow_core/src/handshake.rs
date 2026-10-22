pub const MAX_HELLO_LENGTH: usize = 1024;
const SERVER_HELLO_LENGTH: usize = 11;
const CLIENT_HELLO_PREFIX_LENGTH: usize = 15;

#[derive(Debug, PartialEq, Eq)]
pub enum ProtocolName {
    Barrier,
    Synergy,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ProtocolVersion {
    pub major: i16,
    pub minor: i16,
}

pub const CURRENT_VERSION: ProtocolVersion = ProtocolVersion { major: 1, minor: 8 };

pub struct ServerHello {
    pub protocol: ProtocolName,
    pub version: ProtocolVersion,
}

pub struct ClientHello<'input> {
    pub protocol: ProtocolName,
    pub version: ProtocolVersion,
    pub name: &'input [u8],
}

#[derive(Debug, PartialEq, Eq)]
pub enum HandshakeError {
    HelloTooLarge { length: usize, maximum: usize },
    Truncated { expected: usize, received: usize },
    InvalidProtocol,
    InvalidVersion { major: i16, minor: i16 },
    NameTooLarge { declared: u32, maximum: usize },
    TrailingBytes { count: usize },
    UnsupportedVersion { major: i16, minor: i16 },
}

pub fn parse_server_hello(payload: &[u8]) -> Result<ServerHello, HandshakeError> {
    let (protocol, version) = parse_header(payload)?;
    if payload.len() > SERVER_HELLO_LENGTH {
        return Err(HandshakeError::TrailingBytes {
            count: payload.len() - SERVER_HELLO_LENGTH,
        });
    }
    Ok(ServerHello { protocol, version })
}

pub fn parse_client_hello(payload: &[u8]) -> Result<ClientHello<'_>, HandshakeError> {
    let (protocol, version) = parse_header(payload)?;
    if payload.len() < CLIENT_HELLO_PREFIX_LENGTH {
        return Err(HandshakeError::Truncated {
            expected: CLIENT_HELLO_PREFIX_LENGTH,
            received: payload.len(),
        });
    }
    let declared = u32::from_be_bytes([payload[11], payload[12], payload[13], payload[14]]);
    let maximum = MAX_HELLO_LENGTH - CLIENT_HELLO_PREFIX_LENGTH;
    let name_length = usize::try_from(declared)
        .ok()
        .filter(|length| *length <= maximum)
        .ok_or(HandshakeError::NameTooLarge { declared, maximum })?;
    let expected = CLIENT_HELLO_PREFIX_LENGTH + name_length;
    if payload.len() < expected {
        return Err(HandshakeError::Truncated {
            expected,
            received: payload.len(),
        });
    }
    if payload.len() > expected {
        return Err(HandshakeError::TrailingBytes {
            count: payload.len() - expected,
        });
    }
    Ok(ClientHello {
        protocol,
        version,
        name: &payload[CLIENT_HELLO_PREFIX_LENGTH..],
    })
}

pub fn negotiate_server_version(
    version: ProtocolVersion,
) -> Result<ProtocolVersion, HandshakeError> {
    if version.major != CURRENT_VERSION.major || version.minor < 6 {
        return Err(HandshakeError::UnsupportedVersion {
            major: version.major,
            minor: version.minor,
        });
    }
    Ok(ProtocolVersion {
        major: CURRENT_VERSION.major,
        minor: version.minor.min(CURRENT_VERSION.minor),
    })
}

pub fn validate_client_version(
    version: ProtocolVersion,
) -> Result<ProtocolVersion, HandshakeError> {
    if version.major != CURRENT_VERSION.major
        || !(0..=CURRENT_VERSION.minor).contains(&version.minor)
    {
        return Err(HandshakeError::UnsupportedVersion {
            major: version.major,
            minor: version.minor,
        });
    }
    Ok(version)
}

fn parse_header(payload: &[u8]) -> Result<(ProtocolName, ProtocolVersion), HandshakeError> {
    if payload.len() > MAX_HELLO_LENGTH {
        return Err(HandshakeError::HelloTooLarge {
            length: payload.len(),
            maximum: MAX_HELLO_LENGTH,
        });
    }
    if payload.len() < SERVER_HELLO_LENGTH {
        return Err(HandshakeError::Truncated {
            expected: SERVER_HELLO_LENGTH,
            received: payload.len(),
        });
    }
    let protocol = match &payload[..7] {
        b"Barrier" => ProtocolName::Barrier,
        b"Synergy" => ProtocolName::Synergy,
        _ => return Err(HandshakeError::InvalidProtocol),
    };
    let version = ProtocolVersion {
        major: i16::from_be_bytes([payload[7], payload[8]]),
        minor: i16::from_be_bytes([payload[9], payload[10]]),
    };
    if version.major <= 0 || version.minor < 0 {
        return Err(HandshakeError::InvalidVersion {
            major: version.major,
            minor: version.minor,
        });
    }
    Ok((protocol, version))
}
