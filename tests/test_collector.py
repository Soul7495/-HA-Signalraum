import gzip
import random
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "diagnostic_hub"))
from collector import Collector, DEFAULTS, StorageFull, overlap
from evcc import FAULT, fingerprint, redact


class CollectorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config = dict(DEFAULTS)
        self.timestamp = time.time()
        self.root = Path(self.temp.name)
        self.collector = Collector(self.config, self.root, clock=lambda: self.timestamp)

    def poll(self, lines):
        with patch.object(self.collector, "fetch", return_value=lines):
            self.collector.poll()

    def case(self):
        item = next(iter(self.collector.incidents.values()))
        return self.collector.read_case(self.collector.root / item["filename"])

    def test_overlap_with_duplicates_rotation_and_reset(self):
        self.assertEqual(Collector.new_lines(["a", "b", "c"], ["b", "c", "d"]), ["d"])
        self.assertEqual(Collector.new_lines(["a", "x", "x"], ["x", "x", "x", "end"]), ["x", "end"])
        self.assertEqual(Collector.new_lines(["old"], ["new"]), ["new"])
        self.assertEqual(Collector.new_lines(["x"] * 10000, ["x"] * 10000), [])

    def test_linear_overlap_matches_reference_randomized(self):
        rng = random.Random(1)
        for _ in range(1500):
            left = [rng.randrange(3) for _ in range(rng.randrange(30))]
            right = [rng.randrange(3) for _ in range(rng.randrange(30))]
            expected = next((n for n in range(min(len(left), len(right)), 0, -1) if left[-n:] == right[:n]), 0)
            self.assertEqual(overlap(left, right), expected)

    def test_initial_fault_saved_and_labeled(self):
        self.poll(["before", "[rct] ERROR timeout"])
        item = self.case()
        self.assertEqual(item["origin"], "initial")
        self.assertEqual(item["pre_log"][0], "before")
        self.assertEqual(item["category"], "RCT Power")
        self.assertEqual(item["status"], "pending")

    def test_repeats_grouped_and_error_numbers_stay_distinct(self):
        first = "[rct] ERROR 2026-10-13 14:00:00 timeout code 23"
        second = "[rct] ERROR 2026-10-13 14:00:15 timeout code 23"
        self.poll(["ready"])
        self.poll(["ready", first, first, second])
        self.assertEqual(self.case()["repeats"], 3)
        self.assertNotEqual(fingerprint(first), fingerprint(first.replace("23", "24")))

    def test_new_case_after_window(self):
        self.poll(["ready"])
        self.poll(["ready", "ERROR timeout"])
        self.timestamp += 121
        self.poll(["ready", "ERROR timeout", "ERROR timeout"])
        self.assertEqual(len(self.collector.incidents), 2)
        self.assertEqual(sorted(x["repeats"] for x in self.collector.incidents.values()), [1, 1])

    def test_restart_preserves_pre_tail_and_counts(self):
        self.poll(["before"])
        self.poll(["before", "ERROR timeout"])
        self.timestamp += 15
        self.poll(["before", "ERROR timeout", "tail before restart"])
        self.collector = Collector(self.config, self.root, clock=lambda: self.timestamp)
        self.timestamp += 15
        self.poll(["before", "ERROR timeout", "tail before restart", "tail after restart"])
        self.assertEqual(self.case()["repeats"], 1)
        for _ in range(7):
            self.timestamp += 15
            self.poll(["before", "ERROR timeout", "tail before restart", "tail after restart", "done"])
        case = self.case()
        self.assertEqual(case["status"], "complete")
        self.assertIn("before", case["pre_log"])
        self.assertIn("tail before restart", case["post_log"])
        self.assertIn("tail after restart", case["post_log"])

    def test_evcc_restart_and_outage_mark_gap(self):
        self.poll(["before"])
        self.poll(["before", "ERROR timeout"])
        self.timestamp += 15
        self.collector.failed(TimeoutError())
        self.timestamp += 15
        self.poll(["restarted", "connected"])
        self.timestamp += 100
        self.poll(["restarted", "connected"])
        case = self.case()
        self.assertEqual(case["status"], "incomplete")
        self.assertIn("before", case["pre_log"])
        self.assertIn("restarted", case["post_log"])
        self.assertGreaterEqual(len(case["gaps"]), 2)

    def test_post_completes_during_outage(self):
        self.poll(["ERROR timeout"])
        self.timestamp += 121
        self.collector.failed(TimeoutError())
        self.assertEqual(self.case()["status"], "incomplete")

    def test_retention_uses_capture_time_not_file_updates(self):
        self.poll(["ERROR timeout"])
        self.timestamp += 15 * 86400
        self.collector.prune()
        self.assertFalse(self.collector.incidents)

    def test_storage_pressure_and_atomic_peak(self):
        self.config["max_storage_mb"] = 1
        for index in range(3):
            path = self.collector.root / f"legacy{index}.log"
            self.collector.atomic(path, bytes([index]) * 400000)
            self.assertLessEqual(self.collector.usage(), 1048576)
        self.assertEqual(len(list(self.collector.root.glob("*.log"))), 2)
        before = set(p.name for p in self.collector.files())
        with self.assertRaises(StorageFull):
            self.collector.atomic(self.collector.root / "huge.log", b"x" * 1100000)
        self.assertFalse(list(self.collector.root.glob("*.tmp")))
        self.assertEqual(before, set(p.name for p in self.collector.files()))

    def test_tail_truncates_to_atomic_budget_and_preserves_pre_log(self):
        self.config["max_storage_mb"] = 1
        self.config["gzip_enabled"] = False
        self.poll(["ERROR timeout", "x" * 300000])
        self.timestamp += 121
        self.poll(["ERROR timeout", "x" * 300000, "y" * 600000])
        archive = self.case()
        self.assertIn("x" * 300000, archive["pre_log"])
        self.assertEqual(archive["status"], "incomplete")
        self.assertTrue(any("Schreibplatz" in x for x in archive["gaps"]))
        self.assertLessEqual(self.collector.usage(), self.collector.limit)

    def test_active_eviction_does_not_crash_finalization(self):
        self.config["max_storage_mb"] = 1
        self.config["gzip_enabled"] = False
        self.poll(["ERROR timeout", "x" * 200000])
        self.collector.atomic(self.collector.root / "large.log", b"a" * 850000)
        self.assertFalse(self.collector.incidents)
        self.timestamp += 121
        self.poll(["ready"])
        self.assertLessEqual(self.collector.usage(), 1048576)
        self.assertIn("offener Nachlauf", self.collector.warning)

    def test_cursor_corruption_and_interrupted_stage_recovery(self):
        self.collector.cursor_file.write_bytes(b"broken")
        (self.collector.root / "incident.json.gz.tmp").write_bytes(b"interrupted")
        restored = Collector(self.config, self.root, clock=lambda: self.timestamp)
        self.assertFalse(restored.initialized)
        self.assertIn("beschädigt", restored.warning)
        self.assertFalse(list(restored.root.glob("*.tmp")))

    def test_valid_json_with_corrupt_case_schema_does_not_break_restart(self):
        (self.collector.root / "bad.json").write_text('{"status":"pending", "pre_log":[]}')
        restored = Collector(self.config, self.root, clock=lambda: self.timestamp)
        self.assertIn("beschädigt", restored.warning)
        self.assertTrue((restored.root / "bad.json").exists())

    def test_legacy_archives_remain_visible(self):
        (self.collector.root / "old.log.gz").write_bytes(gzip.compress(b"original"))
        restored = Collector(self.config, self.root, clock=lambda: self.timestamp)
        self.assertEqual(restored.list_cases()["items"][0]["status"], "legacy")

    def test_redaction_json_url_and_configured_key(self):
        text = '{"token":"secret123", "password": "hidden"} Authorization: Bearer xyz https://user:pass@host'
        clean = redact(text)
        for secret in ("secret123", "hidden", "xyz", "user:pass"):
            self.assertNotIn(secret, clean)
        self.assertNotIn("secret123", redact("key is secret123", "secret123"))

    def test_fault_selection(self):
        for line in (
            "[rct] WARN connection reset",
            "ERROR bad",
            "WARN meter unavailable",
            "rct missing measurement",
            "connection refused",
            "timeout",
        ):
            self.assertIsNotNone(FAULT.search(line), line)
        for line in ("INFO ready", "WARN deprecated configuration", "INFO RCT power 0W"):
            self.assertIsNone(FAULT.search(line), line)

    def test_source_outage_creates_diagnosis_with_last_available_history(self):
        self.poll(["INFO before outage"])
        self.collector.failed(TimeoutError())
        archive = self.case()
        self.assertEqual(archive["origin"], "collector")
        self.assertEqual(archive["pre_log"], ["INFO before outage"])
        self.assertTrue(archive["gaps"])

    def test_fault_storm_bounds_work_without_losing_snapshot(self):
        lines = [f"ERROR distinct fault {index}" for index in range(100)]
        self.poll(lines)
        self.assertEqual(len(self.collector.incidents), 32)
        burst = next(x for x in self.collector.incidents.values() if x["trigger"].startswith("Fehlerhäufung"))
        archive = self.collector.read_case(self.collector.root / burst["filename"])
        self.assertEqual(archive["repeats"], 69)
        self.assertEqual(archive["pre_log"], lines)

    def test_pagination_clamps(self):
        for index in range(25):
            self.timestamp += 1
            self.poll([f"ERROR failure {index}"])
        result = self.collector.list_cases(99)
        self.assertEqual(result["page"], 2)
        self.assertEqual(len(result["items"]), 5)


if __name__ == "__main__":
    unittest.main()
