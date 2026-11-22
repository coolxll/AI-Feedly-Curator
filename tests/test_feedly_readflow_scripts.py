import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
PREPARE = ROOT / "skills" / "feedly-readflow" / "scripts" / "prepare_packets.py"
PREPARE_DEEP = ROOT / "skills" / "feedly-readflow" / "scripts" / "prepare_deep_packets.py"
MERGE = ROOT / "skills" / "feedly-readflow" / "scripts" / "merge_reports.py"
MARK_READ = ROOT / "skills" / "feedly-readflow" / "scripts" / "mark_read.py"
TRANSLATE = ROOT / "skills" / "feedly-readflow" / "scripts" / "translate_report_fields.py"


def load_script_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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

    def test_translate_report_fields_dry_run_makes_no_api_calls_and_preserves_files(self):
        translate_mod = load_script_module(TRANSLATE, "translate_report_fields_test")
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            report_path = tmp_path / "fb_report_0.json"
            original_payload = [
                {
                    "id": "en-1",
                    "title": "OpenAI launches a new reasoning model for developers",
                    "reasoning": "Major model release with broad engineering impact.",
                },
                {
                    "id": "zh-1",
                    "title": "这是一篇中文文章标题",
                    "reasoning": "这是一段中文分析摘要。",
                },
            ]
            original_text = json.dumps(original_payload, ensure_ascii=False, indent=2)
            report_path.write_text(original_text, encoding="utf-8")

            with (
                patch.object(translate_mod, "OpenAI", side_effect=AssertionError("OpenAI must not be called")),
                patch.object(
                    translate_mod,
                    "get_openai_task_config",
                    side_effect=AssertionError("config must not be loaded in dry-run"),
                ),
            ):
                rc = translate_mod.main(
                    ["--report-glob", str(tmp_path / "fb_report_*.json"), "--dry-run"]
                )

            self.assertEqual(rc, 0)
            self.assertEqual(report_path.read_text(encoding="utf-8"), original_text)

    def test_mark_read_clear_deep_report_overrides_triage_decision(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "fb_report_0.json").write_text(
                json.dumps(
                    [
                        {"id": "upgraded-1", "decision": "clear", "score": 2.0},
                        {"id": "downgraded-1", "decision": "skim", "score": 3.0},
                        {"id": "still-clear-1", "decision": "clear", "score": 1.5},
                    ]
                ),
                encoding="utf-8",
            )
            (tmp_path / "fb_deep_report_0.json").write_text(
                json.dumps(
                    [
                        {"id": "upgraded-1", "decision": "must_read", "score": 4.5},
                        {"id": "downgraded-1", "decision": "clear", "score": 1.8},
                    ]
                ),
                encoding="utf-8",
            )
            low_path = tmp_path / "low.json"
            low_path.write_text("[]", encoding="utf-8")

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
            self.assertNotIn("upgraded-1", result.stdout)
            self.assertIn("downgraded-1", result.stdout)
            self.assertIn("still-clear-1", result.stdout)

    def test_mark_read_unselected_handles_tmtpost_query_parens_and_excluded_sections(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            articles_path = tmp_path / "feedly_articles.json"
            report_path = tmp_path / "final_report.md"

            articles = [
                {
                    "id": "tmtpost-selected",
                    "link": "https://www.tmtpost.com/7654321?utm_source=rss",
                },
                {
                    "id": "wiki-selected",
                    "link": "https://en.wikipedia.org/wiki/Foo_(bar)",
                },
                {
                    "id": "topic-clear-name-selected",
                    "link": "https://example.com/redis-clear-cache",
                },
                {
                    "id": "clear-sample-unselected",
                    "link": "https://example.com/clear-sample",
                },
                {
                    "id": "prefiltered-unselected",
                    "link": "https://example.com/prefiltered-noise",
                },
                {
                    "id": "truly-missing-unselected",
                    "link": "https://example.com/not-in-report",
                },
            ]
            articles_path.write_text(json.dumps(articles), encoding="utf-8")

            report_md = "\n".join(
                [
                    "# Feedly RSS 阅读报告",
                    "",
                    "## 主题聚合",
                    "",
                    "### Clear cache in Redis",
                    "",
                    "- 代表文章：[Redis Clear Cache](https://example.com/redis-clear-cache) - good",
                    "",
                    "## Must Read",
                    "",
                    "- `4.5` [TMTPost](https://www.tmtpost.com/7654321.html?utm_source=rss)：important",
                    "- `4.2` [Wikipedia](https://en.wikipedia.org/wiki/Foo_(bar))：reference",
                    "",
                    "## 低质量/可清理",
                    "",
                    "- [Clear Sample](https://example.com/clear-sample) 等 3 篇：low value",
                    "",
                    "预过滤阶段直接剔除的低质量（未进入分析）：",
                    "- [Prefiltered Noise](https://example.com/prefiltered-noise)：too_short",
                    "",
                    "## 今日行动建议",
                    "",
                    "- Done.",
                ]
            )
            report_path.write_text(report_md, encoding="utf-8")

            result = run_script(
                str(MARK_READ),
                "--dry-run",
                "unselected",
                "--report",
                str(report_path),
                "--data",
                str(articles_path),
            )

            self.assertIn("Entry IDs selected: 3", result.stdout)
            self.assertNotIn("tmtpost-selected", result.stdout)
            self.assertNotIn("wiki-selected", result.stdout)
            self.assertNotIn("topic-clear-name-selected", result.stdout)
            self.assertIn("clear-sample-unselected", result.stdout)
            self.assertIn("prefiltered-unselected", result.stdout)
            self.assertIn("truly-missing-unselected", result.stdout)

    def test_post_merge_link_fix_inline_links_parens_and_strict_title_matching(self):
        link_fix = load_script_module(
            ROOT / "skills" / "feedly-readflow" / "scripts" / "post_merge_link_fix.py",
            "post_merge_link_fix_test",
        )
        title_to_link = {
            "如何使用 Python 构建高并发服务": "https://www.v2ex.com/t/111111",
            "2026 年芯片供应链深度解析报告": "https://xueqiu.com/123/456",
            "如何看待今天的股市大跌行情分析": "https://example.com/stock-crash",
        }

        report = "\n".join(
            [
                "- 代表文章：[如何使用 Python 构建高并发服务](https://www.v2ex.com/t/999999#reply0) - 值得一看",
                "- `4.5` [2026 年芯片供应链深度解析报告](https://xueqiu.com/today)：深度分析",
                "- [Foo (bar)](https://example.com/foo-bar)",
                "- [Broken (bar)(https://example.com/broken-bar)",
            ]
        )

        rewritten, link_fixes = link_fix.rewrite_markdown_links(report, title_to_link)
        self.assertEqual(link_fixes, 2)
        self.assertIn(
            "- 代表文章：[如何使用 Python 构建高并发服务](https://www.v2ex.com/t/111111#reply0) - 值得一看",
            rewritten,
        )
        self.assertIn(
            "- `4.5` [2026 年芯片供应链深度解析报告](https://xueqiu.com/123/456)：深度分析",
            rewritten,
        )

        fixed_md, md_fixes = link_fix.fix_broken_markdown(rewritten)
        self.assertEqual(md_fixes, 1)
        self.assertIn("- [Foo (bar)](https://example.com/foo-bar)", fixed_md)
        self.assertNotIn("]]", fixed_md)
        self.assertIn("- [Broken (bar)](https://example.com/broken-bar)", fixed_md)

        # Short unrelated title or 5-char shared prefix must not hijack URL
        self.assertIsNone(link_fix.find_link_for_title("如何看待", title_to_link))
        self.assertIsNone(
            link_fix.find_link_for_title("如何看待某公司发布的新手机评测", title_to_link)
        )
        # Exact normalized match still works
        self.assertEqual(
            link_fix.find_link_for_title("  如何使用  python 构建高并发服务 ", title_to_link),
            "https://www.v2ex.com/t/111111",
        )

    def test_translate_report_fields_repo_root_and_list_index_preservation(self):
        translate_mod = load_script_module(TRANSLATE, "translate_report_fields_fixes_test")
        self.assertEqual(Path(translate_mod._REPO_ROOT).resolve(), ROOT.resolve())

        # Mixed scalar + indexed output for same field must not crash
        parsed_mixed = translate_mod.parse_translation(
            "[core_facts]: plain text\n[core_facts][1]: 事实一",
            [("core_facts", 1)],
        )
        self.assertEqual(parsed_mixed["core_facts"], [None, "事实一"])

        # Empty strings in list must keep original indices and length
        item = {
            "id": "list-1",
            "core_facts": ["", "First English fact", "", "Second English fact", ""],
        }
        fake_resp = type(
            "Resp",
            (),
            {
                "choices": [
                    type(
                        "Choice",
                        (),
                        {
                            "message": type(
                                "Msg",
                                (),
                                {
                                    "content": (
                                        "[core_facts][1]: 第一条中文事实\n"
                                        "[core_facts][3]: 第二条中文事实"
                                    )
                                },
                            )()
                        },
                    )()
                ]
            },
        )()
        fake_client = type(
            "Client",
            (),
            {
                "chat": type(
                    "Chat",
                    (),
                    {
                        "completions": type(
                            "Comp",
                            (),
                            {"create": staticmethod(lambda **kw: fake_resp)},
                        )()
                    },
                )()
            },
        )()
        fake_cfg = type("Cfg", (), {"model": "gpt-4o-mini", "api_key": "k", "base_url": None})()
        with patch.object(
            translate_mod,
            "build_chat_completion_kwargs",
            side_effect=lambda cfg, **kw: kw,
        ):
            translated_item = translate_mod.translate_item(fake_client, fake_cfg, item)

        self.assertEqual(
            translated_item["core_facts"],
            ["", "第一条中文事实", "", "第二条中文事实", ""],
        )

    def test_merge_reports_missing_ids_score_parsing_and_low_quality_fallback(self):
        merge_mod = load_script_module(MERGE, "merge_reports_fixes_test")

        # _score parses numeric strings and excludes booleans
        self.assertEqual(merge_mod._score({"score": "4.5"}), 4.5)
        self.assertEqual(merge_mod._score({"score": True}), 0.0)
        self.assertEqual(merge_mod._score({"score": False}), 0.0)
        self.assertEqual(merge_mod._score({"score": "not-a-num"}), 0.0)

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            # Two items without "id" must both be preserved
            (tmp_path / "fb_report_0.json").write_text(
                json.dumps(
                    [
                        {"title": "No ID 1", "decision": "must_read", "score": "4.2", "similarity_key": "k1"},
                        {"title": "No ID 2", "decision": "skim", "score": "3.1", "similarity_key": "k2"},
                    ]
                ),
                encoding="utf-8",
            )
            data_path = tmp_path / "feedly_articles.json"
            data_path.write_text("[]", encoding="utf-8")
            # Place prefiltered low-quality file next to --data, without passing --low-quality
            (tmp_path / "feedly_prefiltered_low_quality.json").write_text(
                json.dumps([{"id": "low-1", "title": "Prefiltered Item", "link": "https://e/low"}]),
                encoding="utf-8",
            )
            output_path = tmp_path / "final.md"

            loaded = merge_mod.load_reports(str(tmp_path / "fb_report_*.json"))
            self.assertEqual(len(loaded), 2)
            merged = merge_mod.merge_report_items(loaded, [])
            self.assertEqual(len(merged), 2)

            run_script(
                str(MERGE),
                "--report-glob",
                str(tmp_path / "fb_report_*.json"),
                "--deep-report-glob",
                str(tmp_path / "fb_deep_report_*.json"),
                "--data",
                str(data_path),
                "--output",
                str(output_path),
            )
            report = output_path.read_text(encoding="utf-8")
            self.assertIn("No ID 1", report)
            self.assertIn("No ID 2", report)
            self.assertIn("Prefiltered Item", report)


if __name__ == "__main__":
    unittest.main()
