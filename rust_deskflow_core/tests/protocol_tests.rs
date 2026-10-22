mod framing {
    /// Setup: declare 258 payload bytes with prefix [0, 0, 1, 2], then append CALV.
    /// Exercise: decode one frame with a 1024-byte limit.
    /// Expect: exactly 258 unchanged bytes and the entire next frame as remainder.
    /// Scope: fixed wire bytes distinguish big-endian decoding from a round trip.
    #[test]
    fn decodes_big_endian_payload_length() {
        let payload = vec![b'x'; 258];
        let following_frame = [0, 0, 0, 4, b'C', b'A', b'L', b'V'];
        let mut input = vec![0, 0, 1, 2];
        input.extend_from_slice(&payload);
        input.extend_from_slice(&following_frame);

        let decoded = rust_deskflow_core::framing::decode_frame(&input, 1024)
            .expect("a frame within the configured limit must be accepted")
            .expect("the payload is complete");

        assert_eq!(decoded.payload, payload.as_slice());
        assert_eq!(decoded.remaining, following_frame);
    }

    /// Setup: expose zero through four bytes of an eight-byte CALV frame.
    /// Exercise: decode each growing prefix without announcing EOF.
    /// Expect: Ok(None), including when the header exists but no payload does.
    /// Scope: callers retain these bytes; this does not test an internal buffer.
    #[test]
    fn waits_for_a_fragmented_header() {
        let frame = [0, 0, 0, 4, b'C', b'A', b'L', b'V'];
        for available in 0..=4 {
            let decoded = rust_deskflow_core::framing::decode_frame(&frame[..available], 1024)
                .expect("a partial header or payload is not a format error");
            assert!(decoded.is_none());
        }
    }

    /// Setup: supply a full header and each incomplete prefix of CALV's payload.
    /// Exercise: retry with accumulated input, then supply the complete frame.
    /// Expect: no early frame; final payload is CALV and the remainder is empty.
    /// Scope: partial input is not malformed until the caller declares EOF.
    #[test]
    fn waits_for_a_fragmented_payload() {
        let frame = [0, 0, 0, 4, b'C', b'A', b'L', b'V'];
        for available in 4..frame.len() {
            let decoded = rust_deskflow_core::framing::decode_frame(&frame[..available], 1024)
                .expect("an incomplete payload should wait for more bytes");
            assert!(decoded.is_none());
        }
        let decoded = rust_deskflow_core::framing::decode_frame(&frame, 1024)
            .unwrap()
            .unwrap();
        assert_eq!(decoded.payload, b"CALV");
        assert!(decoded.remaining.is_empty());
    }

    /// Setup: concatenate independently specified CALV and CNOP wire frames.
    /// Exercise: decode once, then decode the first result's remainder.
    /// Expect: CALV followed by CNOP, with no duplication or leftover bytes.
    /// Scope: the one-frame API must not merge payloads from a combined read.
    #[test]
    fn emits_coalesced_frames_in_order() {
        let frames = [
            0, 0, 0, 4, b'C', b'A', b'L', b'V', 0, 0, 0, 4, b'C', b'N', b'O', b'P',
        ];
        let first = rust_deskflow_core::framing::decode_frame(&frames, 1024)
            .unwrap()
            .unwrap();
        let second = rust_deskflow_core::framing::decode_frame(first.remaining, 1024)
            .unwrap()
            .unwrap();
        assert_eq!(first.payload, b"CALV");
        assert_eq!(second.payload, b"CNOP");
        assert!(second.remaining.is_empty());
    }

    /// Setup: header-only inputs declare 4097 bytes and u32::MAX; limit is 4096.
    /// Exercise: decode without supplying any claimed payload bytes.
    /// Expect: PayloadTooLarge containing the declared length and configured limit.
    /// Scope: rejection must not wait for or allocate the advertised payload.
    #[test]
    fn rejects_oversized_length_before_buffering_payload() {
        let error = rust_deskflow_core::framing::decode_frame(&[0, 0, 16, 1], 4096).err();
        assert_eq!(
            error,
            Some(rust_deskflow_core::framing::FrameError::PayloadTooLarge {
                declared: 4097,
                maximum: 4096,
            })
        );
        let error = rust_deskflow_core::framing::decode_frame(&[255, 255, 255, 255], 4096).err();
        assert_eq!(
            error,
            Some(rust_deskflow_core::framing::FrameError::PayloadTooLarge {
                declared: u32::MAX,
                maximum: 4096,
            })
        );
    }

    /// Setup: CALV has a four-byte payload, independent of its four-byte header.
    /// Exercise: decode with a limit of four, then with a limit of three.
    /// Expect: exact-limit success and PayloadTooLarge for the smaller limit.
    /// Scope: the limit applies to payload bytes, not total encoded frame size.
    #[test]
    fn accepts_a_payload_at_the_configured_limit() {
        let frame = [0, 0, 0, 4, b'C', b'A', b'L', b'V'];
        let decoded = rust_deskflow_core::framing::decode_frame(&frame, 4)
            .unwrap()
            .unwrap();
        assert_eq!(decoded.payload, b"CALV");
        assert!(decoded.remaining.is_empty());
        assert_eq!(
            rust_deskflow_core::framing::decode_frame(&frame, 3).err(),
            Some(rust_deskflow_core::framing::FrameError::PayloadTooLarge {
                declared: 4,
                maximum: 3,
            })
        );
    }

    /// Setup: truncate the CALV frame at every nonempty incomplete boundary.
    /// Exercise: compare ordinary decoding with decoding after EOF.
    /// Expect: ordinary reads wait; EOF reports header or payload truncation.
    /// Scope: received payload counts exclude the header and errors omit contents.
    #[test]
    fn reports_truncated_header_or_payload_at_eof() {
        use rust_deskflow_core::framing::{FrameError, decode_frame, decode_frame_at_eof};

        let frame = [0, 0, 0, 4, b'C', b'A', b'L', b'V'];
        for received in 1..4 {
            let input = &frame[..received];
            assert!(decode_frame(input, 1024).unwrap().is_none());
            assert_eq!(
                decode_frame_at_eof(input, 1024).err(),
                Some(FrameError::TruncatedHeader { received })
            );
        }
        for received in 0..4 {
            let input = &frame[..4 + received];
            assert!(decode_frame(input, 1024).unwrap().is_none());
            assert_eq!(
                decode_frame_at_eof(input, 1024).err(),
                Some(FrameError::TruncatedPayload {
                    declared: 4,
                    received,
                })
            );
        }
    }

    /// Setup: use an empty buffer and a separate complete CALV frame at EOF.
    /// Exercise: decode both, then decode the complete frame's empty remainder.
    /// Expect: clean ends return None; a complete final frame remains readable.
    /// Scope: EOF is not itself a protocol error or permission to discard a frame.
    #[test]
    fn eof_accepts_clean_end_and_complete_frames() {
        use rust_deskflow_core::framing::decode_frame_at_eof;

        assert!(decode_frame_at_eof(&[], 1024).unwrap().is_none());
        let frame = [0, 0, 0, 4, b'C', b'A', b'L', b'V'];
        let decoded = decode_frame_at_eof(&frame, 1024).unwrap().unwrap();
        assert_eq!(decoded.payload, b"CALV");
        assert!(decoded.remaining.is_empty());
        assert!(
            decode_frame_at_eof(decoded.remaining, 1024)
                .unwrap()
                .is_none()
        );
    }

    /// Setup: two complete frames precede either a partial header or payload.
    /// Exercise: repeatedly decode each returned remainder after EOF.
    /// Expect: both valid payloads arrive in order before the exact tail error.
    /// Scope: the first successful decode does not certify its remainder as valid.
    #[test]
    fn eof_returns_complete_frames_before_truncated_tail() {
        use rust_deskflow_core::framing::{FrameError, decode_frame_at_eof};

        for (tail, expected) in [
            (&[0, 0][..], FrameError::TruncatedHeader { received: 2 }),
            (
                &[0, 0, 0, 4, b'C'][..],
                FrameError::TruncatedPayload {
                    declared: 4,
                    received: 1,
                },
            ),
        ] {
            let mut input = vec![
                0, 0, 0, 4, b'C', b'A', b'L', b'V', 0, 0, 0, 4, b'C', b'N', b'O', b'P',
            ];
            input.extend_from_slice(tail);

            let first = decode_frame_at_eof(&input, 1024).unwrap().unwrap();
            let second = decode_frame_at_eof(first.remaining, 1024).unwrap().unwrap();
            assert_eq!(first.payload, b"CALV");
            assert_eq!(second.payload, b"CNOP");
            assert_eq!(second.remaining, tail);
            assert_eq!(
                decode_frame_at_eof(second.remaining, 1024).err(),
                Some(expected)
            );
        }
    }

    /// Setup: a complete header declares 4097 bytes against a 4096-byte limit.
    /// Exercise: declare EOF without providing the claimed payload.
    /// Expect: PayloadTooLarge, not the less specific truncated-payload error.
    /// Scope: EOF and ordinary decoding must retain the same size policy.
    #[test]
    fn eof_preserves_size_limit_errors() {
        use rust_deskflow_core::framing::{FrameError, decode_frame_at_eof};

        assert_eq!(
            decode_frame_at_eof(&[0, 0, 16, 1], 4096).err(),
            Some(FrameError::PayloadTooLarge {
                declared: 4097,
                maximum: 4096,
            })
        );
    }

    /// Setup: distinguish an empty buffer from a four-byte zero-length prefix.
    /// Exercise: encode empty input; decode zero prefixes normally and at EOF.
    /// Expect: EmptyPayload for envelopes, even at a zero limit or before CALV.
    /// Scope: empty buffers still wait/end cleanly; stricter than upstream behavior.
    #[test]
    fn handles_zero_length_frames_using_the_documented_policy() {
        use rust_deskflow_core::framing::{
            FrameError, decode_frame, decode_frame_at_eof, encode_frame,
        };

        let empty_frame = [0, 0, 0, 0];
        assert_eq!(
            decode_frame(&empty_frame, 1024).err(),
            Some(FrameError::EmptyPayload)
        );
        assert_eq!(
            decode_frame_at_eof(&empty_frame, 1024).err(),
            Some(FrameError::EmptyPayload)
        );
        assert_eq!(
            encode_frame(&[], 1024).err(),
            Some(FrameError::EmptyPayload)
        );
        assert_eq!(encode_frame(&[], 0).err(), Some(FrameError::EmptyPayload));
        assert_eq!(
            decode_frame(&empty_frame, 0).err(),
            Some(FrameError::EmptyPayload)
        );
        assert!(decode_frame(&[], 1024).unwrap().is_none());
        assert!(decode_frame_at_eof(&[], 1024).unwrap().is_none());

        let empty_then_valid = [0, 0, 0, 0, 0, 0, 0, 4, b'C', b'A', b'L', b'V'];
        assert_eq!(
            decode_frame(&empty_then_valid, 1024).err(),
            Some(FrameError::EmptyPayload)
        );
        assert_eq!(
            decode_frame_at_eof(&empty_then_valid, 1024).err(),
            Some(FrameError::EmptyPayload)
        );
    }

    /// Setup: 258 synthetic bytes and independently specified prefix [0, 0, 1, 2].
    /// Exercise: encode with a sufficient limit without modifying the input.
    /// Expect: exact prefix plus exact payload, with no extra terminator or bytes.
    /// Scope: this wire oracle does not rely on our decoder agreeing with us.
    #[test]
    fn encodes_a_known_frame_without_changing_payload() {
        let payload = vec![b'x'; 258];
        let mut expected = vec![0, 0, 1, 2];
        expected.extend_from_slice(&payload);

        let encoded = rust_deskflow_core::framing::encode_frame(&payload, 1024)
            .expect("a permitted payload must encode");

        assert_eq!(encoded, expected);
        assert_eq!(payload, vec![b'x'; 258]);
    }

    /// Setup: five payload bytes include NUL, 0xff, 0x80, and 0x7f.
    /// Exercise: encode as bytes, not text or a null-terminated string.
    /// Expect: the fixed nine-byte frame, preserving each binary payload value.
    /// Scope: encoding must not introduce Unicode conversion or escaping.
    #[test]
    fn encoder_preserves_binary_payload_bytes() {
        let payload = [0, 255, 128, 0, 127];
        let encoded = rust_deskflow_core::framing::encode_frame(&payload, 1024).unwrap();
        assert_eq!(encoded, [0, 0, 0, 5, 0, 255, 128, 0, 127]);
    }

    /// Setup: a nonempty four-byte payload with limits of four, three, and zero.
    /// Exercise: encode once with each limit.
    /// Expect: exact wire bytes at four; declared=4 size errors for three and zero.
    /// Scope: a zero configured limit must not mean unlimited payload size.
    #[test]
    fn encoder_enforces_the_inclusive_payload_limit() {
        use rust_deskflow_core::framing::{FrameError, encode_frame};

        assert_eq!(encode_frame(b"CALV", 4).unwrap(), b"\0\0\0\x04CALV");
        for maximum in [0, 3] {
            assert_eq!(
                encode_frame(b"CALV", maximum).err(),
                Some(FrameError::PayloadTooLarge {
                    declared: 4,
                    maximum,
                })
            );
        }
    }
}

