pub struct DecodedFrame<'input> {
    pub payload: &'input [u8],
    pub remaining: &'input [u8],
}

#[derive(Debug, PartialEq, Eq)]
pub enum FrameError {
    EmptyPayload,
    PayloadLengthOutOfRange { length: usize },
    PayloadTooLarge { declared: u32, maximum: usize },
    TruncatedHeader { received: usize },
    TruncatedPayload { declared: u32, received: usize },
}

pub fn decode_frame(
    input: &[u8],
    maximum_payload: usize,
) -> Result<Option<DecodedFrame<'_>>, FrameError> {
    let Some(header) = input.first_chunk::<4>() else {
        return Ok(None);
    };
    let declared = u32::from_be_bytes(*header);
    if declared == 0 {
        return Err(FrameError::EmptyPayload);
    }
    let payload_length = usize::try_from(declared)
        .ok()
        .filter(|length| *length <= maximum_payload)
        .ok_or(FrameError::PayloadTooLarge {
            declared,
            maximum: maximum_payload,
        })?;

    let body = &input[4..];
    if body.len() < payload_length {
        return Ok(None);
    }
    let (payload, remaining) = body.split_at(payload_length);
    Ok(Some(DecodedFrame { payload, remaining }))
}

pub fn decode_frame_at_eof(
    input: &[u8],
    maximum_payload: usize,
) -> Result<Option<DecodedFrame<'_>>, FrameError> {
    let decoded = decode_frame(input, maximum_payload)?;
    if decoded.is_some() || input.is_empty() {
        return Ok(decoded);
    }

    let Some(header) = input.first_chunk::<4>() else {
        return Err(FrameError::TruncatedHeader {
            received: input.len(),
        });
    };
    Err(FrameError::TruncatedPayload {
        declared: u32::from_be_bytes(*header),
        received: input.len() - 4,
    })
}

pub fn encode_frame(payload: &[u8], maximum_payload: usize) -> Result<Vec<u8>, FrameError> {
    if payload.is_empty() {
        return Err(FrameError::EmptyPayload);
    }
    let declared =
        u32::try_from(payload.len()).map_err(|_| FrameError::PayloadLengthOutOfRange {
            length: payload.len(),
        })?;
    if payload.len() > maximum_payload {
        return Err(FrameError::PayloadTooLarge {
            declared,
            maximum: maximum_payload,
        });
    }

    let mut encoded = Vec::from(declared.to_be_bytes());
    encoded.extend_from_slice(payload);
    Ok(encoded)
}
