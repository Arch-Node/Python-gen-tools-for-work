#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct ClipboardPermissions {
    pub send: bool,
    pub receive: bool,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum ClipboardKind {
    Ownership,
    Start,
    Data,
    End,
}

pub(crate) struct ClipboardMessage<'input> {
    pub kind: ClipboardKind,
    pub id: u8,
    pub sequence: u32,
    pub data: &'input [u8],
}

#[derive(Clone, Copy)]
pub(crate) struct Transfer {
    id: u8,
    sequence: u32,
    expected: u64,
    received: u64,
    pub forward: bool,
}

pub(crate) fn parse(payload: &[u8]) -> Result<ClipboardMessage<'_>, ()> {
    if payload.len() < 9 || payload[4] >= 2 {
        return Err(());
    }
    let sequence = u32::from_be_bytes(payload[5..9].try_into().map_err(|_| ())?);
    let (kind, data) = match &payload[..4] {
        b"CCLP" if payload.len() == 9 => (ClipboardKind::Ownership, &[][..]),
        b"DCLP" if payload.len() >= 14 => {
            let length = u32::from_be_bytes(payload[10..14].try_into().map_err(|_| ())?);
            let data = &payload[14..];
            if usize::try_from(length).ok() != Some(data.len()) {
                return Err(());
            }
            let kind = match payload[9] {
                1 => ClipboardKind::Start,
                2 => ClipboardKind::Data,
                3 if data.is_empty() => ClipboardKind::End,
                _ => return Err(()),
            };
            (kind, data)
        }
        _ => return Err(()),
    };
    Ok(ClipboardMessage {
        kind,
        id: payload[4],
        sequence,
        data,
    })
}

pub(crate) fn advance(
    active: &mut Option<Transfer>,
    message: &ClipboardMessage<'_>,
    allowed: bool,
) -> Result<bool, ()> {
    match message.kind {
        ClipboardKind::Ownership => Ok(allowed),
        ClipboardKind::Start => {
            if active.is_some() || message.data.is_empty() {
                return Err(());
            }
            let expected = message.data.iter().try_fold(0_u64, |size, digit| {
                if !digit.is_ascii_digit() {
                    return Err(());
                }
                size.checked_mul(10)
                    .and_then(|size| size.checked_add(u64::from(digit - b'0')))
                    .ok_or(())
            })?;
            *active = Some(Transfer {
                id: message.id,
                sequence: message.sequence,
                expected,
                received: 0,
                forward: allowed,
            });
            Ok(allowed)
        }
        ClipboardKind::Data | ClipboardKind::End => {
            let transfer = active.as_mut().ok_or(())?;
            if transfer.id != message.id || transfer.sequence != message.sequence {
                return Err(());
            }
            transfer.forward &= allowed;
            transfer.received = transfer
                .received
                .checked_add(message.data.len() as u64)
                .ok_or(())?;
            if transfer.received > transfer.expected {
                return Err(());
            }
            let forward = transfer.forward;
            if message.kind == ClipboardKind::End {
                if transfer.received != transfer.expected {
                    return Err(());
                }
                *active = None;
            }
            Ok(forward)
        }
    }
}