mod handshake {
    /// Setup: independently checked server/client greeting fixtures from the pin.
    /// Exercise: parse identifiers, big-endian versions, and client-name fields.
    /// Expect: exact field values and the following frame preserved by framing.
    /// Scope: parses payloads only; names are bytes and session readiness is separate.
    #[test]
    fn parses_supported_greeting_and_version() {
        use rust_deskflow_core::framing::decode_frame;
        use rust_deskflow_core::handshake::{
            ProtocolName, ProtocolVersion, parse_client_hello, parse_server_hello,
        };

        let version = ProtocolVersion { major: 1, minor: 8 };
        for (identifier, expected_protocol) in [
            (b"Barrier", ProtocolName::Barrier),
            (b"Synergy", ProtocolName::Synergy),
        ] {
            let mut server_payload = identifier.to_vec();
            server_payload.extend_from_slice(&[0, 1, 0, 8]);
            let server = parse_server_hello(&server_payload).unwrap();
            assert_eq!(server.protocol, expected_protocol);
            assert_eq!(server.version, version);

            let mut client_payload = server_payload;
            client_payload.extend_from_slice(&[0, 0, 0, 4, b'd', b'e', b's', b'k']);
            let client = parse_client_hello(&client_payload).unwrap();
            assert_eq!(client.protocol, expected_protocol);
            assert_eq!(client.version, version);
            assert_eq!(client.name, b"desk");
        }

        let input = b"\0\0\0\x0bBarrier\0\x01\0\x08\0\0\0\x04CALV";
        let frame = decode_frame(input, 1024).unwrap().unwrap();
        assert_eq!(parse_server_hello(frame.payload).unwrap().version, version);
        assert_eq!(frame.remaining, b"\0\0\0\x04CALV");

        let binary_name = b"Barrier\0\x01\0\x08\0\0\0\x02\xff\0";
        assert_eq!(parse_client_hello(binary_name).unwrap().name, &[255, 0]);
    }

    /// Setup: pinned client/server version matrices and a greeting before a data frame.
    /// Exercise: call pure role-specific version checks, including future server minors.
    /// Expect: client uses 1.6-1.8; server accepts replies 1.0-1.8; remainder untouched.
    /// Scope: no forwarding or closure API exists yet; session gating remains pending.
    #[test]
    fn rejects_unsupported_versions_without_forwarding_input() {
        use rust_deskflow_core::framing::decode_frame;
        use rust_deskflow_core::handshake::{
            HandshakeError, ProtocolVersion, negotiate_server_version, parse_server_hello,
            validate_client_version,
        };

        for minor in [6, 7, 8, 9, i16::MAX] {
            assert_eq!(
                negotiate_server_version(ProtocolVersion { major: 1, minor }),
                Ok(ProtocolVersion {
                    major: 1,
                    minor: minor.min(8),
                })
            );
        }
        for minor in 0..=8 {
            let version = ProtocolVersion { major: 1, minor };
            assert_eq!(validate_client_version(version), Ok(version));
        }
        for version in [
            ProtocolVersion { major: 0, minor: 8 },
            ProtocolVersion { major: 2, minor: 8 },
            ProtocolVersion {
                major: -1,
                minor: 8,
            },
            ProtocolVersion {
                major: 1,
                minor: -1,
            },
        ] {
            let expected = HandshakeError::UnsupportedVersion {
                major: version.major,
                minor: version.minor,
            };
            assert_eq!(negotiate_server_version(version).err(), Some(expected));
            assert!(validate_client_version(version).is_err());
        }
        for minor in 0..6 {
            assert!(negotiate_server_version(ProtocolVersion { major: 1, minor }).is_err());
        }
        assert!(validate_client_version(ProtocolVersion { major: 1, minor: 9 }).is_err());

        let input = b"\0\0\0\x0bBarrier\0\x02\0\x08\0\0\0\x04CALV";
        let frame = decode_frame(input, 1024).unwrap().unwrap();
        let hello = parse_server_hello(frame.payload).unwrap();
        assert!(negotiate_server_version(hello.version).is_err());
        assert_eq!(frame.remaining, b"\0\0\0\x04CALV");
    }

    /// Setup: incomplete greetings, invalid IDs/versions, trailing bytes, and length limits.
    /// Exercise: parse complete frame payloads directly, including a 1024-byte reply.
    /// Expect: metadata-only errors or exact-limit success without allocating names.
    /// Scope: strict trailing-byte/name bounds are local checks, not full session validation.
    #[test]
    fn rejects_malformed_or_oversized_greetings() {
        use rust_deskflow_core::handshake::{
            HandshakeError, MAX_HELLO_LENGTH, parse_client_hello, parse_server_hello,
        };

        let server = b"Barrier\0\x01\0\x08";
        let client = b"Barrier\0\x01\0\x08\0\0\0\x04desk";
        for received in 0..11 {
            assert_eq!(
                parse_server_hello(&server[..received]).err(),
                Some(HandshakeError::Truncated {
                    expected: 11,
                    received
                })
            );
        }
        for received in 0..client.len() {
            let expected = if received < 11 {
                11
            } else if received < 15 {
                15
            } else {
                19
            };
            assert_eq!(
                parse_client_hello(&client[..received]).err(),
                Some(HandshakeError::Truncated { expected, received })
            );
        }
        for payload in [b"Unknown\0\x01\0\x08".as_slice(), b"barrier\0\x01\0\x08"] {
            assert_eq!(
                parse_server_hello(payload).err(),
                Some(HandshakeError::InvalidProtocol)
            );
        }
        for (major, minor) in [(0_i16, 8_i16), (-1, 8), (1, -1)] {
            let mut payload = b"Barrier".to_vec();
            payload.extend_from_slice(&major.to_be_bytes());
            payload.extend_from_slice(&minor.to_be_bytes());
            assert_eq!(
                parse_server_hello(&payload).err(),
                Some(HandshakeError::InvalidVersion { major, minor })
            );
        }
        let mut trailing_server = server.to_vec();
        trailing_server.push(0);
        assert_eq!(
            parse_server_hello(&trailing_server).err(),
            Some(HandshakeError::TrailingBytes { count: 1 })
        );
        let mut trailing_client = client.to_vec();
        trailing_client.push(0);
        assert_eq!(
            parse_client_hello(&trailing_client).err(),
            Some(HandshakeError::TrailingBytes { count: 1 })
        );

        let mut bad_name = server.to_vec();
        bad_name.extend_from_slice(&u32::MAX.to_be_bytes());
        assert_eq!(
            parse_client_hello(&bad_name).err(),
            Some(HandshakeError::NameTooLarge {
                declared: u32::MAX,
                maximum: MAX_HELLO_LENGTH - 15
            })
        );
        let mut largest = server.to_vec();
        largest.extend_from_slice(&1009_u32.to_be_bytes());
        largest.extend_from_slice(&vec![b'n'; 1009]);
        assert_eq!(largest.len(), MAX_HELLO_LENGTH);
        assert_eq!(parse_client_hello(&largest).unwrap().name.len(), 1009);
        largest.push(b'n');
        assert_eq!(
            parse_client_hello(&largest).err(),
            Some(HandshakeError::HelloTooLarge {
                length: 1025,
                maximum: MAX_HELLO_LENGTH
            })
        );
    }
}

mod clipboard_policy {
    use super::session::{complete_handshake, ready_session};
    use rust_deskflow_core::clipboard::ClipboardPermissions;
    use rust_deskflow_core::framing::{decode_frame, encode_frame};
    use rust_deskflow_core::session::{Endpoint, Session, SessionState};

    fn other(endpoint: Endpoint) -> Endpoint {
        match endpoint {
            Endpoint::Server => Endpoint::Client,
            Endpoint::Client => Endpoint::Server,
        }
    }

    fn allow_both(session: &mut Session, generation: u64) {
        for endpoint in [Endpoint::Server, Endpoint::Client] {
            session
                .set_clipboard_permissions(
                    generation,
                    endpoint,
                    ClipboardPermissions {
                        send: true,
                        receive: true,
                    },
                )
                .unwrap();
        }
    }

    fn restrict_work(session: &mut Session, work: Endpoint, incoming: bool) {
        session
            .set_clipboard_permissions(
                1,
                work,
                ClipboardPermissions {
                    send: false,
                    receive: incoming,
                },
            )
            .unwrap();
    }

    fn chunk(id: u8, sequence: u32, mark: u8, data: &[u8]) -> Vec<u8> {
        let mut payload = b"DCLP".to_vec();
        payload.push(id);
        payload.extend_from_slice(&sequence.to_be_bytes());
        payload.push(mark);
        payload.extend_from_slice(&(data.len() as u32).to_be_bytes());
        payload.extend_from_slice(data);
        payload
    }

    fn transfer(id: u8, sequence: u32, format: u32, content: &[u8]) -> Vec<Vec<u8>> {
        let mut ownership = b"CCLP".to_vec();
        ownership.push(id);
        ownership.extend_from_slice(&sequence.to_be_bytes());
        let mut serialized = 1_u32.to_be_bytes().to_vec();
        serialized.extend_from_slice(&format.to_be_bytes());
        serialized.extend_from_slice(&(content.len() as u32).to_be_bytes());
        serialized.extend_from_slice(content);
        let split = serialized.len() / 2;
        vec![
            ownership,
            chunk(id, sequence, 1, serialized.len().to_string().as_bytes()),
            chunk(id, sequence, 2, &serialized[..split]),
            chunk(id, sequence, 2, &serialized[split..]),
            chunk(id, sequence, 3, &[]),
        ]
    }

    /// Setup: synthetic text, HTML, binary-image bytes, and X11 selection fixtures.
    /// Exercise: send through a work-to-personal path with outbound denial enabled.
    /// Expect: no content reaches the peer, including partial chunks or cached replay.
    /// Scope: inspect model output queues; OS clipboard and third-peer redistribution remain absent.
    #[test]
    fn blocks_work_to_personal_clipboard_content() {
        for work in [Endpoint::Server, Endpoint::Client] {
            for id in [0, 1] {
                for (format, content) in [
                    (0, b"my voice is my passport. Please, verify me.".as_slice()),
                    (1, b"<b>synthetic</b>"),
                    (2, b"BM\0\xff\x80synthetic"),
                ] {
                    let mut session = ready_session(1, 4096);
                    allow_both(&mut session, 1);
                    restrict_work(&mut session, work, true);
                    for payload in transfer(id, 0, format, content) {
                        session.receive(1, work, &payload).unwrap();
                        assert!(session.take_next(1, other(work)).unwrap().is_none());
                    }
                    assert_eq!(session.snapshot().state, SessionState::Ready);
                    assert_eq!(session.snapshot().queued_bytes, 0);
                }
            }
        }
    }

    /// Setup: identical personal-origin transfers with incoming permission on/off.
    /// Exercise: route them toward work while work's outgoing permission stays off.
    /// Expect: incoming allow forwards; incoming deny blocks; outbound denial persists.
    /// Scope: repeat when work changes server/client role; no incoming default assumed.
    #[test]
    fn applies_personal_to_work_policy_independently() {
        for work in [Endpoint::Server, Endpoint::Client] {
            for incoming in [true, false] {
                let mut session = ready_session(1, 4096);
                allow_both(&mut session, 1);
                restrict_work(&mut session, work, incoming);
                for payload in transfer(0, 0, 0, b"personal fixture") {
                    session.receive(1, other(work), &payload).unwrap();
                    let received = session.take_next(1, work).unwrap();
                    assert_eq!(
                        received,
                        incoming.then(|| encode_frame(&payload, 1024).unwrap())
                    );
                }
                for payload in transfer(0, 1, 0, b"work fixture") {
                    session.receive(1, work, &payload).unwrap();
                    assert!(session.take_next(1, other(work)).unwrap().is_none());
                }
                assert_eq!(session.snapshot().state, SessionState::Ready);
            }
        }
    }

    /// Setup: two permitted personal peers and representative clipboard content types.
    /// Exercise: route complete and chunked transfers through the policy boundary.
    /// Expect: byte/order preservation and correct transfer completion, without duplicates.
    /// Scope: independent restricted session coexists; no multi-peer redistribution or OS decoding.
    #[test]
    fn preserves_allowed_personal_to_personal_transfers() {
        let mut personal = ready_session(1, 4096);
        allow_both(&mut personal, 1);
        let mut restricted = ready_session(1, 4096);
        allow_both(&mut restricted, 1);
        restrict_work(&mut restricted, Endpoint::Client, true);
        for from in [Endpoint::Server, Endpoint::Client] {
            for id in [0, 1] {
                for (format, content) in [
                    (0, b"synthetic text".as_slice()),
                    (1, b"<p>HTML</p>"),
                    (2, b"BM\0\xffbinary"),
                ] {
                    let messages = transfer(id, 0, format, content);
                    for payload in &messages {
                        personal.receive(1, from, payload).unwrap();
                        restricted.receive(1, Endpoint::Client, payload).unwrap();
                        assert!(restricted.take_next(1, Endpoint::Server).unwrap().is_none());
                    }
                    for payload in &messages {
                        assert_eq!(
                            personal.take_next(1, other(from)).unwrap(),
                            Some(encode_frame(payload, 1024).unwrap())
                        );
                    }
                    assert!(personal.take_next(1, other(from)).unwrap().is_none());
                }
            }
        }
    }

    /// Setup: denied CCLP ownership and DCLP start/data/end payloads with sequence 7.
    /// Exercise: decode bytewise frames, duplicate completion, restart, and cancel midway.
    /// Expect: denied frames never queue; malformed/replayed tails close the model.
    /// Scope: no invented request/cancel packets, peer acknowledgments, or real timeout claim.
    #[test]
    fn denied_chunked_transfer_does_not_leak_partial_content() {
        let mut session = ready_session(1, 4096);
        allow_both(&mut session, 1);
        restrict_work(&mut session, Endpoint::Client, true);
        let messages = transfer(1, 7, 0, b"denied chunk fixture");
        let bytes: Vec<u8> = messages
            .iter()
            .flat_map(|payload| encode_frame(payload, 1024).unwrap())
            .collect();
        let mut accumulated = Vec::new();
        for byte in bytes {
            accumulated.push(byte);
            while let Some(frame) = decode_frame(&accumulated, 1024).unwrap() {
                session.receive(1, Endpoint::Client, frame.payload).unwrap();
                let consumed = accumulated.len() - frame.remaining.len();
                accumulated.drain(..consumed);
                assert!(session.take_next(1, Endpoint::Server).unwrap().is_none());
            }
        }
        assert!(accumulated.is_empty());
        assert_eq!(session.snapshot().state, SessionState::Ready);
        assert!(
            session
                .receive(1, Endpoint::Client, messages.last().unwrap())
                .is_err()
        );
        assert_eq!(session.snapshot().state, SessionState::Closed);
        session.restart(2).unwrap();
        complete_handshake(&mut session, 2);
        assert!(
            session
                .receive(2, Endpoint::Client, &chunk(1, 7, 2, b"old tail"))
                .is_err()
        );
        assert_eq!(session.snapshot().queued_bytes, 0);
        session.restart(3).unwrap();
        complete_handshake(&mut session, 3);
        for payload in &messages[..3] {
            session.receive(3, Endpoint::Client, payload).unwrap();
        }
        session.disconnect(3, Endpoint::Client).unwrap();
        session.restart(4).unwrap();
        complete_handshake(&mut session, 4);
        assert!(session.receive(4, Endpoint::Client, &messages[3]).is_err());
        assert_eq!(session.snapshot().queued_bytes, 0);
    }

