import hashlib
import json
from pathlib import Path
import signal
import sqlite3
import struct
import tempfile
import unittest
import zlib

from robot_crash.harness import inspect, interrupt, matrix, resume
from robot_crash.recorder import initialize, png, write_episode
from robot_crash.report import html_report


class CrashLabTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.matrices = {encoding: matrix(encoding) for encoding in ("jsonl", "mcap")}

    def test_real_sigkill_at_all_eight_checkpoint_protocol_pairs(self):
        for report in self.matrices.values():
            self.assertEqual(report["real_process_kills"], 8)
            self.assertTrue(all(t["returncode"] == -signal.SIGKILL for t in report["trials"]))

    def test_safe_protocol_only_exposes_complete_prefixes(self):
        for report in self.matrices.values():
            self.assertTrue(report["safe_protocol_passed"])
            for trial in report["trials"]:
                if trial["protocol"] == "safe":
                    self.assertTrue(trial["snapshot"]["valid"])
                    self.assertEqual(trial["snapshot"]["readable_episodes"], trial["snapshot"]["visible_episodes"])

    def test_broken_protocol_is_detected_before_files_exist(self):
        for report in self.matrices.values():
            failures = [t for t in report["trials"] if t["protocol"] == "metadata_first" and not t["snapshot"]["valid"]]
            self.assertEqual(len(failures), 3)
            self.assertTrue(all(t["snapshot"]["errors"][0]["code"] == "missing_artifact" for t in failures))

    def test_all_valid_prefixes_resume_to_twelve_frames(self):
        for report in self.matrices.values():
            for trial in report["trials"]:
                if trial["resumed"]:
                    self.assertTrue(trial["resumed"]["valid"])
                    self.assertEqual(trial["resumed"]["frame_count"], 12)

    def test_does_not_claim_native_lerobot_or_power_loss(self):
        for report in self.matrices.values():
            self.assertTrue(report["synthetic_sensor_data"])
            self.assertFalse(report["power_loss_tested"])
            self.assertFalse(report["lerobot_native_backend_tested"])

    def test_orphan_artifacts_survive_resume_without_becoming_visible(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "data"
            result = interrupt(root, "safe", "after_artifact_publish")
            self.assertEqual(result["snapshot"]["orphan_artifact_count"], 1)
            self.assertEqual(result["snapshot"]["visible_episodes"], 0)
            after = resume(root)
            self.assertEqual(after["orphan_artifact_count"], 1)
            self.assertEqual(after["frame_count"], 12)

    def test_broken_committed_episode_blocks_resume(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "data"
            interrupt(root, "metadata_first", "after_metadata_publish")
            with self.assertRaisesRegex(ValueError, "invalid_committed_dataset"):
                resume(root)

    def test_unknown_nonempty_directory_is_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            user = root / "important.txt"
            user.write_text("user data")
            with self.assertRaisesRegex(ValueError, "invalid_non_lab_directory"):
                initialize(root)
            self.assertEqual(user.read_text(), "user data")
            self.assertEqual(list(root.iterdir()), [user])

    def test_committed_image_corruption_is_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "data"
            write_episode(root, 0)
            image = next((root / "episodes").glob("*/rgb/*.png"))
            image.write_bytes(b"corrupted")
            result = inspect(root)
            self.assertFalse(result["valid"])
            self.assertEqual(result["errors"][0]["code"], "artifact_hash")

    def test_metadata_directory_escape_is_rejected_without_reading_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = initialize(Path(tmp) / "data")
            with sqlite3.connect(root / "metadata.sqlite") as db:
                db.execute("INSERT INTO episodes VALUES (0,4,'../private','x')")
            self.assertEqual(inspect(root)["errors"][0]["code"], "artifact_path_escape")

    def test_duplicate_episode_does_not_replace_existing_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "data"
            write_episode(root, 0)
            before = inspect(root)
            with self.assertRaisesRegex(ValueError, "already_committed"):
                write_episode(root, 0)
            self.assertEqual(inspect(root), before)

    def test_png_has_decodable_pixels_and_valid_chunk_crcs(self):
        data = png(1)
        self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")
        pos = 8
        image_data = b""
        while pos < len(data):
            length = struct.unpack(">I", data[pos:pos+4])[0]
            kind = data[pos+4:pos+8]
            chunk = data[pos+8:pos+8+length]
            crc = struct.unpack(">I", data[pos+8+length:pos+12+length])[0]
            self.assertEqual(crc, zlib.crc32(kind + chunk) & 0xffffffff)
            if kind == b"IDAT":
                image_data += chunk
            pos += length + 12
        self.assertEqual(len(zlib.decompress(image_data)), 16 * (1 + 16 * 3))

    def test_real_mcap_reader_decodes_committed_frames(self):
        from mcap.reader import make_reader
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "data"
            write_episode(root, 0, frame_encoding="mcap")
            file = next((root / "episodes").glob("*/frames.mcap"))
            with file.open("rb") as stream:
                messages = list(make_reader(stream, validate_crcs=True).iter_messages(log_time_order=False))
            self.assertEqual(len(messages), 4)
            self.assertEqual([m.sequence for _, _, m in messages], [0,1,2,3])
            self.assertTrue(inspect(root)["valid"])

    def test_trilingual_html_does_not_inline_unescaped_data(self):
        report = dict(self.matrices["mcap"], note="</script><script>alert(1)</script>")
        for lang in ("fr", "en", "es"):
            content = html_report(report, lang)
            self.assertNotIn("</script><script>alert", content)
            self.assertIn("\\u003c/script>", content)


if __name__ == "__main__":
    unittest.main()
