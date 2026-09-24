import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from rss_analyzer import cache
from rss_analyzer.jobs import JobManager, JobStore


class TestDurableJobs(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_patch = patch.object(
            cache,
            "DB_PATH",
            str(Path(self.temp_dir.name) / "jobs.db"),
        )
        self.db_patch.start()
        self.store = JobStore()
        self.store.init_schema()

    def tearDown(self):
        self.db_patch.stop()
        self.temp_dir.cleanup()

    def test_store_deduplicates_and_retries_failed_job(self):
        first = self.store.create("run_analysis", {"limit": 10}, dedupe_key="same")
        duplicate = self.store.create("run_analysis", {"limit": 10}, dedupe_key="same")
        self.assertEqual(first["job_id"], duplicate["job_id"])

        claimed = self.store.claim_next()
        self.assertEqual(claimed["status"], "running")
        self.assertEqual(claimed["attempts"], 1)

        self.store.fail(claimed["job_id"], "temporary failure")
        failed = self.store.get(claimed["job_id"])
        self.assertEqual(failed["status"], "failed")

        retried = self.store.retry(claimed["job_id"])
        self.assertEqual(retried["status"], "pending")
        claimed_again = self.store.claim_next()
        self.store.succeed(claimed_again["job_id"], {"success": True})
        completed = self.store.get(claimed_again["job_id"])
        self.assertEqual(completed["status"], "succeeded")
        self.assertEqual(completed["result"], {"success": True})

    def test_manager_executes_persisted_job(self):
        manager = JobManager(
            lambda operation, payload: {
                "success": True,
                "operation": operation,
                "value": payload["value"],
            },
            store=self.store,
            worker_count=1,
            poll_seconds=0.01,
        )
        try:
            job = manager.submit("example", {"value": 7})
            deadline = time.monotonic() + 2
            current = job
            while time.monotonic() < deadline:
                current = self.store.get(job["job_id"])
                if current["status"] == "succeeded":
                    break
                time.sleep(0.01)

            self.assertEqual(current["status"], "succeeded")
            self.assertEqual(current["result"]["value"], 7)
        finally:
            manager.stop()


if __name__ == "__main__":
    unittest.main()
