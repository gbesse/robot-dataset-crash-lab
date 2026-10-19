import hashlib
import json
from pathlib import Path
import selectors
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time
from urllib.parse import quote

from .recorder import STAGES, initialize, write_episode


def read_frames(folder, manifest):
    encoding = manifest.get("frame_encoding", "jsonl")
    name = manifest.get("frame_file", "frames.jsonl")
    if name not in manifest["files"] or not (folder / name).resolve().is_relative_to(folder):
        raise ValueError("invalid_frame_path")
    if encoding == "jsonl":
        return [json.loads(line) for line in (folder / name).read_text().splitlines()]
    if encoding != "mcap":
        raise ValueError("invalid_encoding")
    try:
        from mcap.reader import make_reader
    except ImportError as error:
        raise ValueError("invalid_missing_mcap_dependency") from error
    try:
        with (folder / name).open("rb") as stream:
            frames = []
            for _, channel, message in make_reader(stream, validate_crcs=True).iter_messages(log_time_order=False):
                frame = json.loads(message.data)
                if channel.topic != "/robot/frame" or message.sequence != frame["frame_index"] or message.log_time != frame["timestamp_ns"]:
                    raise ValueError("mcap_sequence_or_timestamp")
                frames.append(frame)
            return frames
    except Exception as error:
        raise ValueError("invalid_mcap") from error


def inspect(root):
    """Read only committed metadata. Unreferenced files never become visible frames."""
    root = Path(root).resolve()
    errors = []
    episodes = []
    referenced = set()
    uri = "file:" + quote(str(root / "metadata.sqlite")) + "?mode=ro"
    with sqlite3.connect(uri, uri=True) as db:
        rows = db.execute("SELECT episode,frame_count,artifact_dir,manifest_sha256 FROM episodes ORDER BY episode").fetchall()
    if [row[0] for row in rows] != list(range(len(rows))):
        errors.append({"code": "episode_gap"})
    last_time = -1
    for episode, count, artifact, manifest_hash in rows:
        folder = (root / artifact).resolve()
        if not folder.is_relative_to(root / "episodes") or folder == root / "episodes":
            errors.append({"code": "artifact_path_escape", "episode": episode})
            continue
        referenced.add(folder)
        try:
            manifest_path = folder / "manifest.json"
            if manifest_path.is_symlink():
                raise ValueError("manifest_path_escape")
            data = manifest_path.read_bytes()
            if hashlib.sha256(data).hexdigest() != manifest_hash:
                raise ValueError("manifest_hash")
            manifest = json.loads(data)
            if manifest["episode"] != episode or manifest["frame_count"] != count:
                raise ValueError("metadata_mismatch")
            if not isinstance(manifest.get("files"), dict):
                raise ValueError("invalid_manifest")
            for name, digest in manifest["files"].items():
                path = (folder / name).resolve()
                if not path.is_relative_to(folder):
                    raise ValueError("file_path_escape")
                if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                    raise ValueError("artifact_hash")
            frames = read_frames(folder, manifest)
            if len(frames) != count or [f["frame_index"] for f in frames] != list(range(count)):
                raise ValueError("frame_count_or_index")
            for frame in frames:
                path = (folder / frame["image"]).resolve()
                if not path.is_relative_to(folder) or frame["image"] not in manifest["files"]:
                    raise ValueError("image_reference")
                if not path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n"):
                    raise ValueError("image_format")
                if type(frame["timestamp_ns"]) is not int or frame["timestamp_ns"] <= last_time:
                    raise ValueError("timestamp_order")
                last_time = frame["timestamp_ns"]
            episodes.append({"episode": episode, "frame_count": count, "synthetic": manifest.get("synthetic", False)})
        except (OSError, ValueError, TypeError, KeyError) as error:
            errors.append({"code": "missing_artifact" if isinstance(error, FileNotFoundError) else str(error) if isinstance(error, ValueError) else "invalid_artifact", "episode": episode})
    artifacts = {p.resolve() for p in (root / "episodes").iterdir() if p.is_dir()}
    return {"valid": not errors, "visible_episodes": len(rows), "readable_episodes": len(episodes),
            "frame_count": sum(e["frame_count"] for e in episodes), "episodes": episodes, "errors": errors,
            "orphan_artifact_count": len(artifacts - referenced),
            "staging_count": len(list((root / ".staging").iterdir())), "explicit_dataset_writes": False}


def interrupt(root, protocol, checkpoint, timeout=10, frame_encoding="jsonl"):
    if protocol not in ("safe", "metadata_first") or checkpoint not in STAGES:
        raise ValueError("invalid_trial")
    root = initialize(root)
    process = subprocess.Popen([sys.executable, "-m", "robot_crash.recorder", str(root), "0", protocol, frame_encoding],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    events = []
    deadline = time.monotonic() + timeout
    try:
        while time.monotonic() < deadline:
            if not selector.select(timeout=min(0.1, max(0, deadline - time.monotonic()))):
                if process.poll() is not None:
                    break
                continue
            line = process.stdout.readline()
            if not line:
                break
            event = json.loads(line)
            events.append(event)
            if event.get("checkpoint") == checkpoint:
                process.kill()
                process.wait(timeout=5)
                return {"signal": "SIGKILL", "returncode": process.returncode, "checkpoint": checkpoint,
                        "events": events, "snapshot": inspect(root)}
            process.stdin.write("continue\n")
            process.stdin.flush()
        raise RuntimeError("checkpoint_not_reached")
    finally:
        selector.close()
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=5)


def resume(root, target_episodes=3, frame_encoding="jsonl"):
    snapshot = inspect(root)
    if not snapshot["valid"]:
        raise ValueError("invalid_committed_dataset")
    for episode in range(snapshot["visible_episodes"], target_episodes):
        write_episode(root, episode, "safe", frame_encoding=frame_encoding)
    return inspect(root)


def matrix(frame_encoding="jsonl"):
    if frame_encoding not in ("jsonl", "mcap"):
        raise ValueError("invalid_encoding")
    trials = []
    for protocol in ("safe", "metadata_first"):
        for checkpoint in STAGES:
            with tempfile.TemporaryDirectory(prefix="robot-crash-") as tmp:
                root = Path(tmp) / "dataset"
                result = interrupt(root, protocol, checkpoint, frame_encoding=frame_encoding)
                if result["snapshot"]["valid"]:
                    result["resumed"] = resume(root, frame_encoding=frame_encoding)
                else:
                    result["resumed"] = None
                trials.append({"protocol": protocol, **result})
    safe = [t for t in trials if t["protocol"] == "safe"]
    controls = [t for t in trials if t["protocol"] == "metadata_first"]
    return {"synthetic_sensor_data": True, "frame_encoding": frame_encoding, "real_process_kills": len(trials), "trials": trials,
            "safe_protocol_passed": all(t["snapshot"]["valid"] and t["resumed"]["visible_episodes"] == 3 and t["resumed"]["valid"] for t in safe),
            "broken_control_detected": any(not t["snapshot"]["valid"] for t in controls),
            "power_loss_tested": False, "lerobot_native_backend_tested": False}