    /// Setup: denied clipboard traffic interleaved with input and required control.
    /// Exercise: route synthetic press/release, motion, scroll, and keep-alive pairs.
    /// Expect: clipboard contents blocked; permitted messages retain bytes and order.
    /// Scope: both control directions; byte preservation does not prove physical key release.
    #[test]
    fn clipboard_denial_preserves_required_input_and_control() {
        let mut session = ready_session(1, 4096);
        allow_both(&mut session, 1);
        restrict_work(&mut session, Endpoint::Client, true);
        let input: &[&[u8]] = &[
            b"DKDL\0a\0\0\0\x1e\0\0\0\x02en",
            b"DKUP\0a\0\0\0\x1e",
            b"DMDN\x01",
            b"DMUP\x01",
            b"DMMV\0\x01\0\x02",
            b"DMWM\0\0\0\x01",
            b"CIAK",
            b"CALV",
            b"CNOP",
        ];
        for payload in transfer(0, 0, 0, b"blocked") {
            session.receive(1, Endpoint::Client, &payload).unwrap();
            assert!(session.take_next(1, Endpoint::Server).unwrap().is_none());
            for message in input {
                session.receive(1, Endpoint::Server, message).unwrap();
                assert_eq!(
                    session.take_next(1, Endpoint::Client).unwrap(),
                    Some(encode_frame(message, 1024).unwrap())
                );
            }
            for message in [b"CALV", b"CNOP"] {
                session.receive(1, Endpoint::Client, message).unwrap();
                assert_eq!(
                    session.take_next(1, Endpoint::Server).unwrap(),
                    Some(encode_frame(message, 1024).unwrap())
                );
            }
        }
        assert_eq!(session.snapshot().state, SessionState::Ready);
    }

    /// Setup: a local outbound denial and an otherwise authorized remote peer.
    /// Exercise: receive permissive clipboard options, reset-options, then reconnect.
    /// Expect: the effective rule remains deny and attempted transfers remain blocked.
    /// Scope: distinguish mandatory local restrictions from ordinary remote preferences.
    #[test]
    fn remote_options_cannot_relax_a_local_denial() {
        let mut session = ready_session(1, 4096);
        allow_both(&mut session, 1);
        restrict_work(&mut session, Endpoint::Client, true);
        for payload in [b"DSOP\0\0\0\x02CLPS\0\0\0\x01".as_slice(), b"CROP"] {
            session.receive(1, Endpoint::Server, payload).unwrap();
            session.take_next(1, Endpoint::Client).unwrap().unwrap();
        }
        for payload in transfer(0, 0, 0, b"still denied") {
            session.receive(1, Endpoint::Client, &payload).unwrap();
            assert!(session.take_next(1, Endpoint::Server).unwrap().is_none());
        }
        session.disconnect(1, Endpoint::Client).unwrap();
        session.restart(2).unwrap();
        complete_handshake(&mut session, 2);
        for payload in transfer(0, 1, 0, b"denied after restart") {
            session.receive(2, Endpoint::Client, &payload).unwrap();
            assert!(session.take_next(2, Endpoint::Server).unwrap().is_none());
        }
    }

    /// Setup: allowed transfers queued wholly/partly, or with a start already drained.
    /// Exercise: revoke source-send or destination-receive permission in either direction.
    /// Expect: unsent clipboard frames purge, input remains; drained start forces closure.
    /// Scope: take_next is the conservative cutover; adapter-held bytes cannot be recalled.
    #[test]
    fn policy_change_discards_now_prohibited_queued_content() {
        let messages = transfer(0, 0, 0, b"queued fixture");
        for from in [Endpoint::Server, Endpoint::Client] {
            for at_source in [true, false] {
                let endpoint = if at_source { from } else { other(from) };
                let permissions = ClipboardPermissions {
                    send: !at_source,
                    receive: at_source,
                };
                for cut in [3, messages.len()] {
                    let mut session = ready_session(1, 4096);
                    allow_both(&mut session, 1);
                    for payload in &messages[..cut] {
                        session.receive(1, from, payload).unwrap();
                    }
                    let control: &[u8] = if from == Endpoint::Server {
                        b"DMDN\x01"
                    } else {
                        b"CALV"
                    };
                    session.receive(1, from, control).unwrap();
                    session
                        .set_clipboard_permissions(1, endpoint, permissions)
                        .unwrap();
                    assert_eq!(
                        session.take_next(1, other(from)).unwrap(),
                        Some(encode_frame(control, 1024).unwrap())
                    );
                    for payload in &messages[cut..] {
                        session.receive(1, from, payload).unwrap();
                    }
                    assert!(session.take_next(1, other(from)).unwrap().is_none());
                    assert_eq!(session.snapshot().queued_bytes, 0);
                    assert_eq!(session.snapshot().state, SessionState::Ready);
                }
                let mut started = ready_session(1, 4096);
                allow_both(&mut started, 1);
                for payload in &messages[..2] {
                    started.receive(1, from, payload).unwrap();
                    started.take_next(1, other(from)).unwrap().unwrap();
                }
                started
                    .set_clipboard_permissions(1, endpoint, permissions)
                    .unwrap();
                assert_eq!(started.snapshot().state, SessionState::Closed);
                assert_eq!(started.snapshot().queued_bytes, 0);
            }
        }
    }

    /// Setup: allowed and default-denied ready sessions with malformed ownership and chunks.
    /// Exercise: send invalid IDs, lengths, marks, sizes, lifecycle order, or identity changes.
    /// Expect: close both logical endpoints and clear queues for every malformed transfer.
    /// Scope: strict local validation, not all permissive upstream parsing behavior.
    #[test]
    fn malformed_clipboard_messages_close_without_retaining_content() {
        let mut wrong_length = chunk(0, 0, 2, b"data");
        wrong_length[10..14].copy_from_slice(&u32::MAX.to_be_bytes());
        let malformed = vec![
            b"CCLP".to_vec(),
            b"CCLP\0\0\0\0\0x".to_vec(),
            b"CCLP\x02\0\0\0\0".to_vec(),
            chunk(2, 0, 1, b"0"),
            chunk(0, 0, 0, b""),
            chunk(0, 0, 4, b""),
            chunk(0, 0, 1, b""),
            chunk(0, 0, 1, b"-1"),
            chunk(0, 0, 1, b"+1"),
            chunk(0, 0, 1, b" 1"),
            chunk(0, 0, 1, b"18446744073709551616"),
            chunk(0, 0, 2, b"orphan"),
            chunk(0, 0, 3, b""),
            chunk(0, 0, 3, b"nonempty end"),
            wrong_length,
        ];
        for allowed in [false, true] {
            for payload in &malformed {
                let mut session = ready_session(1, 4096);
                if allowed {
                    allow_both(&mut session, 1);
                }
                assert!(session.receive(1, Endpoint::Client, payload).is_err());
                assert_eq!(session.snapshot().state, SessionState::Closed);
                assert_eq!(session.snapshot().endpoints_open, [false, false]);
                assert_eq!(session.snapshot().queued_bytes, 0);
            }
            for invalid_tail in [
                chunk(0, 0, 2, b"too much"),
                chunk(1, 0, 2, b"data"),
                chunk(0, 1, 2, b"data"),
                chunk(0, 0, 3, b""),
                chunk(0, 0, 1, b"4"),
            ] {
                let mut session = ready_session(1, 4096);
                if allowed {
                    allow_both(&mut session, 1);
                }
                session
                    .receive(1, Endpoint::Client, &chunk(0, 0, 1, b"4"))
                    .unwrap();
                assert!(session.receive(1, Endpoint::Client, &invalid_tail).is_err());
                assert_eq!(session.snapshot().state, SessionState::Closed);
                assert_eq!(session.snapshot().queued_bytes, 0);
            }
        }
        let mut session = Session::new(1, 1024, 4096);
        complete_handshake(&mut session, 1);
        let oversized = chunk(0, 0, 2, &[0; 1024]);
        assert!(matches!(
            session.receive(1, Endpoint::Client, &oversized),
            Err(rust_deskflow_core::session::SessionError::Framing(
                rust_deskflow_core::framing::FrameError::PayloadTooLarge { .. }
            ))
        ));
        assert_eq!(session.snapshot().state, SessionState::Closed);
    }

    /// Setup: a fresh session, then an explicitly restricted work endpoint and a restart.
    /// Exercise: send both ways by default, then try an old-generation permissive update.
    /// Expect: defaults deny both ways; stale updates fail and current restrictions persist.
    /// Scope: local configuration only; no remote endpoint identity or administrator UI.
    #[test]
    fn defaults_deny_and_stale_updates_cannot_relax_permissions() {
        let mut session = ready_session(1, 4096);
        for from in [Endpoint::Server, Endpoint::Client] {
            for payload in transfer(0, 0, 0, b"default denied") {
                session.receive(1, from, &payload).unwrap();
                assert!(session.take_next(1, other(from)).unwrap().is_none());
            }
        }
        allow_both(&mut session, 1);
        restrict_work(&mut session, Endpoint::Client, true);
        session.disconnect(1, Endpoint::Client).unwrap();
        session.restart(2).unwrap();
        complete_handshake(&mut session, 2);
        assert_eq!(
            session.set_clipboard_permissions(
                1,
                Endpoint::Client,
                ClipboardPermissions {
                    send: true,
                    receive: true
                }
            ),
            Err(rust_deskflow_core::session::SessionError::StaleGeneration)
        );
        for from in [Endpoint::Server, Endpoint::Client] {
            for payload in transfer(0, 1, 0, b"after restart") {
                session.receive(2, from, &payload).unwrap();
                assert_eq!(
                    session.take_next(2, other(from)).unwrap(),
                    (from == Endpoint::Server).then(|| encode_frame(&payload, 1024).unwrap())
                );
            }
        }
    }

    /// Setup: a denied transfer enabled halfway through, and a precisely budgeted queue.
    /// Exercise: finish the old transfer, start a new one, then exceed the allowed queue.
    /// Expect: no tail-only forwarding; only the new transfer passes; overflow closes/clears.
    /// Scope: encoded-byte queue bounds, not total transfer size, timeouts, or process memory.
    #[test]
    fn transfer_policy_is_sticky_and_clipboard_queues_are_bounded() {
        let messages = transfer(0, 0, 0, b"sticky fixture");
        let mut session = ready_session(1, 4096);
        for payload in &messages[..2] {
            session.receive(1, Endpoint::Client, payload).unwrap();
        }
        allow_both(&mut session, 1);
        for payload in &messages[2..] {
            session.receive(1, Endpoint::Client, payload).unwrap();
            assert!(session.take_next(1, Endpoint::Server).unwrap().is_none());
        }
        for payload in &messages {
            session.receive(1, Endpoint::Client, payload).unwrap();
            assert_eq!(
                session.take_next(1, Endpoint::Server).unwrap(),
                Some(encode_frame(payload, 1024).unwrap())
            );
        }
        let budget = messages.iter().map(|payload| payload.len() + 4).sum();
        let mut bounded = ready_session(1, budget);
        allow_both(&mut bounded, 1);
        for payload in &messages {
            bounded.receive(1, Endpoint::Client, payload).unwrap();
        }
        assert_eq!(bounded.snapshot().queued_bytes, budget);
        assert_eq!(
            bounded.receive(1, Endpoint::Client, &messages[0]),
            Err(rust_deskflow_core::session::SessionError::QueueLimit { maximum: budget })
        );
        assert_eq!(bounded.snapshot().state, SessionState::Closed);
        assert_eq!(bounded.snapshot().queued_bytes, 0);
    }
}

mod diagnostics {
    use std::time::Duration;

    use rust_deskflow_core::diagnostics::{
        Category, Direction, Event, EventKind, InputKind, InputOutcome, InputSummaryTracker, Level,
        LogRecorder, MemoryRecorder, Outcome, Reason, Record,
    };

    /// Setup: an in-memory log sink and synthetic allowed/denied transfer events.
    /// Exercise: emit events for both directions and each available verbosity level.
    /// Expect: category, endpoint-relative direction, outcome, and reason are usable.
    /// Scope: only approved metadata fields; never raw frames or unbounded peer strings.
    #[test]
    fn records_categories_direction_and_policy_outcome() {
        let mut recorder = MemoryRecorder::new(Level::Info);
        for level in [Level::Info, Level::Debug, Level::Trace] {
            recorder.record_event(Event {
                level,
                kind: EventKind::Message,
                category: Category::Clipboard,
                direction: Direction::ClientToServer,
                outcome: Outcome::Denied,
                reason: Reason::Policy,
            });
        }
        assert_eq!(recorder.records().len(), 3);
        for record in recorder.records() {
            assert!(matches!(
                record,
                Record::Event(Event {
                    category: Category::Clipboard,
                    direction: Direction::ClientToServer,
                    outcome: Outcome::Denied,
                    reason: Reason::Policy,
                    ..
                })
            ));
        }
        let mut debug = MemoryRecorder::new(Level::Debug);
        debug.record_event(Event {
            level: Level::Info,
            kind: EventKind::Message,
            category: Category::Session,
            direction: Direction::Local,
            outcome: Outcome::Disconnected,
            reason: Reason::PeerClosed,
        });
        debug.record_event(Event {
            level: Level::Debug,
            kind: EventKind::Message,
            category: Category::Control,
            direction: Direction::ServerToClient,
            outcome: Outcome::Forwarded,
            reason: Reason::NotApplicable,
        });
        assert_eq!(debug.records().len(), 1);
        assert!(matches!(
            debug.records()[0],
            Record::Event(Event {
                level: Level::Debug,
                ..
            })
        ));
    }

