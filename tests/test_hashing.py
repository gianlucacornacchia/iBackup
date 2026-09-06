"""Tests for streaming SHA-256 hashing, including property-based checks."""

from __future__ import annotations

import hashlib
import io

from hypothesis import given
from hypothesis import strategies as st

from iphone_archive.core import hashing


def test_sha256_bytes_known_value():
    """Known-answer test for the empty input."""
    empty_digest = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    assert hashing.hashing_sha256_bytes(b"") == empty_digest


def test_sha256_file_matches_hashlib(tmp_path):
    """Hashing a file equals hashlib over its bytes."""
    payload = b"iphone-archive" * 10000
    target = tmp_path / "blob.bin"
    target.write_bytes(payload)
    assert hashing.hashing_sha256_file(target) == hashlib.sha256(payload).hexdigest()


def test_sha256_stream_small_chunk():
    """A tiny chunk size must not change the digest."""
    payload = b"0123456789abcdef" * 1000
    stream = io.BytesIO(payload)
    assert (
        hashing.hashing_sha256_stream(stream, chunk_size=7) == hashlib.sha256(payload).hexdigest()
    )


@given(
    data=st.binary(max_size=4096),
    chunk_size=st.integers(min_value=1, max_value=512),
)
def test_streaming_is_chunk_size_independent(data, chunk_size):
    """Property: streamed chunked hashing equals one-shot hashlib for any input."""
    stream = io.BytesIO(data)
    streamed = hashing.hashing_sha256_stream(stream, chunk_size=chunk_size)
    assert streamed == hashlib.sha256(data).hexdigest()
