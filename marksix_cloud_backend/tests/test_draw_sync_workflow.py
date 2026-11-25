"""Offline regression check for the MarkSix default-disabled scheduler."""
import re
import unittest
from pathlib import Path


class DrawSyncWorkflowTests(unittest.TestCase):
    def test_all_update_triggers_share_explicit_job_gate(self):
        workflow = Path(__file__).resolve().parents[2] / ".github/workflows/marksix-draw-sync.yml"
        text = workflow.read_text(encoding="utf-8")
        triggers, jobs = text.split("\njobs:\n", 1)
        self.assertIn("\n  schedule:\n", triggers)
        self.assertIn("\n  workflow_dispatch:\n", triggers)
        self.assertEqual(re.findall(r"^  ([\w-]+):\s*$", jobs, re.M), ["synchronize"])
        self.assertIn("\n    if: ${{ vars.MARKSIX_DRAW_SYNC_ENABLED == 'true' }}\n", jobs)
        self.assertEqual(text.count("/api/v1/marksix/admin/catch-up"), 1)
        self.assertNotIn("/api/v1/marksix/admin/catch-up", triggers)
        self.assertLess(jobs.index("    if:"), jobs.index("    runs-on:"))
        self.assertLess(jobs.index('test -n "$MARKSIX_CATCH_UP_TOKEN"'), jobs.index("curl --silent"))


if __name__ == "__main__":
    unittest.main()