    /// Setup: a byte-vector sink, a fixed event, and an aggregate input summary.
    /// Exercise: write both records using the production text formatter.
    /// Expect: stable, payload-free lines with readable operational metadata.
    /// Scope: the sink formats approved diagnostic types only; it is not durable storage.
    #[test]
    fn writes_redacted_event_and_summary_lines() {
        let mut output = Vec::new();
        {
            let mut logger = LogRecorder::new(&mut output, Level::Info);
            logger
                .record_event(Event {
                    level: Level::Info,
                    kind: EventKind::Message,
                    category: Category::Clipboard,
                    direction: Direction::ServerToClient,
                    outcome: Outcome::Denied,
                    reason: Reason::Policy,
                })
                .unwrap();
            logger
                .record_summary(rust_deskflow_core::diagnostics::InputSummary {
                    window: Duration::from_secs(10),
                    keyboard_forwarded: 24,
                    keyboard_denied: 1,
                    pointer_forwarded: 3,
                    pointer_denied: 0,
                })
                .unwrap();
        }
        assert_eq!(
            String::from_utf8(output).unwrap(),
            concat!(
                "event level=info kind=message category=clipboard direction=server-to-client outcome=denied reason=policy\n",
                "input summary interval_ms=10000 keyboard_forwarded=24 keyboard_denied=1 pointer_forwarded=3 pointer_denied=0\n"
            )
        );
    }

    /// Setup: a writer that fails on every write and a logger filtered at debug.
    /// Exercise: submit below-threshold and accepted events, then force a sink error.
    /// Expect: filtered events are not written and I/O failures are returned.
    /// Scope: callers must handle sink errors; this test does not define retry policy.
    #[test]
    fn filters_by_verbosity_and_propagates_sink_errors() {
        use std::io::{self, Write};

        struct FailingWriter;

        impl Write for FailingWriter {
            fn write(&mut self, _buffer: &[u8]) -> io::Result<usize> {
                Err(io::Error::new(
                    io::ErrorKind::BrokenPipe,
                    "synthetic sink failure",
                ))
            }

            fn flush(&mut self) -> io::Result<()> {
                Ok(())
            }
        }

        let mut output = Vec::new();
        {
            let mut logger = LogRecorder::new(&mut output, Level::Debug);
            logger
                .record_event(Event {
                    level: Level::Info,
                    kind: EventKind::Message,
                    category: Category::Session,
                    direction: Direction::Local,
                    outcome: Outcome::Forwarded,
                    reason: Reason::NotApplicable,
                })
                .unwrap();
            logger
                .record_event(Event {
                    level: Level::Debug,
                    kind: EventKind::Message,
                    category: Category::Control,
                    direction: Direction::ClientToServer,
                    outcome: Outcome::Forwarded,
                    reason: Reason::NotApplicable,
                })
                .unwrap();
            logger
                .record_summary(rust_deskflow_core::diagnostics::InputSummary::default())
                .unwrap();
        }
        assert_eq!(
            String::from_utf8(output).unwrap(),
            "event level=debug kind=message category=control direction=client-to-server outcome=forwarded reason=not-applicable\n"
        );

        let mut failing = LogRecorder::new(FailingWriter, Level::Info);
        let error = failing
            .record_event(Event {
                level: Level::Info,
                kind: EventKind::Message,
                category: Category::Session,
                direction: Direction::Local,
                outcome: Outcome::Disconnected,
                reason: Reason::PeerClosed,
            })
            .unwrap_err();
        assert_eq!(error.kind(), io::ErrorKind::BrokenPipe);
    }

    /// Setup: the synthetic test phrase in clipboard and generated keyboard fixtures.
    /// Exercise: success, denial, malformed input, and disconnect at info/debug/trace.
    /// Expect: no phrase, constituent payload fields, hex/base64, or byte-array dumps.
    /// Scope: payload bytes never enter the logger; no durable or external sink is tested.
    #[test]
    fn excludes_synthetic_phrase_and_encoded_payloads_at_every_level() {
        let phrase = b"my voice is my passport. Please, verify me.";
        let clipboard_fixture = rust_deskflow_core::framing::encode_frame(phrase, 1024).unwrap();
        let hex = phrase
            .iter()
            .map(|byte| format!("{byte:02x}"))
            .collect::<String>();
        let base64 = "bXkgdm9pY2UgaXMgbXkgcGFzc3BvcnQuIFBsZWFzZSwgdmVyaWZ5IG1lLg==";
        for level in [Level::Info, Level::Debug, Level::Trace] {
            let mut recorder = MemoryRecorder::new(level);
            let mut logger = LogRecorder::new(Vec::new(), level);
            for (outcome, reason) in [
                (Outcome::Forwarded, Reason::NotApplicable),
                (Outcome::Denied, Reason::Policy),
                (Outcome::Rejected, Reason::Malformed),
                (Outcome::Disconnected, Reason::PeerClosed),
            ] {
                let event = Event {
                    level,
                    kind: EventKind::Message,
                    category: Category::Clipboard,
                    direction: Direction::ServerToClient,
                    outcome,
                    reason,
                };
                recorder.record_event(event);
                logger.record_event(event).unwrap();
            }
            let output = format!("{:?}", recorder.records());
            assert_eq!(recorder.records().len(), 4);
            assert!(!output.contains(std::str::from_utf8(phrase).unwrap()));
            assert!(!output.contains("passport"));
            assert!(!output.contains("Please"));
            assert!(!output.contains(&hex));
            assert!(!output.contains(base64));
            assert!(!output.contains("[109, 121, 32"));
            assert!(!output.contains(&format!("{clipboard_fixture:?}")));
            let log_output = String::from_utf8(logger.into_inner()).unwrap();
            assert!(!log_output.contains(std::str::from_utf8(phrase).unwrap()));
            assert!(!log_output.contains("passport"));
            assert!(!log_output.contains("Please"));
            assert!(!log_output.contains(&hex));
            assert!(!log_output.contains(base64));
            assert!(!log_output.contains("[109, 121, 32"));
            assert!(!log_output.contains(&format!("{clipboard_fixture:?}")));
        }
    }

    /// Setup: synthetic key-down/up/repeat sequences with explicit IDs and modifiers.
    /// Exercise: process them with a fake clock and the most verbose diagnostics.
    /// Expect: schema omits key values, key timing, scan codes, and modifier combinations.
    /// Scope: numeric-ID text searching alone is insufficient; inspect fields/record counts.
    #[test]
    fn excludes_key_identifiers_modifiers_and_per_keystroke_records() {
        let synthetic_key_frames: &[&[u8]] = &[
            b"DKDL\0a\0\0\0\x1e\0\0\0\x02en",
            b"DKUP\0a\0\0\0\x1e",
            b"DKRP\0a\0\0\0\x1e\0\0\0\x02en",
        ];
        assert_eq!(synthetic_key_frames.len(), 3);
        let mut tracker = InputSummaryTracker::new(Duration::from_secs(10), Duration::ZERO);
        for _frame in synthetic_key_frames {
            tracker.record(InputKind::Keyboard, InputOutcome::Forwarded);
        }
        let summary = tracker.take_due(Duration::from_secs(10)).unwrap();
        let mut recorder = MemoryRecorder::new(Level::Trace);
        recorder.record_summary(summary);
        let mut logger = LogRecorder::new(Vec::new(), Level::Trace);
        logger.record_summary(summary).unwrap();
        assert_eq!(recorder.records().len(), 1);
        assert_eq!(summary.keyboard_forwarded, 3);
        assert_eq!(summary.keyboard_denied, 0);
        assert_eq!(summary.pointer_forwarded, 0);
        assert_eq!(summary.pointer_denied, 0);
        let schema = format!("{summary:?}");
        for key_metadata in ["keycode", "scan_code", "modifiers", "timestamp"] {
            assert!(!schema.contains(key_metadata));
        }
        let output = format!("{:?}", recorder.records());
        for encoded_key in ["DKDL", "DKUP", "DKRP", "\\u{1e}", "0x1e"] {
            assert!(!output.contains(encoded_key));
        }
        let log_output = String::from_utf8(logger.into_inner()).unwrap();
        for key_metadata in ["keycode", "scan_code", "modifiers", "timestamp"] {
            assert!(!log_output.contains(key_metadata));
        }
        for encoded_key in ["DKDL", "DKUP", "DKRP", "\\u{1e}", "0x1e"] {
            assert!(!log_output.contains(encoded_key));
        }
    }

    /// Setup: a fake clock, fixed reporting interval, and known input event counts.
    /// Exercise: advance before/at/after the boundary, then reset or close the session.
    /// Expect: accurate interval summaries, no duplicate counting or per-key records.
    /// Scope: define press/release counting and allowed/blocked counter semantics first.
    #[test]
    fn emits_periodic_input_summaries_without_payloads() {
        let interval = Duration::from_secs(10);
        let mut tracker = InputSummaryTracker::new(interval, Duration::ZERO);
        tracker.record(InputKind::Keyboard, InputOutcome::Forwarded);
        tracker.record(InputKind::Keyboard, InputOutcome::Forwarded);
        tracker.record(InputKind::Keyboard, InputOutcome::Denied);
        tracker.record(InputKind::Pointer, InputOutcome::Forwarded);
        tracker.record(InputKind::Pointer, InputOutcome::Forwarded);
        tracker.record(InputKind::Pointer, InputOutcome::Denied);
        assert_eq!(tracker.take_due(Duration::from_secs(9)), None);
        let first = tracker.take_due(Duration::from_secs(10)).unwrap();
        assert_eq!(first.window, interval);
        assert_eq!(first.keyboard_forwarded, 2);
        assert_eq!(first.keyboard_denied, 1);
        assert_eq!(first.pointer_forwarded, 2);
        assert_eq!(first.pointer_denied, 1);
        assert_eq!(tracker.take_due(Duration::from_secs(10)), None);
        tracker.record(InputKind::Pointer, InputOutcome::Forwarded);
        assert_eq!(tracker.take_due(Duration::from_secs(19)), None);
        let second = tracker.take_due(Duration::from_secs(20)).unwrap();
        assert_eq!(second.pointer_forwarded, 1);
        assert_eq!(second.keyboard_forwarded, 0);
        tracker.record(InputKind::Keyboard, InputOutcome::Denied);
        tracker.reset(Duration::from_secs(20));
        tracker.record(InputKind::Keyboard, InputOutcome::Forwarded);
        assert_eq!(tracker.take_due(Duration::from_secs(29)), None);
        let reset = tracker.take_due(Duration::from_secs(30)).unwrap();
        assert_eq!(reset.keyboard_forwarded, 1);
        assert_eq!(reset.keyboard_denied, 0);
        assert_eq!(reset.pointer_forwarded, 0);
    }
}

mod session {
    use std::time::Duration;

    use rust_deskflow_core::diagnostics::{
        Category, Direction, Event, EventKind, Level, LogRecorder, MAX_PENDING_DIAGNOSTICS,
        Outcome, Reason, Record,
    };
    use rust_deskflow_core::framing::encode_frame;
    use rust_deskflow_core::session::{Endpoint, Session, SessionError, SessionState};

    const STARTUP: &[(Endpoint, &[u8])] = &[
        (Endpoint::Server, b"Barrier\0\x01\0\x08"),
        (Endpoint::Client, b"Barrier\0\x01\0\x08\0\0\0\x04desk"),
        (Endpoint::Server, b"QINF"),
        (
            Endpoint::Client,
            b"DINF\0\0\0\0\x07\x80\x04\x38\0\0\0\0\0\0",
        ),
        (Endpoint::Server, b"CIAK"),
        (Endpoint::Server, b"CROP"),
        (Endpoint::Server, b"DSOP\0\0\0\0"),
    ];

    pub(super) fn complete_handshake(session: &mut Session, generation: u64) {
        for (index, (from, payload)) in STARTUP.iter().enumerate() {
            session.receive(generation, *from, payload).unwrap();
            let destination = match from {
                Endpoint::Server => Endpoint::Client,
                Endpoint::Client => Endpoint::Server,
            };
            assert_eq!(
                session.take_next(generation, destination).unwrap(),
                Some(encode_frame(payload, 1024).unwrap())
            );
            assert_eq!(
                session.snapshot().state == SessionState::Ready,
                index == STARTUP.len() - 1
            );
        }
        assert_eq!(session.snapshot().queued_bytes, 0);
    }

    pub(super) fn ready_session(generation: u64, maximum_queued_bytes: usize) -> Session {
        let mut session = Session::new(generation, 1024, maximum_queued_bytes);
        complete_handshake(&mut session, generation);
        session
    }

    fn clipboard_transfer(content: &[u8]) -> [Vec<u8>; 4] {
        let ownership = b"CCLP\0\0\0\0\0".to_vec();
        let mut start = b"DCLP\0\x01\0\0\0\x01".to_vec();
        start.extend_from_slice(&(content.len().to_string().len() as u32).to_be_bytes());
        start.extend_from_slice(content.len().to_string().as_bytes());
        let mut data = b"DCLP\0\x01\0\0\0\x02".to_vec();
        data.extend_from_slice(&(content.len() as u32).to_be_bytes());
        data.extend_from_slice(content);
        let end = b"DCLP\0\x01\0\0\0\x03\0\0\0\0".to_vec();
        [ownership, start, data, end]
    }

