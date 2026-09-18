import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PREPARE = ROOT / "skills" / "feedly-readflow" / "scripts" / "prepare_packets.py"
PREPARE_DEEP = ROOT / "skills" / "feedly-readflow" / "scripts" / "prepare_deep_packets.py"
MERGE = ROOT / "skills" / "feedly-readflow" / "scripts" / "merge_reports.py"
MARK_READ = ROOT / "skills" / "feedly-readflow" / "scripts" / "mark_read.py"


def run_script(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )


class TestFeedlyReadflowScripts(unittest.TestCase):
    def test_prepare_packets_writes_v2_manifest_and_light_chunks(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            input_path = tmp_path / "articles.json"
            articles = [
                {
                    "id": f"id-{index}",
                    "title": f"Article {index}",
                    "link": f"https://example.com/{index}",
                    "origin": "Example",
                    "summary": "summary " * 40,
                    "content": "content " * 500,
                }
                for index in range(4)
            ]
            input_path.write_text(json.dumps(articles), encoding="utf-8")

            run_script(
                str(PREPARE),
                "--input",
                str(input_path),
                "--output-dir",
                tmp,
                "--no-fetch-content",
                "--min-chunks",
                "1",
                "--chunk-size",
                "2",
                "--worker-content-chars",
                "30",
            )

            manifest = json.loads((tmp_path / "feedly_readflow_manifest.json").read_text())
            self.assertEqual(manifest["schema_version"], 2)
            self.assertEqual(manifest["chunk_size"], 2)
            self.assertEqual(manifest["triage_chunk_paths"], manifest["chunk_paths"])
            chunk = json.loads(Path(manifest["chunk_paths"][0]).read_text())
            self.assertIn("content_excerpt", chunk[0])
            self.assertLessEqual(len(chunk[0]["content_excerpt"]), 30)
            self.assertNotIn("token", json.dumps(chunk).lower())

    def test_prepare_deep_packets_selects_must_read_and_needs_deep(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            data_path = tmp_path / "feedly_articles.json"
            report_path = tmp_path / "fb_report_0.json"
            data_path.write_text(
                json.dumps(
                    [
                        {"id": "1", "title": "A", "link": "https://e/1", "content": "a"},
                        {"id": "2", "title": "B", "link": "https://e/2", "content": "b"},
                        {"id": "3", "title": "C", "link": "https://e/3", "content": "c"},
                    ]
                ),
                encoding="utf-8",
            )
            report_path.write_text(
                json.dumps(
                    [
                        {"id": "1", "decision": "must_read", "score": 4.0},
                        {"id": "2", "decision": "skim", "needs_deep_read": True},
                        {"id": "3", "decision": "clear", "needs_deep_read": False},
                    ]
                ),
                encoding="utf-8",
            )

            run_script(
                str(PREPARE_DEEP),
                "--report-glob",
                str(tmp_path / "fb_report_*.json"),
                "--data",
                str(data_path),
                "--output-dir",
                tmp,
                "--chunk-size",
                "10",
            )

            manifest = json.loads((tmp_path / "feedly_deep_read_manifest.json").read_text())
            self.assertEqual(manifest["deep_candidate_count"], 2)
            deep_chunk = json.loads((tmp_path / "fb_deep_chunk_0.json").read_text())
            self.assertEqual([item["id"] for item in deep_chunk], ["1", "2"])

    def test_merge_reports_normalizes_legacy_and_deep_overrides(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "fb_report_0.json").write_text(
                json.dumps(
                    [
                        {
                            "id": "1",
                            "title": "A",
                            "link": "https://example.com/a",
                            "decision": "optional",
                            "score": 3.0,
                            "similarity_key": "topic",
                            "core_facts": ["triage fact"],
                        }
                    ]
                ),
                encoding="utf-8",
            )
            (tmp_path / "fb_deep_report_0.json").write_text(
                json.dumps(
                    [
                        {
                            "id": "1",
                            "title": "A",
                            "link": "https://example.com/a",
                            "decision": "must_read",
                            "score": 4.4,
                            "similarity_key": "topic",
                            "analysis_summary": "deep wins",
                        }
                    ]
                ),
                encoding="utf-8",
            )
            low_path = tmp_path / "low.json"
            low_path.write_text("[]", encoding="utf-8")
            output_path = tmp_path / "final.md"

            run_script(
                str(MERGE),
                "--report-glob",
                str(tmp_path / "fb_report_*.json"),
                "--deep-report-glob",
                str(tmp_path / "fb_deep_report_*.json"),
                "--low-quality",
                str(low_path),
                "--output",
                str(output_path),
            )

            report = output_path.read_text(encoding="utf-8")
            self.assertIn("## Must Read", report)
            self.assertIn("deep wins", report)
            self.assertIn("Must Read 1 / Skim 0 / Clear 0", report)

    def test_mark_read_clear_dry_run_selects_clear_reports_and_prefiltered(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "fb_report_0.json").write_text(
                json.dumps(
                    [
                        {"id": "clear-1", "decision": "clear"},
                        {"id": "keep-1", "decision": "must_read"},
                    ]
                ),
                encoding="utf-8",
            )
            low_path = tmp_path / "low.json"
            low_path.write_text(json.dumps([{"id": "prefiltered-1"}]), encoding="utf-8")

            result = run_script(
                str(MARK_READ),
                "--dry-run",
                "clear",
                "--report-glob",
                str(tmp_path / "fb_report_*.json"),
                "--deep-report-glob",
                str(tmp_path / "fb_deep_report_*.json"),
                "--low-quality",
                str(low_path),
            )

            self.assertIn("Entry IDs selected: 2", result.stdout)
            self.assertIn("clear-1", result.stdout)
            self.assertIn("prefiltered-1", result.stdout)


if __name__ == "__main__":
    unittest.main()
