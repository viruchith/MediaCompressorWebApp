"""Unit tests for the database module."""

import time

from app import db
from app.config import config


class TestQueueCounts:
    def test_empty_database(self):
        counts = db.get_queue_counts()
        assert counts["total"] == 0
        assert counts["pending"] == 0
        assert counts["processing"] == 0
        assert counts["completed"] == 0
        assert counts["errors"] == 0
        assert counts["cancelled"] == 0

    def test_with_files(self):
        job_id = db.create_job("/in", "/out", {}, {}, "balanced")
        db.add_files_batch(job_id, [
            ("/in/a.png", "/out/a.webp", "image"),
            ("/in/b.png", "/out/b.webp", "image"),
        ])
        counts = db.get_queue_counts()
        assert counts["total"] == 2
        assert counts["pending"] == 2


class TestClaimFile:
    def test_claim_success(self):
        job_id = db.create_job("/in", "/out", {}, {}, "balanced")
        db.add_files_batch(job_id, [("/in/a.png", "/out/a.webp", "image")])
        pending = db.get_pending_files(limit=1)
        assert len(pending) == 1
        assert db.claim_file(pending[0].id) is True

    def test_claim_already_claimed(self):
        job_id = db.create_job("/in", "/out", {}, {}, "balanced")
        db.add_files_batch(job_id, [("/in/a.png", "/out/a.webp", "image")])
        pending = db.get_pending_files(limit=1)
        db.claim_file(pending[0].id)
        # Second claim should fail
        assert db.claim_file(pending[0].id) is False


class TestFairScheduling:
    def test_round_robin_across_jobs(self):
        """Files from multiple jobs should interleave via round-robin."""
        job1 = db.create_job("/in1", "/out1", {}, {}, "balanced")
        job2 = db.create_job("/in2", "/out2", {}, {}, "balanced")
        db.add_files_batch(job1, [
            (f"/in1/img{i}.png", f"/out1/img{i}.webp", "image")
            for i in range(5)
        ])
        db.add_files_batch(job2, [
            (f"/in2/img{i}.png", f"/out2/img{i}.webp", "image")
            for i in range(5)
        ])

        pending = db.get_pending_files(limit=10)
        job_ids = [f.job_id for f in pending]
        # First file should be from job1 or job2, but they should alternate
        # At minimum, both jobs should appear in the first 4 results
        first_four = set(job_ids[:4])
        assert job1 in first_four
        assert job2 in first_four


class TestTimeoutDetection:
    def test_get_timed_out_files(self):
        job_id = db.create_job("/in", "/out", {}, {}, "balanced")
        db.add_files_batch(job_id, [("/in/a.png", "/out/a.webp", "image")])
        pending = db.get_pending_files(limit=1)
        db.claim_file(pending[0].id)

        # With timeout of 0 minutes, any processing file should be "timed out"
        timed_out = db.get_timed_out_files(timeout_minutes=0)
        assert len(timed_out) == 1
        assert timed_out[0].id == pending[0].id

    def test_mark_file_timed_out(self):
        job_id = db.create_job("/in", "/out", {}, {}, "balanced")
        db.add_files_batch(job_id, [("/in/a.png", "/out/a.webp", "image")])
        pending = db.get_pending_files(limit=1)
        db.claim_file(pending[0].id)

        result_job_id = db.mark_file_timed_out(pending[0].id)
        assert result_job_id == job_id

        # File should now be back to pending (retry) or permanent fail
        f = db.get_file(pending[0].id)
        assert f.status in (config.STATUS_PENDING, config.STATUS_PERMANENT_FAIL)
        assert f.retry_count == 1


class TestPoisonFile:
    def test_is_poison_file(self):
        job_id = db.create_job("/in", "/out", {}, {}, "balanced")
        db.add_files_batch(job_id, [("/in/a.png", "/out/a.webp", "image")])
        pending = db.get_pending_files(limit=1)
        file_id = pending[0].id

        # Not a poison file initially
        assert db.is_poison_file(file_id) is False

        # Fail it twice
        db.mark_file_failed(file_id, "corrupt", permanent=False)
        db.mark_file_failed(file_id, "corrupt", permanent=False)

        # Now it should be detected as poison (retry_count >= 2)
        assert db.is_poison_file(file_id, threshold=2) is True