    /// Setup: a synthetic clipboard phrase and both allowed and denied policies.
    /// Exercise: drive ownership and content chunks through ready sessions and format drained records.
    /// Expect: policy outcomes and lifecycle metadata are logged, never clipboard bytes.
    /// Scope: typed in-memory session diagnostics only; no live sink or transport is involved.
    #[test]
    fn session_diagnostics_capture_clipboard_outcomes_without_payloads() {
        let phrase = b"my voice is my passport. Please, verify me.";
        let hex = phrase
            .iter()
            .map(|byte| format!("{byte:02x}"))
            .collect::<String>();
        let base64 = "bXkgdm9pY2UgaXMgbXkgcGFzc3BvcnQuIFBsZWFzZSwgdmVyaWZ5IG1lLg==";
        let encoded_frame = format!(
            "{:?}",
            rust_deskflow_core::framing::encode_frame(phrase, 1024).unwrap()
        );
        let messages = clipboard_transfer(phrase);

        let mut denied = ready_session(1, 4096);
        for message in &messages {
            denied.receive(1, Endpoint::Server, message).unwrap();
            assert!(denied.take_next(1, Endpoint::Client).unwrap().is_none());
        }
        let denied_records = denied.take_diagnostics(Duration::ZERO);
        assert!(denied_records.records.iter().any(|record| matches!(
            record,
            Record::Event(Event {
                kind: EventKind::SessionOpened,
                category: Category::Session,
                ..
            })
        )));
        assert!(denied_records.records.iter().any(|record| matches!(
            record,
            Record::Event(Event {
                kind: EventKind::ProtocolNegotiated,
                category: Category::Control,
                ..
            })
        )));
        assert!(denied_records.records.iter().any(|record| matches!(
            record,
            Record::Event(Event {
                kind: EventKind::SessionReady,
                category: Category::Session,
                ..
            })
        )));
        assert!(denied_records.records.iter().any(|record| matches!(
            record,
            Record::Event(Event {
                kind: EventKind::Message,
                category: Category::Clipboard,
                direction: Direction::ServerToClient,
                outcome: Outcome::Denied,
                reason: Reason::Policy,
                ..
            })
        )));

        let mut allowed = ready_session(1, 4096);
        for endpoint in [Endpoint::Server, Endpoint::Client] {
            allowed
                .set_clipboard_permissions(
                    1,
                    endpoint,
                    rust_deskflow_core::clipboard::ClipboardPermissions {
                        send: true,
                        receive: true,
                    },
                )
                .unwrap();
        }
        for message in &messages {
            allowed.receive(1, Endpoint::Server, message).unwrap();
            assert!(allowed.take_next(1, Endpoint::Client).unwrap().is_some());
        }
        let allowed_records = allowed.take_diagnostics(Duration::ZERO);
        assert!(allowed_records.records.iter().any(|record| matches!(
            record,
            Record::Event(Event {
                category: Category::Clipboard,
                outcome: Outcome::Forwarded,
                reason: Reason::NotApplicable,
                ..
            })
        )));

        for records in [denied_records, allowed_records] {
            let mut output = Vec::new();
            {
                let mut logger = LogRecorder::new(&mut output, Level::Trace);
                for record in records.records {
                    match record {
                        Record::Event(event) => logger.record_event(event).unwrap(),
                        Record::InputSummary(summary) => logger.record_summary(summary).unwrap(),
                    }
                }
            }
            let output = String::from_utf8(output).unwrap();
            assert!(!output.contains(std::str::from_utf8(phrase).unwrap()));
            assert!(!output.contains("passport"));
            assert!(!output.contains(&hex));
            assert!(!output.contains(base64));
            assert!(!output.contains("[109, 121, 32"));
            assert!(!output.contains(&encoded_frame));
        }
    }

    /// Setup: a malformed clipboard frame, a full output queue, disconnect, and restart.
    /// Exercise: trigger each close path and drain only after starting a fresh generation.
    /// Expect: rejected and closed events retain causes, and restart adds a fresh-open event.
    /// Scope: local state transitions only; errors from an external log sink are handled by its caller.
    #[test]
    fn session_diagnostics_report_failures_and_preserve_records_across_restart() {
        let mut malformed = ready_session(1, 1024);
        assert_eq!(
            malformed.receive(1, Endpoint::Server, b"CCLP"),
            Err(SessionError::MalformedMessage)
        );
        let malformed_records = malformed.take_diagnostics(Duration::ZERO);
        assert!(malformed_records.records.iter().any(|record| matches!(
            record,
            Record::Event(Event {
                category: Category::Clipboard,
                outcome: Outcome::Rejected,
                reason: Reason::Malformed,
                ..
            })
        )));
        assert!(malformed_records.records.iter().any(|record| matches!(
            record,
            Record::Event(Event {
                category: Category::Session,
                outcome: Outcome::Disconnected,
                reason: Reason::Malformed,
                ..
            })
        )));

        let mut bounded = ready_session(1, 24);
        let motion = b"DMMV\0\x01\0\x02";
        bounded.receive(1, Endpoint::Server, motion).unwrap();
        bounded.receive(1, Endpoint::Server, motion).unwrap();
        assert_eq!(
            bounded.receive(1, Endpoint::Server, motion),
            Err(SessionError::QueueLimit { maximum: 24 })
        );
        bounded.disconnect(1, Endpoint::Client).unwrap();
        bounded.restart(2).unwrap();
        let records = bounded.take_diagnostics(Duration::ZERO);
        assert!(records.records.iter().any(|record| matches!(
            record,
            Record::Event(Event {
                category: Category::Control,
                outcome: Outcome::Rejected,
                reason: Reason::QueueLimit,
                ..
            })
        )));
        assert!(records.records.iter().any(|record| matches!(
            record,
            Record::Event(Event {
                category: Category::Session,
                outcome: Outcome::Disconnected,
                reason: Reason::QueueLimit,
                ..
            })
        )));
        assert!(records.records.iter().any(|record| matches!(
            record,
            Record::Event(Event {
                kind: EventKind::SessionRestarted,
                category: Category::Session,
                direction: Direction::Local,
                outcome: Outcome::Forwarded,
                reason: Reason::NotApplicable,
                ..
            })
        )));

        let mut disconnected = ready_session(1, 1024);
        disconnected.disconnect(1, Endpoint::Client).unwrap();
        disconnected.restart(2).unwrap();
        let records = disconnected.take_diagnostics(Duration::ZERO);
        assert!(records.records.iter().any(|record| matches!(
            record,
            Record::Event(Event {
                kind: EventKind::SessionClosed,
                category: Category::Session,
                outcome: Outcome::Disconnected,
                reason: Reason::PeerClosed,
                ..
            })
        )));
        assert!(records.records.iter().any(|record| matches!(
            record,
            Record::Event(Event {
                kind: EventKind::SessionRestarted,
                category: Category::Session,
                outcome: Outcome::Forwarded,
                ..
            })
        )));
    }

    /// Setup: a ready session with a bounded queue and a fake ten-second clock.
    /// Exercise: forward keyboard/pointer frames, overflow with pointer input, then drain at the boundary.
    /// Expect: one aggregate contains forwarded/denied counts and no per-input record or metadata.
    /// Scope: counts validated session input outcomes; no physical input or wall-clock source is modeled.
    #[test]
    fn session_input_diagnostics_emit_redacted_interval_summaries() {
        let mut session = ready_session(1, 64);
        let key_frame = b"DKDL\0a\0\0\0\x1e\0\0\0\x02en";
        let pointer_frame = b"DMDN\x01";
        for _ in 0..2 {
            session.receive(1, Endpoint::Server, key_frame).unwrap();
            session.receive(1, Endpoint::Server, pointer_frame).unwrap();
        }
        assert_eq!(
            session.receive(1, Endpoint::Server, pointer_frame),
            Err(SessionError::QueueLimit { maximum: 64 })
        );
        let records = session.take_diagnostics(Duration::from_secs(10));
        let summaries: Vec<_> = records
            .records
            .iter()
            .filter_map(|record| match record {
                Record::InputSummary(summary) => Some(summary),
                Record::Event(_) => None,
            })
            .collect();
        assert_eq!(summaries.len(), 1);
        assert_eq!(summaries[0].window, Duration::from_secs(10));
        assert_eq!(summaries[0].keyboard_forwarded, 2);
        assert_eq!(summaries[0].keyboard_denied, 0);
        assert_eq!(summaries[0].pointer_forwarded, 2);
        assert_eq!(summaries[0].pointer_denied, 1);
        assert!(!records.records.iter().any(|record| matches!(
            record,
            Record::Event(Event {
                category: Category::KeyboardInput | Category::PointerInput,
                ..
            })
        )));
        assert_eq!(
            session
                .take_diagnostics(Duration::from_secs(10))
                .records
                .iter()
                .filter(|record| matches!(record, Record::InputSummary(_)))
                .count(),
            0
        );

        let mut output = Vec::new();
        {
            let mut logger = LogRecorder::new(&mut output, Level::Trace);
            for record in records.records {
                match record {
                    Record::Event(event) => logger.record_event(event).unwrap(),
                    Record::InputSummary(summary) => logger.record_summary(summary).unwrap(),
                }
            }
        }
        let output = String::from_utf8(output).unwrap();
        for forbidden in ["DKDL", "keycode", "scan_code", "modifiers", "timestamp"] {
            assert!(!output.contains(forbidden));
        }

        let mut restarted = ready_session(1, 1024);
        restarted.take_diagnostics(Duration::ZERO);
        restarted.receive(1, Endpoint::Server, key_frame).unwrap();
        restarted.disconnect(1, Endpoint::Client).unwrap();
        restarted.restart(2).unwrap();
        complete_handshake(&mut restarted, 2);
        restarted
            .receive(2, Endpoint::Server, pointer_frame)
            .unwrap();
        let records = restarted.take_diagnostics(Duration::from_secs(10));
        let summary = records
            .records
            .iter()
            .find_map(|record| match record {
                Record::InputSummary(summary) => Some(summary),
                Record::Event(_) => None,
            })
            .unwrap();
        assert_eq!(summary.keyboard_forwarded, 1);
        assert_eq!(summary.pointer_forwarded, 1);
    }

    /// Setup: an allowed ready session and more than 5,000 synthetic ownership events.
    /// Exercise: generate events without draining the diagnostics buffer, then drain twice.
    /// Expect: the buffer stays capped, oldest records are dropped, and the exact drop count is reported once.
    /// Scope: validates the in-memory diagnostics cap, not external sink backpressure or retention.
    #[test]
    fn session_diagnostics_drop_oldest_records_at_the_configured_cap() {
        let mut session = ready_session(1, 1024);
        for endpoint in [Endpoint::Server, Endpoint::Client] {
            session
                .set_clipboard_permissions(
                    1,
                    endpoint,
                    rust_deskflow_core::clipboard::ClipboardPermissions {
                        send: true,
                        receive: true,
                    },
                )
                .unwrap();
        }
        session.take_diagnostics(Duration::ZERO);

        let generated = MAX_PENDING_DIAGNOSTICS + 7;
        for sequence in 0..generated {
            let mut ownership = b"CCLP\0".to_vec();
            ownership.extend_from_slice(&(sequence as u32).to_be_bytes());
            session.receive(1, Endpoint::Server, &ownership).unwrap();
            session.take_next(1, Endpoint::Client).unwrap().unwrap();
        }

        let batch = session.take_diagnostics(Duration::ZERO);
        assert_eq!(batch.records.len(), MAX_PENDING_DIAGNOSTICS);
        assert_eq!(batch.dropped_records, 7);
        assert!(batch.records.iter().all(|record| matches!(
            record,
            Record::Event(Event {
                category: Category::Clipboard,
                outcome: Outcome::Forwarded,
                ..
            })
        )));
        let next_batch = session.take_diagnostics(Duration::ZERO);
        assert!(next_batch.records.is_empty());
        assert_eq!(next_batch.dropped_records, 0);

        for sequence in 0..MAX_PENDING_DIAGNOSTICS {
            let mut ownership = b"CCLP\0".to_vec();
            ownership.extend_from_slice(&(sequence as u32).to_be_bytes());
            session.receive(1, Endpoint::Server, &ownership).unwrap();
            session.take_next(1, Endpoint::Client).unwrap().unwrap();
        }
        session.disconnect(1, Endpoint::Client).unwrap();
        session.restart(2).unwrap();
        let restarted_batch = session.take_diagnostics(Duration::ZERO);
        assert_eq!(restarted_batch.records.len(), MAX_PENDING_DIAGNOSTICS);
        assert_eq!(restarted_batch.dropped_records, 2);
        assert!(restarted_batch.records.iter().any(|record| matches!(
            record,
            Record::Event(Event {
                kind: EventKind::SessionRestarted,
                ..
            })
        )));
    }

    /// Setup: logical endpoints with queued synthetic press/release frames.
    /// Exercise: disconnect either logical endpoint with synthetic input queued.
    /// Expect: both states close, queues clear, and late queue operations cannot deliver bytes.
    /// Scope: in-memory model only; physical sockets and held-key release remain pending.
    #[test]
    fn disconnect_closes_both_endpoints_and_discards_queues() {
        for from in [Endpoint::Server, Endpoint::Client] {
            let mut session = ready_session(1, 1024);
            session.receive(1, Endpoint::Server, b"DMDN\x01").unwrap();
            session.receive(1, Endpoint::Server, b"DMUP\x01").unwrap();
            assert!(session.snapshot().queued_bytes > 0);
            session.disconnect(1, from).unwrap();
            let closed = session.snapshot();
            assert_eq!(closed.state, SessionState::Closed);
            assert_eq!(closed.endpoints_open, [false, false]);
            assert_eq!(closed.queued_bytes, 0);
            assert_eq!(
                session.take_next(1, Endpoint::Client),
                Err(SessionError::Closed)
            );
            assert_eq!(
                session.receive(1, Endpoint::Server, b"CALV"),
                Err(SessionError::Closed)
            );
            session.disconnect(1, from).unwrap();
            assert_eq!(session.snapshot(), closed);
        }
    }

