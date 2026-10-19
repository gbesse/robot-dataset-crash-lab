"""Reference recorder and intentionally broken control. Not a LeRobot backend."""
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import struct
import sys
import uuid
import zlib

STAGES = ("after_frames", "after_images", "after_artifact_publish", "after_metadata_publish")
MARKER = "robot-dataset-crash-lab-v1"


def initialize(root):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    marker = root / ".crash-lab"
    if not marker.exists() and any(root.iterdir()):
        raise ValueError("invalid_non_lab_directory")
    if marker.exists() and marker.read_text() != MARKER:
        raise ValueError("invalid_lab_marker")
    marker.write_text(MARKER)
    for directory in ("episodes", ".staging"):
        (root / directory).mkdir(exist_ok=True)
    with sqlite3.connect(root / "metadata.sqlite") as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=FULL")
        db.execute("CREATE TABLE IF NOT EXISTS episodes (episode INTEGER PRIMARY KEY, frame_count INTEGER NOT NULL, artifact_dir TEXT NOT NULL UNIQUE, manifest_sha256 TEXT NOT NULL)")
    return root


def png(index):
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    width = height = 16
    pixels = b"".join(b"\x00" + bytes(((x * 13 + index) % 256, (y * 13) % 256, 100)) * width
                      for y, x in [(y, y) for y in range(height)])
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(pixels)) + chunk(b"IEND", b"")


def write_durable(path, data):
    with Path(path).open("wb") as file:
        file.write(data)
        file.flush()
        os.fsync(file.fileno())


def fsync_directory(path):
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def write_episode(root, episode, protocol="safe", checkpoint=lambda _: None, frame_encoding="jsonl"):
    if protocol not in ("safe", "metadata_first") or type(episode) is not int or episode < 0 or frame_encoding not in ("jsonl", "mcap"):
        raise ValueError("invalid_recorder_arguments")
    if frame_encoding == "mcap":
        try:
            from mcap.writer import Writer, CompressionType
        except ImportError as error:
            raise ValueError("invalid_missing_mcap_dependency") from error
    root = initialize(root)
    with sqlite3.connect(root / "metadata.sqlite") as db:
        if db.execute("SELECT 1 FROM episodes WHERE episode=?", (episode,)).fetchone():
            raise ValueError("invalid_episode_already_committed")
    token = f"{episode:06d}-{uuid.uuid4().hex}"
    stage = root / ".staging" / token
    destination = root / "episodes" / token
    stage.mkdir()
    (stage / "rgb").mkdir()
    frames = [{"frame_index": i, "timestamp_ns": (episode * 4 + i) * 50_000_000,
               "state": [episode, i / 10], "action": [0.1, -0.1], "image": f"rgb/{i:06d}.png"}
              for i in range(4)]
    frame_data = ("\n".join(json.dumps(f, sort_keys=True) for f in frames) + "\n").encode()
    frame_file = "frames.jsonl"
    if frame_encoding == "mcap":
        stream = io.BytesIO()
        writer = Writer(stream, compression=CompressionType.NONE)
        writer.start(profile="", library="robot-dataset-crash-lab/0.1.0")
        channel = writer.register_channel(topic="/robot/frame", message_encoding="json", schema_id=0)
        for frame in frames:
            writer.add_message(channel, log_time=frame["timestamp_ns"], publish_time=frame["timestamp_ns"],
                               sequence=frame["frame_index"], data=json.dumps(frame, sort_keys=True).encode())
        writer.finish()
        frame_data = stream.getvalue()
        frame_file = "frames.mcap"
    images = {f"rgb/{i:06d}.png": png(i) for i in range(4)}
    manifest = {"synthetic": True, "episode": episode, "frame_count": 4,
                "frame_encoding": frame_encoding, "frame_file": frame_file,
                "files": {frame_file: hashlib.sha256(frame_data).hexdigest(),
                          **{name: hashlib.sha256(data).hexdigest() for name, data in images.items()}}}
    manifest_data = json.dumps(manifest, sort_keys=True).encode()
    manifest_hash = hashlib.sha256(manifest_data).hexdigest()

    def publish_metadata():
        with sqlite3.connect(root / "metadata.sqlite") as db:
            db.execute("PRAGMA synchronous=FULL")
            db.execute("INSERT INTO episodes VALUES (?,?,?,?)", (episode, 4, f"episodes/{token}", manifest_hash))
        checkpoint("after_metadata_publish")

    if protocol == "metadata_first":
        publish_metadata()
    write_durable(stage / frame_file, frame_data)
    checkpoint("after_frames")
    for name, data in images.items():
        write_durable(stage / name, data)
    write_durable(stage / "manifest.json", manifest_data)
    fsync_directory(stage / "rgb")
    fsync_directory(stage)
    checkpoint("after_images")
    stage.rename(destination)
    fsync_directory(root / "episodes")
    checkpoint("after_artifact_publish")
    if protocol == "safe":
        publish_metadata()


def handshake(stage):
    print(json.dumps({"checkpoint": stage}), flush=True)
    if sys.stdin.readline().strip() != "continue":
        raise RuntimeError("invalid_controller_response")


if __name__ == "__main__":
    write_episode(sys.argv[1], int(sys.argv[2]), sys.argv[3], handshake, sys.argv[4] if len(sys.argv) > 4 else "jsonl")
