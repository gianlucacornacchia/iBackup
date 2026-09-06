"""Streaming SHA-256 hashing utilities.

Hashing is used both for integrity verification (re-hash a stored file and
compare) and for content-based duplicate detection. Files are read in fixed-size
chunks so memory use stays constant regardless of asset size.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import BinaryIO

# 1 MiB read chunk — a good balance of syscall overhead and memory use.
CHUNK_SIZE = 1024 * 1024


def hashing_sha256_stream(stream: BinaryIO, chunk_size: int = CHUNK_SIZE) -> str:
    """Compute the SHA-256 hex digest of a binary stream.

    stream: an open binary file-like object positioned at the start.
    chunk_size: number of bytes to read per iteration.
    Returns the lowercase hexadecimal SHA-256 digest.
    """
    hasher = hashlib.sha256()
    while True:
        block = stream.read(chunk_size)
        if not block:
            break
        hasher.update(block)
    return hasher.hexdigest()


def hashing_sha256_file(path: Path, chunk_size: int = CHUNK_SIZE) -> str:
    """Compute the SHA-256 hex digest of a file on disk.

    path: filesystem path to the file to hash.
    chunk_size: number of bytes to read per iteration.
    Returns the lowercase hexadecimal SHA-256 digest.
    """
    with open(path, "rb") as handle:
        digest = hashing_sha256_stream(handle, chunk_size=chunk_size)
    return digest


def hashing_sha256_bytes(data: bytes) -> str:
    """Compute the SHA-256 hex digest of an in-memory byte string.

    data: the bytes to hash.
    Returns the lowercase hexadecimal SHA-256 digest.
    """
    return hashlib.sha256(data).hexdigest()