    /// Setup: session A callbacks remain queued after A closes and session B starts.
    /// Exercise: deliver A's delayed disconnect, queue-drain, and input operations.
    /// Expect: B's state, queues, and counters remain unchanged.
    /// Scope: generation-tagged model operations, not real callbacks or policy state.
    #[test]
    fn stale_callbacks_do_not_modify_a_replacement_session() {
        let mut session = ready_session(1, 1024);
        let active = session.snapshot();
        assert_eq!(session.restart(2), Err(SessionError::AlreadyOpen));
        assert_eq!(session.snapshot(), active);
        session.receive(1, Endpoint::Server, b"DMDN\x01").unwrap();
        session.disconnect(1, Endpoint::Client).unwrap();
        assert_eq!(session.restart(1), Err(SessionError::InvalidGeneration));
        session.restart(2).unwrap();
        assert_eq!(session.snapshot().state, SessionState::AwaitServerHello);
        assert_eq!(session.snapshot().accepted_frames, 0);
        assert_eq!(session.snapshot().queued_bytes, 0);
        let fresh = session.snapshot();
        assert_eq!(
            session.receive(1, Endpoint::Server, b"DMDN\x01"),
            Err(SessionError::StaleGeneration)
        );
        assert_eq!(
            session.disconnect(1, Endpoint::Server),
            Err(SessionError::StaleGeneration)
        );
        assert_eq!(
            session.take_next(1, Endpoint::Client),
            Err(SessionError::StaleGeneration)
        );
        assert_eq!(session.snapshot(), fresh);
        complete_handshake(&mut session, 2);
        session.receive(2, Endpoint::Server, b"DMDN\x01").unwrap();
        let ready = session.snapshot();
        assert_eq!(
            session.disconnect(1, Endpoint::Server),
            Err(SessionError::StaleGeneration)
        );
        assert_eq!(
            session.take_next(1, Endpoint::Client),
            Err(SessionError::StaleGeneration)
        );
        assert_eq!(session.snapshot(), ready);
        assert_eq!(
            session.take_next(2, Endpoint::Client).unwrap(),
            Some(encode_frame(b"DMDN\x01", 1024).unwrap())
        );
    }

    /// Setup: a slow fake peer, explicit queue limits, and uniquely ordered frames.
    /// Exercise: fill to the byte limit, drain one frame, refill, then overflow.
    /// Expect: exact-limit FIFO behavior; overflow closes both states and clears queues.
    /// Scope: encoded queue bytes only, not total process memory or real transport buffering.
    #[test]
    fn backpressure_bounds_memory_and_preserves_order() {
        let mut session = ready_session(1, 24);
        let first = b"DMMV\0\x01\0\x02";
        let second = b"DMMV\0\x03\0\x04";
        let third = b"DMMV\0\x05\0\x06";
        session.receive(1, Endpoint::Server, first).unwrap();
        session.receive(1, Endpoint::Server, second).unwrap();
        assert_eq!(session.snapshot().queued_bytes, 24);
        assert_eq!(
            session.take_next(1, Endpoint::Client).unwrap(),
            Some(encode_frame(first, 1024).unwrap())
        );
        assert_eq!(session.snapshot().queued_bytes, 12);
        session.receive(1, Endpoint::Server, third).unwrap();
        assert_eq!(
            session.take_next(1, Endpoint::Client).unwrap(),
            Some(encode_frame(second, 1024).unwrap())
        );
        assert_eq!(
            session.take_next(1, Endpoint::Client).unwrap(),
            Some(encode_frame(third, 1024).unwrap())
        );
        assert_eq!(session.snapshot().queued_bytes, 0);
        session.receive(1, Endpoint::Server, first).unwrap();
        session.receive(1, Endpoint::Server, second).unwrap();
        assert_eq!(
            session.receive(1, Endpoint::Server, third),
            Err(SessionError::QueueLimit { maximum: 24 })
        );
        assert_eq!(session.snapshot().state, SessionState::Closed);
        assert_eq!(session.snapshot().queued_bytes, 0);
        assert_eq!(session.snapshot().endpoints_open, [false, false]);
    }

    /// Setup: sessions awaiting handshake, forwarding, denying a transfer, and closing.
    /// Exercise: inject early input, malformed controls, mismatched greetings, and unknown data.
    /// Expect: rejection/closure; only a validated 1.8 startup reaches Ready.
    /// Scope: includes malformed clipboard data; valid clipboard behavior is tested separately.
    #[test]
    fn unexpected_messages_do_not_bypass_handshake_or_policy() {
        let mut early = Session::new(1, 1024, 1024);
        assert!(early.receive(1, Endpoint::Server, b"DMDN\x01").is_err());
        assert_eq!(early.snapshot().state, SessionState::Closed);
        let mut mismatched = Session::new(1, 1024, 1024);
        mismatched
            .receive(1, Endpoint::Server, b"Barrier\0\x01\0\x08")
            .unwrap();
        assert_eq!(
            mismatched.receive(1, Endpoint::Client, b"Synergy\0\x01\0\x08\0\0\0\x04desk"),
            Err(SessionError::ProtocolMismatch)
        );
        let mut legacy = Session::new(1, 1024, 1024);
        assert_eq!(
            legacy.receive(1, Endpoint::Server, b"Barrier\0\x01\0\x07"),
            Err(SessionError::UnsupportedVersion)
        );

        let mut startup = Session::new(1, 1024, 1024);
        startup
            .receive(1, Endpoint::Server, b"Barrier\0\x01\0\x08")
            .unwrap();
        startup
            .receive(1, Endpoint::Client, b"Barrier\0\x01\0\x08\0\0\0\x04desk")
            .unwrap();
        assert_ne!(startup.snapshot().state, SessionState::Ready);
        startup.receive(1, Endpoint::Server, b"CALV").unwrap();
        assert_ne!(startup.snapshot().state, SessionState::Ready);
        assert!(startup.receive(1, Endpoint::Server, b"DMDN\x01").is_err());
        assert_eq!(startup.snapshot().queued_bytes, 0);

        for (from, invalid) in [
            (Endpoint::Server, b"JUNK".as_slice()),
            (Endpoint::Server, b"DMDN"),
            (Endpoint::Client, b"DMDN\x01"),
            (Endpoint::Server, b"DSOP\0\0\0\x01\0\0\0\0"),
            (Endpoint::Client, b"DCLP\0\0\0\0\0\0\0\0\0\x01x"),
        ] {
            let mut session = ready_session(1, 1024);
            assert!(session.receive(1, from, invalid).is_err());
            assert_eq!(session.snapshot().state, SessionState::Closed);
            assert_eq!(session.snapshot().queued_bytes, 0);
        }
        let mut ready = ready_session(1, 1024);
        ready.receive(1, Endpoint::Server, b"DMDN\x01").unwrap();
        ready.receive(1, Endpoint::Server, b"DMUP\x01").unwrap();
        assert_eq!(ready.snapshot().state, SessionState::Ready);
        ready.receive(1, Endpoint::Client, b"CALV").unwrap();
        assert_eq!(
            ready.take_next(1, Endpoint::Server).unwrap(),
            Some(encode_frame(b"CALV", 1024).unwrap())
        );
    }

    /// Setup: each incomplete prefix of the valid startup exchange.
    /// Exercise: inject input at every pre-ready state and send DSOP out of order.
    /// Expect: closure and empty queues; invalid display sizes cannot reach Ready.
    /// Scope: readiness is the local strict startup policy, not all upstream sequences.
    #[test]
    fn input_remains_blocked_at_every_pre_ready_stage() {
        for received in 0..STARTUP.len() {
            let mut session = Session::new(1, 1024, 1024);
            for (from, payload) in &STARTUP[..received] {
                session.receive(1, *from, payload).unwrap();
            }
            assert_ne!(session.snapshot().state, SessionState::Ready);
            assert!(session.receive(1, Endpoint::Server, b"DMDN\x01").is_err());
            assert_eq!(session.snapshot().state, SessionState::Closed);
            assert_eq!(session.snapshot().queued_bytes, 0);
        }
        for received in 2..5 {
            let mut session = Session::new(1, 1024, 1024);
            for (from, payload) in &STARTUP[..received] {
                session.receive(1, *from, payload).unwrap();
            }
            assert_eq!(
                session.receive(1, Endpoint::Server, b"DSOP\0\0\0\0"),
                Err(SessionError::UnexpectedMessage)
            );
            assert_eq!(session.snapshot().state, SessionState::Closed);
        }
        let mut session = Session::new(1, 1024, 1024);
        for (from, payload) in &STARTUP[..3] {
            session.receive(1, *from, payload).unwrap();
        }
        assert_eq!(
            session.receive(1, Endpoint::Client, b"DINF\0\0\0\0\0\0\0\0\0\0\0\0\0\0"),
            Err(SessionError::MalformedMessage)
        );
        assert_eq!(session.snapshot().state, SessionState::Closed);
    }

    /// Setup: protocol-1.8 key, pointer, entry/leave, and options payload fixtures.
    /// Exercise: queue valid messages, then repeat each with an extra trailing byte.
    /// Expect: exact encoded bytes for supported inputs; malformed variants close.
    /// Scope: structural validation only; key mapping and option application are absent.
    #[test]
    fn ready_input_messages_require_exact_lengths() {
        let payloads: &[&[u8]] = &[
            b"DKDL\0a\0\0\0\x1e\0\0\0\x02en",
            b"DKRP\0a\0\0\0\x02\0\x1e\0\0\0\x02en",
            b"DKUP\0a\0\0\0\x1e",
            b"DMDN\x01",
            b"DMUP\x01",
            b"DMMV\0\x01\0\x02",
            b"DMRM\0\x01\0\x02",
            b"DMWM\0\x01\0\x02",
            b"CINN\0\0\0\0\0\0\0\x01\0\0",
            b"COUT",
            b"CROP",
            b"DSOP\0\0\0\x02\0\0\0\x01\0\0\0\0",
        ];
        for payload in payloads {
            let mut session = ready_session(1, 1024);
            session.receive(1, Endpoint::Server, payload).unwrap();
            assert_eq!(session.snapshot().state, SessionState::Ready);
            assert_eq!(
                session.take_next(1, Endpoint::Client).unwrap(),
                Some(encode_frame(payload, 1024).unwrap())
            );
            let mut malformed = payload.to_vec();
            malformed.push(0);
            assert_eq!(
                session.receive(1, Endpoint::Server, &malformed),
                Err(SessionError::MalformedMessage)
            );
            assert_eq!(session.snapshot().state, SessionState::Closed);
        }
        let mut session = ready_session(1, 1024);
        session.receive(1, Endpoint::Server, b"CBYE").unwrap();
        assert_eq!(session.snapshot().state, SessionState::Closed);
        assert_eq!(session.snapshot().endpoints_open, [false, false]);
    }

    /// Setup: a shared 32-byte queue budget, a zero budget, and a small payload limit.
    /// Exercise: mix both directions at the limit and overflow during startup or Ready.
    /// Expect: one combined encoded-byte budget and clean closure on each failure.
    /// Scope: excludes allocator overhead, transport-owned frames, and total process memory.
    #[test]
    fn queue_limits_cover_both_directions_and_startup() {
        let mut session = ready_session(1, 32);
        session
            .receive(1, Endpoint::Server, b"DMMV\0\x01\0\x02")
            .unwrap();
        session.receive(1, Endpoint::Client, b"CALV").unwrap();
        session
            .receive(1, Endpoint::Server, b"DMMV\0\x03\0\x04")
            .unwrap();
        assert_eq!(session.snapshot().queued_bytes, 32);
        assert_eq!(
            session.receive(1, Endpoint::Client, b"CALV"),
            Err(SessionError::QueueLimit { maximum: 32 })
        );
        assert_eq!(session.snapshot().queued_bytes, 0);
        assert_eq!(session.snapshot().endpoints_open, [false, false]);

        let mut no_queue = Session::new(1, 1024, 0);
        assert_eq!(
            no_queue.receive(1, Endpoint::Server, STARTUP[0].1),
            Err(SessionError::QueueLimit { maximum: 0 })
        );
        assert_eq!(no_queue.snapshot().state, SessionState::Closed);

        let mut limited = Session::new(1, 18, 1024);
        limited.receive(1, Endpoint::Server, STARTUP[0].1).unwrap();
        assert_eq!(
            limited.receive(1, Endpoint::Client, STARTUP[1].1),
            Err(SessionError::Framing(
                rust_deskflow_core::framing::FrameError::PayloadTooLarge {
                    declared: 19,
                    maximum: 18
                }
            ))
        );
        assert_eq!(limited.snapshot().queued_bytes, 0);
        assert_eq!(limited.snapshot().state, SessionState::Closed);
    }
}

mod transport {
    use std::io::{Read, Write};
    use std::net::{IpAddr, Ipv4Addr, Shutdown, SocketAddr, TcpListener, TcpStream};
    use std::time::Duration;

    use rust_deskflow_core::diagnostics::{EventKind, Reason, Record};
    use rust_deskflow_core::framing::{FrameError, encode_frame};
    use rust_deskflow_core::session::Session;
    use rust_deskflow_core::transport::{
        CancellationToken, FrameBuffer, LoopbackForwarder, SESSION_IDLE_TIMEOUT, TransportError,
        TransportTimeouts, forward_session, forward_session_cancellable,
        forward_session_with_timeouts_cancellable,
    };

    /// Setup: concatenate two frames and split the bytes across three reads.
    /// Exercise: feed each fragment to the bounded stream decoder.
    /// Expect: exactly two unchanged payloads in original order.
    /// Scope: arbitrary stream read boundaries do not define frame boundaries.
    #[test]
    fn buffers_fragmented_and_coalesced_frames() {
        let mut decoder = FrameBuffer::new(32);
        let mut frames = decoder.push(&[0, 0]).unwrap();
        frames.extend(decoder.push(&[0, 4, b'C']).unwrap());
        frames.extend(
            decoder
                .push(&[b'A', b'L', b'V', 0, 0, 0, 4, b'C', b'N', b'O', b'P'])
                .unwrap(),
        );

        assert_eq!(frames, [b"CALV".to_vec(), b"CNOP".to_vec()]);
        decoder.finish().unwrap();
    }

    /// Setup: provide only an oversized four-byte frame header.
    /// Exercise: feed it to a decoder with a 16-byte payload limit.
    /// Expect: reject the declared length without waiting for its body.
    /// Scope: frame buffering never allocates the declared oversized payload.
    #[test]
    fn rejects_oversized_frame_before_receiving_its_payload() {
        let mut decoder = FrameBuffer::new(16);
        assert_eq!(
            decoder.push(&[0, 0, 0, 17]),
            Err(FrameError::PayloadTooLarge {
                declared: 17,
                maximum: 16,
            })
        );
    }

