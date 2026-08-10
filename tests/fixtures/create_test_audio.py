#!/usr/bin/env python3
"""
create_test_audio.py

Creates a minimal but syntactically valid MP3 file for use in tests.
No external dependencies — pure Python standard library.

The resulting file is a valid MPEG1 Layer 3 audio file consisting of
silent audio frames. It will not play meaningful audio, but it satisfies
MP3 format requirements for testing RSS generation.

Usage:
    python tests/fixtures/create_test_audio.py [output_path]
"""

import struct
import sys
from pathlib import Path


def make_mp3_frame(bitrate_kbps: int = 128, sample_rate: int = 44100) -> bytes:
    """
    Build one silent MPEG1 Layer 3 audio frame.

    Frame header bit layout (32 bits):
      [31-21] Sync:         11111111111
      [20-19] MPEG version: 11  (MPEG 1)
      [18-17] Layer:        01  (Layer 3)
      [16]    CRC:          1   (no CRC)
      [15-12] Bitrate idx:  1001 (128 kbps for MPEG1/L3)
      [11-10] Sample rate:  00  (44100 Hz for MPEG1)
      [9]     Padding:      0
      [8]     Private:      0
      [7-6]   Channel mode: 01  (joint stereo)
      [5-4]   Mode ext:     00
      [3]     Copyright:    0
      [2]     Original:     1
      [1-0]   Emphasis:     00

    Resulting header bytes: FF FB 90 44
    Frame size = 144 * bitrate / sample_rate = 144 * 128000 / 44100 = 417 bytes
    """
    header = bytes([0xFF, 0xFB, 0x90, 0x44])
    # Frame body size (total frame - 4 byte header)
    frame_size = (144 * bitrate_kbps * 1000) // sample_rate  # = 417
    body = bytes(frame_size - 4)
    return header + body


def create_test_mp3(output_path: Path, num_frames: int = 10) -> int:
    """
    Write a minimal test MP3 file.

    Args:
        output_path: Where to write the file
        num_frames:  Number of silent frames (10 frames ≈ 0.26 seconds)

    Returns:
        File size in bytes
    """
    frame = make_mp3_frame()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "wb") as f:
        for _ in range(num_frames):
            f.write(frame)
    size = output_path.stat().st_size
    return size


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("test_audio.mp3")
    size = create_test_mp3(out)
    print(f"Created test MP3: {out} ({size} bytes, {size // 417} frames)")
