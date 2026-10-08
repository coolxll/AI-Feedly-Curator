"""Smoke tests for the ``feedly_filter.py`` CLI entry point.

These guard against a real regression: the ``process_stream`` import was moved
from the ``feedly_workflows`` facade to ``filter_workflows`` (where it never
existed), silently breaking the whole CLI for every subcommand. No test
imported this module, so the breakage shipped.

The tests below fail fast if:
* the module stops importing (bad import source / missing symbol);
* a name used inside ``main()`` is not defined at module scope;
* the ``process-stream`` subcommand loses its backing callable.
"""

from __future__ import annotations

import ast
import builtins
import importlib
import inspect
import unittest
from pathlib import Path
from unittest.mock import patch

import feedly_filter


CLI_PATH = Path(feedly_filter.__file__)


class TestFeedlyFilterCliImports(unittest.TestCase):
    def test_module_imports(self):
        """The CLI module must import cleanly (this is the regression guard)."""
        module = importlib.reload(feedly_filter)
        self.assertTrue(callable(module.main))

    def test_process_stream_resolves_from_facade(self):
        """``process_stream`` must be the readflow implementation via the facade."""
        from rss_analyzer.feedly_workflows import process_stream as facade_fn

        self.assertIs(feedly_filter.process_stream, facade_fn)
        self.assertEqual(
            facade_fn.__module__,
            "rss_analyzer.readflow_workflows",
            "process_stream should live in readflow_workflows and be re-exported",
        )

    def test_every_module_level_name_used_in_main_is_defined(self):
        """Catch module-level names referenced in main() but never imported/defined.

        Mirrors the original bug: ``process_stream`` was referenced but not
        importable, which only surfaced at runtime. Locals, parameters, and
        builtins are excluded so only genuine module-scope lookups remain.
        """
        tree = ast.parse(CLI_PATH.read_text(encoding="utf-8"))
        main_node = next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "main"
        )

        # Names bound at module scope: imports plus top-level assignments/defs.
        bound: set[str] = set()
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                bound.add(node.name)
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        bound.add(target.id)
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    bound.add(alias.asname or alias.name)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    bound.add((alias.asname or alias.name).split(".")[0])

        # Names bound *inside* main(): parameters and any assignment target.
        local: set[str] = {
            arg.arg
            for arg in (
                list(main_node.args.args)
                + list(main_node.args.kwonlyargs)
                + list(main_node.args.posonlyargs)
            )
        }
        for node in ast.walk(main_node):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
                local.add(node.id)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                local.add(node.name)
            elif isinstance(node, ast.ExceptHandler) and node.name:
                local.add(node.name)
            elif isinstance(node, (ast.comprehension,)):
                for t in ast.walk(node.target):
                    if isinstance(t, ast.Name):
                        local.add(t.id)

        builtins_ok = set(dir(builtins)) | {"__builtins__"}
        used = {
            node.id
            for node in ast.walk(main_node)
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
        }

        unresolved = used - bound - local - builtins_ok
        self.assertEqual(
            unresolved,
            set(),
            f"main() references undefined module-level names: {sorted(unresolved)}",
        )


class TestFeedlyFilterCliParser(unittest.TestCase):
    def test_all_subcommands_are_registered(self):
        """Every advertised subcommand must be accepted by the parser.

        Parsing is exercised for real (not a source-text grep) so a broken
        subparser registration fails the test.
        """
        parser = feedly_filter._build_parser()
        for cmd in ("newsflash", "low-score", "all", "process-stream"):
            with self.subTest(cmd=cmd):
                args = parser.parse_args([cmd])
                self.assertEqual(args.cmd, cmd)

    def test_unknown_subcommand_is_rejected(self):
        parser = feedly_filter._build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args(["definitely-not-a-command"])

    def test_parser_help_exits_cleanly(self):
        """``--help`` must succeed without touching the network."""
        with self.assertRaises(SystemExit) as ctx:
            feedly_filter.main(["--help"])
        self.assertEqual(ctx.exception.code, 0)

    def test_main_signature_accepts_argv(self):
        """main() should accept an optional argv for testability."""
        params = list(inspect.signature(feedly_filter.main).parameters)
        self.assertIn("argv", params)


class TestFeedlyFilterArgumentOrder(unittest.TestCase):
    """Global flags must work before *and* after the subcommand.

    Regression guard: using ``parents=[...]`` naively made the subparser
    re-apply its own defaults, silently discarding ``--limit 5`` when placed
    before the subcommand (it fetched 1000 instead of 5).
    """

    def setUp(self):
        self.parser = feedly_filter._build_parser()

    def _parse(self, argv):
        return self.parser.parse_args(argv)

    def test_limit_before_and_after_subcommand(self):
        before = self._parse(["--limit", "5", "newsflash"])
        after = self._parse(["newsflash", "--limit", "5"])
        self.assertEqual(before.limit, 5)
        self.assertEqual(after.limit, 5)

    def test_flags_before_subcommand_are_not_clobbered(self):
        args = self._parse(["--limit", "5", "--dry-run", "newsflash"])
        self.assertEqual(args.limit, 5)
        self.assertTrue(args.dry_run)

    def test_stream_id_before_and_after_subcommand(self):
        before = self._parse(["--stream-id", "feed/x", "process-stream"])
        after = self._parse(["process-stream", "--stream-id", "feed/x"])
        self.assertEqual(before.stream_id, "feed/x")
        self.assertEqual(after.stream_id, "feed/x")

    def test_store_false_flag_before_and_after_subcommand(self):
        before = self._parse(["--no-incremental-mark", "newsflash"])
        after = self._parse(["newsflash", "--no-incremental-mark"])
        self.assertFalse(before.incremental_mark)
        self.assertFalse(after.incremental_mark)

    def test_later_flag_overrides_earlier(self):
        args = self._parse(["--limit", "5", "newsflash", "--limit", "7"])
        self.assertEqual(args.limit, 7)

    def test_defaults_apply_when_no_flags_given(self):
        args = self._parse(["newsflash"])
        self.assertEqual(args.limit, 1000)
        self.assertFalse(args.dry_run)
        self.assertIsNone(args.stream_id)


class TestFeedlyFilterAuthFailure(unittest.TestCase):
    """Auth failures must exit cleanly, not raise a traceback."""

    def test_auth_error_returns_nonzero(self):
        """Auth failures must not escape main() as a raw exception."""
        from rss_analyzer.feedly_auth import FeedlyAuthError

        with patch(
            "rss_analyzer.filter_workflows.feedly_fetch_unread",
            side_effect=FeedlyAuthError("token expired"),
        ):
            rc = feedly_filter.main(["--limit", "1", "--dry-run", "newsflash"])
        self.assertEqual(rc, 1)


if __name__ == "__main__":
    unittest.main()