    /// Setup: supply an incomplete header, then an incomplete declared payload.
    /// Exercise: report end-of-stream after each partial frame.
    /// Expect: distinguish TruncatedHeader from TruncatedPayload.
    /// Scope: incomplete input is tolerated until EOF is explicitly observed.
    #[test]
    fn reports_truncated_frames_at_end_of_stream() {
        let mut header = FrameBuffer::new(16);
        header.push(&[0, 0]).unwrap();
        assert_eq!(
            header.finish(),
            Err(FrameError::TruncatedHeader { received: 2 })
        );

        let mut payload = FrameBuffer::new(16);
        payload.push(&[0, 0, 0, 4, b'C']).unwrap();
        assert_eq!(
            payload.finish(),
            Err(FrameError::TruncatedPayload {
                declared: 4,
                received: 1,
            })
        );
    }

    /// Setup: connect two loopback TCP pairs and a fresh protocol-1.8 session.
    /// Exercise: complete startup, then send coalesced pointer frames and CBYE.
    /// Expect: accepted frames cross the bridge unchanged and in order.
    /// Scope: local transport behavior only; no live Deskflow peer is exercised.
    #[test]
    fn forwards_session_frames_over_loopback_tcp() {
        let (mut server_peer, server_bridge) = connected_tcp_pair();
        let (client_peer, client_bridge) = connected_tcp_pair();
        set_read_timeout(&server_peer);
        set_read_timeout(&client_peer);

        let bridge = std::thread::spawn(move || {
            let mut session = Session::new(1, 1024, 16_384);
            forward_session(server_bridge, client_bridge, &mut session, 1)
        });

        send_frame(&server_peer, b"Barrier\0\x01\0\x08");
        expect_frame(&client_peer, b"Barrier\0\x01\0\x08");
        send_frame(&client_peer, b"Barrier\0\x01\0\x08\0\0\0\0");
        expect_frame(&server_peer, b"Barrier\0\x01\0\x08\0\0\0\0");
        send_frame(&server_peer, b"QINF");
        expect_frame(&client_peer, b"QINF");

        let mut client_info = vec![0; 18];
        client_info[..4].copy_from_slice(b"DINF");
        client_info[8..10].copy_from_slice(&1920_i16.to_be_bytes());
        client_info[10..12].copy_from_slice(&1080_i16.to_be_bytes());
        send_frame(&client_peer, &client_info);
        expect_frame(&server_peer, &client_info);
        send_frame(&server_peer, b"CIAK");
        expect_frame(&client_peer, b"CIAK");
        send_frame(&server_peer, b"DSOP\0\0\0\0");
        expect_frame(&client_peer, b"DSOP\0\0\0\0");

        let mut coalesced = encode_frame(b"DMDN\0", 1024).unwrap();
        coalesced.extend_from_slice(&encode_frame(b"DMUP\0", 1024).unwrap());
        server_peer.write_all(&coalesced).unwrap();
        expect_frame(&client_peer, b"DMDN\0");
        expect_frame(&client_peer, b"DMUP\0");

        send_frame(&server_peer, b"CBYE");
        bridge.join().unwrap().unwrap();
        let mut trailing = [0];
        assert_eq!(client_peer.peek(&mut trailing).unwrap(), 0);
    }

    /// Setup: start a bridge, then close one loopback peer with a partial header.
    /// Exercise: shut down its write half to signal EOF.
    /// Expect: the bridge returns a framing error instead of a clean disconnect.
    /// Scope: invalid/truncated streams close the session and are surfaced.
    #[test]
    fn surfaces_truncated_tcp_frames() {
        let (mut server_peer, server_bridge) = connected_tcp_pair();
        let (client_peer, client_bridge) = connected_tcp_pair();
        set_read_timeout(&client_peer);
        let bridge = std::thread::spawn(move || {
            let mut session = Session::new(1, 1024, 16_384);
            forward_session(server_bridge, client_bridge, &mut session, 1)
        });

        server_peer.write_all(&[0, 0]).unwrap();
        server_peer.shutdown(Shutdown::Write).unwrap();

        assert!(matches!(
            bridge.join().unwrap(),
            Err(TransportError::Frame(FrameError::TruncatedHeader {
                received: 2
            }))
        ));
        let mut byte = [0];
        assert_eq!(client_peer.peek(&mut byte).unwrap(), 0);
    }

    /// Setup: bind paired endpoint listeners on ephemeral loopback ports.
    /// Exercise: run two sessions with increasing generations through one runner.
    /// Expect: both complete a fresh handshake and close independently.
    /// Scope: listener lifecycle only; no Deskflow process or remote interface is used.
    #[test]
    fn accepts_repeated_peers_with_fresh_sessions() {
        let runner = std::sync::Arc::new(
            LoopbackForwarder::bind(
                SocketAddr::new(IpAddr::V4(Ipv4Addr::LOCALHOST), 0),
                SocketAddr::new(IpAddr::V4(Ipv4Addr::LOCALHOST), 0),
                1024,
                16_384,
            )
            .unwrap(),
        );
        let (server_address, client_address) = runner.local_addrs().unwrap();
        assert!(server_address.ip().is_loopback());
        assert!(client_address.ip().is_loopback());

        for generation in 1..=2 {
            let runner = std::sync::Arc::clone(&runner);
            let bridge = std::thread::spawn(move || runner.run_once(generation));
            let server_peer = TcpStream::connect(server_address).unwrap();
            let client_peer = TcpStream::connect(client_address).unwrap();
            set_read_timeout(&server_peer);
            set_read_timeout(&client_peer);
            complete_tcp_handshake(&server_peer, &client_peer);
            send_frame(&server_peer, b"CBYE");
            bridge.join().unwrap().unwrap();

            let mut byte = [0];
            assert_eq!(client_peer.peek(&mut byte).unwrap(), 0);
        }
    }

    /// Setup: start a runner without connecting either loopback peer.
    /// Exercise: cancel its paired-peer accept wait.
    /// Expect: return a distinct cancellation result promptly.
    /// Scope: cancellation wakes polling accepts; it is not a peer-pair timeout.
    #[test]
    fn cancels_while_waiting_for_loopback_peers() {
        let runner = std::sync::Arc::new(
            LoopbackForwarder::bind(
                SocketAddr::new(IpAddr::V4(Ipv4Addr::LOCALHOST), 0),
                SocketAddr::new(IpAddr::V4(Ipv4Addr::LOCALHOST), 0),
                1024,
                16_384,
            )
            .unwrap(),
        );
        let cancellation = CancellationToken::new();
        let worker_cancellation = cancellation.clone();
        let worker_runner = std::sync::Arc::clone(&runner);
        let worker =
            std::thread::spawn(move || worker_runner.run_once_cancellable(1, &worker_cancellation));

        std::thread::sleep(Duration::from_millis(30));
        cancellation.cancel();
        assert!(matches!(
            worker.join().unwrap(),
            Err(TransportError::Cancelled)
        ));
    }

    /// Setup: bind a forwarder with a short pair deadline and connect one peer.
    /// Exercise: leave the second listener without a peer until the shared deadline expires.
    /// Expect: return the distinct pairing timeout and close the accepted first stream.
    /// Scope: the deadline covers both accepts together, not 30 seconds per listener.
    #[test]
    fn times_out_while_waiting_for_the_second_peer() {
        let runner = std::sync::Arc::new(
            LoopbackForwarder::bind_with_timeouts(
                SocketAddr::new(IpAddr::V4(Ipv4Addr::LOCALHOST), 0),
                SocketAddr::new(IpAddr::V4(Ipv4Addr::LOCALHOST), 0),
                1024,
                16_384,
                TransportTimeouts {
                    pair: Duration::from_millis(100),
                    handshake: Duration::from_secs(1),
                    incomplete_frame: Duration::from_secs(1),
                },
            )
            .unwrap(),
        );
        let (server_address, _) = runner.local_addrs().unwrap();
        let bridge = std::thread::spawn({
            let runner = std::sync::Arc::clone(&runner);
            move || runner.run_once(1)
        });
        let server_peer = TcpStream::connect(server_address).unwrap();
        set_read_timeout(&server_peer);

        assert!(matches!(
            bridge.join().unwrap(),
            Err(TransportError::PairTimedOut)
        ));
        let mut byte = [0];
        assert_eq!(server_peer.peek(&mut byte).unwrap(), 0);
    }

    /// Setup: connect two loopback streams and configure a short handshake deadline.
    /// Exercise: send no protocol messages before the deadline expires.
    /// Expect: report a handshake timeout and close both peer streams.
    /// Scope: uses injected timing for deterministic offline coverage.
    #[test]
    fn times_out_before_session_handshake_completes() {
        let (server_peer, server_bridge) = connected_tcp_pair();
        let (client_peer, client_bridge) = connected_tcp_pair();
        set_read_timeout(&server_peer);
        set_read_timeout(&client_peer);
        let timeouts = TransportTimeouts {
            pair: Duration::from_secs(1),
            handshake: Duration::from_millis(100),
            incomplete_frame: Duration::from_secs(1),
        };
        let bridge = std::thread::spawn(move || {
            let mut session = Session::new(1, 1024, 16_384);
            let result = forward_session_with_timeouts_cancellable(
                server_bridge,
                client_bridge,
                &mut session,
                1,
                &CancellationToken::new(),
                timeouts,
            );
            (result, session.take_diagnostics(Duration::ZERO))
        });

        let (result, diagnostics) = bridge.join().unwrap();
        assert!(matches!(result, Err(TransportError::HandshakeTimedOut)));
        assert!(diagnostics.records.iter().any(|record| matches!(
            record,
            Record::Event(event)
                if event.kind == EventKind::SessionClosed
                    && event.reason == Reason::HandshakeTimeout
        )));
        let mut byte = [0];
        assert_eq!(server_peer.peek(&mut byte).unwrap(), 0);
        assert_eq!(client_peer.peek(&mut byte).unwrap(), 0);
    }

    /// Setup: connect two loopback streams with a short incomplete-frame deadline.
    /// Exercise: send an incomplete frame header and leave it unfinished.
    /// Expect: report a distinct incomplete-frame timeout and close both streams.
    /// Scope: the deadline begins on the first byte and is independent of handshake expiry.
    #[test]
    fn times_out_when_a_frame_remains_incomplete() {
        let (mut server_peer, server_bridge) = connected_tcp_pair();
        let (client_peer, client_bridge) = connected_tcp_pair();
        set_read_timeout(&server_peer);
        set_read_timeout(&client_peer);
        let timeouts = TransportTimeouts {
            pair: Duration::from_secs(1),
            handshake: Duration::from_secs(1),
            incomplete_frame: Duration::from_millis(100),
        };
        let bridge = std::thread::spawn(move || {
            let mut session = Session::new(1, 1024, 16_384);
            let result = forward_session_with_timeouts_cancellable(
                server_bridge,
                client_bridge,
                &mut session,
                1,
                &CancellationToken::new(),
                timeouts,
            );
            (result, session.take_diagnostics(Duration::ZERO))
        });
        server_peer.write_all(&[0, 0]).unwrap();

        let (result, diagnostics) = bridge.join().unwrap();
        assert!(matches!(
            result,
            Err(TransportError::IncompleteFrameTimedOut)
        ));
        assert!(diagnostics.records.iter().any(|record| matches!(
            record,
            Record::Event(event)
                if event.kind == EventKind::SessionClosed
                    && event.reason == Reason::IncompleteFrameTimeout
        )));
        let mut byte = [0];
        assert_eq!(server_peer.peek(&mut byte).unwrap(), 0);
        assert_eq!(client_peer.peek(&mut byte).unwrap(), 0);
    }

    /// Setup: start an established loopback bridge with no further peer traffic.
    /// Exercise: complete the synthetic handshake and wait for three 3-second intervals.
    /// Expect: close both streams and report a session keepalive timeout at nine seconds.
    /// Scope: scheduling tolerance is broad; the fixed timeout follows pinned protocol behavior.
    #[test]
    fn times_out_after_three_missed_keepalive_intervals() {
        assert_eq!(SESSION_IDLE_TIMEOUT, Duration::from_secs(9));
        let (server_peer, server_bridge) = connected_tcp_pair();
        let (client_peer, client_bridge) = connected_tcp_pair();
        set_read_timeout(&server_peer);
        set_read_timeout(&client_peer);
        let bridge = std::thread::spawn(move || {
            let mut session = Session::new(1, 1024, 16_384);
            forward_session(server_bridge, client_bridge, &mut session, 1)
        });

        complete_tcp_handshake(&server_peer, &client_peer);
        assert!(matches!(
            bridge.join().unwrap(),
            Err(TransportError::SessionTimedOut)
        ));

        let mut byte = [0];
        assert_eq!(server_peer.peek(&mut byte).unwrap(), 0);
        assert_eq!(client_peer.peek(&mut byte).unwrap(), 0);
    }

    /// Setup: start an active bridge over two loopback TCP pairs.
    /// Exercise: cancel after the forward loop begins polling for input.
    /// Expect: return a distinct cancellation result and close both peer streams.
    /// Scope: cancellation does not terminate the worker thread or bypass TCP shutdown.
    #[test]
    fn cancels_active_forwarding_and_shuts_down_both_peers() {
        let (server_peer, server_bridge) = connected_tcp_pair();
        let (client_peer, client_bridge) = connected_tcp_pair();
        set_read_timeout(&server_peer);
        set_read_timeout(&client_peer);
        let cancellation = CancellationToken::new();
        let worker_cancellation = cancellation.clone();
        let bridge = std::thread::spawn(move || {
            let mut session = Session::new(1, 1024, 16_384);
            forward_session_cancellable(
                server_bridge,
                client_bridge,
                &mut session,
                1,
                &worker_cancellation,
            )
        });

        std::thread::sleep(Duration::from_millis(30));
        cancellation.cancel();
        assert!(matches!(
            bridge.join().unwrap(),
            Err(TransportError::Cancelled)
        ));

        let mut byte = [0];
        assert_eq!(server_peer.peek(&mut byte).unwrap(), 0);
        assert_eq!(client_peer.peek(&mut byte).unwrap(), 0);
    }

