from __future__ import annotations

import pytest

from aegis.verify_decision import payload_hash, verify_payload


def test_exact_payload_bytes_and_keccak_are_required():
    # Ethereum Keccak-256, deliberately not standardized SHA3-256.
    assert payload_hash(b"") == "0xc5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470"
    payload = b'{"mode":"paper","reason":"risk_rejected"}'
    expected = payload_hash(payload)
    assert verify_payload(payload, expected)
    assert not verify_payload(payload + b"\n", expected)
    assert not verify_payload(payload.replace(b"paper", b"live"), expected)


def test_invalid_expected_hash_is_rejected():
    with pytest.raises(ValueError, match="32-byte"):
        verify_payload(b"example", "bad")