    /// Setup: request a wildcard listener address or a zero payload limit.
    /// Exercise: configure the loopback listener pair.
    /// Expect: invalid configuration is rejected before binding.
    /// Scope: listeners cannot accidentally expose the prototype on external interfaces.
    #[test]
    fn rejects_non_loopback_addresses_and_zero_payload_limits() {
        assert_eq!(
            LoopbackForwarder::bind(
                SocketAddr::new(IpAddr::V4(Ipv4Addr::UNSPECIFIED), 0),
                SocketAddr::new(IpAddr::V4(Ipv4Addr::LOCALHOST), 0),
                1024,
                16_384,
            )
            .err()
            .unwrap()
            .kind(),
            std::io::ErrorKind::InvalidInput
        );
        assert_eq!(
            LoopbackForwarder::bind(
                SocketAddr::new(IpAddr::V4(Ipv4Addr::LOCALHOST), 0),
                SocketAddr::new(IpAddr::V4(Ipv4Addr::LOCALHOST), 0),
                0,
                16_384,
            )
            .err()
            .unwrap()
            .kind(),
            std::io::ErrorKind::InvalidInput
        );
    }

    fn connected_tcp_pair() -> (TcpStream, TcpStream) {
        let listener = TcpListener::bind(("127.0.0.1", 0)).unwrap();
        let client = TcpStream::connect(listener.local_addr().unwrap()).unwrap();
        let (server, _) = listener.accept().unwrap();
        (client, server)
    }

    fn set_read_timeout(stream: &TcpStream) {
        stream
            .set_read_timeout(Some(Duration::from_secs(3)))
            .unwrap();
    }

    fn send_frame(stream: &TcpStream, payload: &[u8]) {
        let frame = encode_frame(payload, 1024).unwrap();
        (&*stream).write_all(&frame).unwrap();
    }

    fn expect_frame(stream: &TcpStream, expected: &[u8]) {
        let mut header = [0; 4];
        (&*stream).read_exact(&mut header).unwrap();
        let length = u32::from_be_bytes(header) as usize;
        let mut payload = vec![0; length];
        (&*stream).read_exact(&mut payload).unwrap();
        assert_eq!(payload, expected);
    }

    fn complete_tcp_handshake(server: &TcpStream, client: &TcpStream) {
        send_frame(server, b"Barrier\0\x01\0\x08");
        expect_frame(client, b"Barrier\0\x01\0\x08");
        send_frame(client, b"Barrier\0\x01\0\x08\0\0\0\0");
        expect_frame(server, b"Barrier\0\x01\0\x08\0\0\0\0");
        send_frame(server, b"QINF");
        expect_frame(client, b"QINF");

        let mut client_info = vec![0; 18];
        client_info[..4].copy_from_slice(b"DINF");
        client_info[8..10].copy_from_slice(&1920_i16.to_be_bytes());
        client_info[10..12].copy_from_slice(&1080_i16.to_be_bytes());
        send_frame(client, &client_info);
        expect_frame(server, &client_info);
        send_frame(server, b"CIAK");
        expect_frame(client, b"CIAK");
        send_frame(server, b"DSOP\0\0\0\0");
        expect_frame(client, b"DSOP\0\0\0\0");
    }
}

mod compatibility {
    use rust_deskflow_core::clipboard::ClipboardPermissions;
    use rust_deskflow_core::framing::{decode_frame, encode_frame};
    use rust_deskflow_core::handshake::{
        CURRENT_VERSION, ProtocolName, negotiate_server_version, parse_client_hello,
        parse_server_hello, validate_client_version,
    };
    use rust_deskflow_core::session::{Endpoint, Session, SessionError, SessionState};

    /// Setup: fixed examples from ProtocolTypes.h at Deskflow commit c1b19244a37bd238038ea2bf0ab56d9efc2de5d7.
    /// Exercise: parse greetings, run the documented protocol-1.8 startup, and frame accepted messages.
    /// Expect: exact upstream-example bytes, decoded fields, and server-to-client message order.
    /// Scope: upstream examples/constants are the oracle; strict session policy is local and not differential-tested.
    #[test]
    fn matches_pinned_deskflow_wire_fixtures() {
        const SERVER_HELLO_FRAME: &[u8] = &[
            0, 0, 0, 11, b'B', b'a', b'r', b'r', b'i', b'e', b'r', 0, 1, 0, 8,
        ];
        const CLIENT_HELLO_FRAME: &[u8] = &[
            0, 0, 0, 26, b'B', b'a', b'r', b'r', b'i', b'e', b'r', 0, 1, 0, 8, 0, 0, 0, 11, b'w',
            b'o', b'r', b'k', b's', b't', b'a', b't', b'i', b'o', b'n',
        ];
        const QINF_FRAME: &[u8] = &[0, 0, 0, 4, b'Q', b'I', b'N', b'F'];
        const DINF_FRAME: &[u8] = &[
            0, 0, 0, 18, b'D', b'I', b'N', b'F', 0, 0, 0, 0, 7, 128, 4, 56, 0, 0, 1, 144, 1, 44,
        ];
        const CIAK_FRAME: &[u8] = &[0, 0, 0, 4, b'C', b'I', b'A', b'K'];
        const CROP_FRAME: &[u8] = &[0, 0, 0, 4, b'C', b'R', b'O', b'P'];
        const EMPTY_DSOP_FRAME: &[u8] = &[0, 0, 0, 8, b'D', b'S', b'O', b'P', 0, 0, 0, 0];
        const LEFT_MOUSE_DOWN_FRAME: &[u8] = &[0, 0, 0, 5, b'D', b'M', b'D', b'N', 1];
        const INPUT_FRAMES: &[&[u8]] = &[
            b"\0\0\0\x10DKDL\0a\0\0\0\x1e\0\0\0\x02en",
            b"\0\0\0\x12DKRP\0a\0\0\0\x03\0\x1e\0\0\0\x02en",
            b"\0\0\0\x0aDKUP\0a\0\0\0\x1e",
            b"\0\0\0\x05DMUP\x01",
            b"\0\0\0\x08DMMV\x01\x90\x01\x2c",
            b"\0\0\0\x08DMRM\0\x0a\xff\xf6",
            b"\0\0\0\x08DMWM\0\0\0\x78",
            b"\0\0\0\x0eCINN\x01\x90\x01\x2c\0\0\0\x01\0\0",
            b"\0\0\0\x04COUT",
        ];
        const CLIPBOARD_FRAMES: &[&[u8]] = &[
            b"\0\0\0\x09CCLP\0\0\0\0\0",
            b"\0\0\0\x0fDCLP\0\0\0\0\0\x01\0\0\0\x011",
            b"\0\0\0\x0fDCLP\0\0\0\0\0\x02\0\0\0\x01x",
            b"\0\0\0\x0eDCLP\0\0\0\0\0\x03\0\0\0\0",
        ];

        let server_frame = decode_frame(SERVER_HELLO_FRAME, 1024).unwrap().unwrap();
        assert!(server_frame.remaining.is_empty());
        let server_hello = parse_server_hello(server_frame.payload).unwrap();
        assert_eq!(server_hello.protocol, ProtocolName::Barrier);
        assert_eq!(
            negotiate_server_version(server_hello.version).unwrap(),
            CURRENT_VERSION
        );

        let client_frame = decode_frame(CLIENT_HELLO_FRAME, 1024).unwrap().unwrap();
        assert!(client_frame.remaining.is_empty());
        let client_hello = parse_client_hello(client_frame.payload).unwrap();
        assert_eq!(client_hello.protocol, ProtocolName::Barrier);
        assert_eq!(client_hello.version, CURRENT_VERSION);
        assert_eq!(client_hello.name, b"workstation");
        assert_eq!(
            validate_client_version(client_hello.version).unwrap(),
            CURRENT_VERSION
        );

        let mut session = Session::new(1, 1024, 4096);
        let fixture_sequence = [
            (Endpoint::Server, SERVER_HELLO_FRAME),
            (Endpoint::Client, CLIENT_HELLO_FRAME),
            (Endpoint::Server, QINF_FRAME),
            (Endpoint::Client, DINF_FRAME),
            (Endpoint::Server, CIAK_FRAME),
            (Endpoint::Server, CROP_FRAME),
            (Endpoint::Server, EMPTY_DSOP_FRAME),
        ];
        for (source, frame) in fixture_sequence {
            let decoded = decode_frame(frame, 1024).unwrap().unwrap();
            assert!(decoded.remaining.is_empty());
            session.receive(1, source, decoded.payload).unwrap();
            let destination = match source {
                Endpoint::Server => Endpoint::Client,
                Endpoint::Client => Endpoint::Server,
            };
            assert_eq!(
                session.take_next(1, destination).unwrap().as_deref(),
                Some(frame)
            );
        }
        assert_eq!(session.snapshot().state, SessionState::Ready);

        for frame in INPUT_FRAMES
            .iter()
            .copied()
            .chain(std::iter::once(LEFT_MOUSE_DOWN_FRAME))
        {
            let decoded = decode_frame(frame, 1024).unwrap().unwrap();
            assert!(decoded.remaining.is_empty());
            session
                .receive(1, Endpoint::Server, decoded.payload)
                .unwrap();
            assert_eq!(
                session.take_next(1, Endpoint::Client).unwrap().as_deref(),
                Some(frame)
            );
        }

        session
            .set_clipboard_permissions(
                1,
                Endpoint::Server,
                ClipboardPermissions {
                    send: true,
                    receive: false,
                },
            )
            .unwrap();
        session
            .set_clipboard_permissions(
                1,
                Endpoint::Client,
                ClipboardPermissions {
                    send: false,
                    receive: true,
                },
            )
            .unwrap();
        for frame in CLIPBOARD_FRAMES {
            let decoded = decode_frame(frame, 1024).unwrap().unwrap();
            assert!(decoded.remaining.is_empty());
            session
                .receive(1, Endpoint::Server, decoded.payload)
                .unwrap();
            assert_eq!(
                session.take_next(1, Endpoint::Client).unwrap().as_deref(),
                Some(*frame)
            );
        }

        assert_eq!(
            encode_frame(b"DINF\0\0\0\0\x07\x80\x048\0\0\x01\x90\x01\x2c", 1024).unwrap(),
            DINF_FRAME
        );
    }

    /// Setup: complete pinned-source startup, then append a byte to the fixed-width DMMV example.
    /// Exercise: submit the malformed message through an otherwise ready session.
    /// Expect: strict local shape validation rejects it and closes/clears the session.
    /// Scope: malformed-frame closure is Rust policy; upstream parsing is not differentially tested.
    #[test]
    fn rejects_malformed_pinned_message_shape_without_forwarding() {
        const MALFORMED_DMMV_FRAME: &[u8] = b"\0\0\0\x09DMMV\x01\x90\x01\x2c\0";

        let mut session = Session::new(1, 1024, 4096);
        for (source, frame) in [
            (
                Endpoint::Server,
                b"\0\0\0\x0bBarrier\0\x01\0\x08".as_slice(),
            ),
            (
                Endpoint::Client,
                b"\0\0\0\x1aBarrier\0\x01\0\x08\0\0\0\x0bworkstation".as_slice(),
            ),
            (Endpoint::Server, b"\0\0\0\x04QINF".as_slice()),
            (
                Endpoint::Client,
                b"\0\0\0\x12DINF\0\0\0\0\x07\x80\x048\0\0\x01\x90\x01\x2c".as_slice(),
            ),
            (Endpoint::Server, b"\0\0\0\x04CIAK".as_slice()),
            (Endpoint::Server, b"\0\0\0\x04CROP".as_slice()),
            (Endpoint::Server, b"\0\0\0\x08DSOP\0\0\0\0".as_slice()),
        ] {
            let decoded = decode_frame(frame, 1024).unwrap().unwrap();
            session.receive(1, source, decoded.payload).unwrap();
            let destination = match source {
                Endpoint::Server => Endpoint::Client,
                Endpoint::Client => Endpoint::Server,
            };
            assert_eq!(
                session.take_next(1, destination).unwrap().as_deref(),
                Some(frame)
            );
        }

        let malformed = decode_frame(MALFORMED_DMMV_FRAME, 1024).unwrap().unwrap();
        assert_eq!(
            session.receive(1, Endpoint::Server, malformed.payload),
            Err(SessionError::MalformedMessage)
        );
        assert_eq!(session.snapshot().state, SessionState::Closed);
        assert_eq!(session.snapshot().queued_bytes, 0);
        assert_eq!(
            session.take_next(1, Endpoint::Client),
            Err(SessionError::Closed)
        );
    }

    /// Setup: explicitly opted-in Deskflow test endpoints with pinned builds/configuration.
    /// Exercise: greet, switch screens, send synthetic input, and test clipboard permissions.
    /// Expect: correct endpoint behavior and clean close with payload-free diagnostics.
    /// Scope: isolated permitted environment only; no work-machine connection by default.
    #[test]
    #[ignore = "Requires a permitted Deskflow endpoint test environment"]
    fn exchanges_synthetic_input_with_real_deskflow_endpoints() {
        todo!("Run an explicit opt-in compatibility test without capturing normal typing");
    }
}

mod bluetooth {
    /// Setup: an approved paired adapter pair, selected backend, and fixed frame fixtures.
    /// Exercise: send fragmented/coalesced frames both ways under representative input load.
    /// Expect: exact ordered bytes, bounded queues, and recorded aggregate latency.
    /// Scope: select latency thresholds first; confirm intended peer and encrypted link state.
    #[test]
    #[ignore = "Requires selected Bluetooth backend and paired test adapters"]
    fn transports_frames_without_boundary_or_order_changes() {
        todo!("Check the same framing fixtures over the real selected Bluetooth transport");
    }

    /// Setup: an active permitted Bluetooth session with held synthetic keys and queued data.
    /// Exercise: drop the link, exercise the local stop, then reconnect or sleep/resume.
    /// Expect: cleanup, a fresh handshake, and no stale input/clipboard replay or callbacks.
    /// Scope: physical tests remain opt-in; specify held-key release ownership before asserting it.
    #[test]
    #[ignore = "Requires paired adapters and a permitted live test environment"]
    fn disconnect_and_reconnect_start_a_fresh_session() {
        todo!("Check link loss, shutdown, fresh handshake, and no stale input replay");
    }
}
