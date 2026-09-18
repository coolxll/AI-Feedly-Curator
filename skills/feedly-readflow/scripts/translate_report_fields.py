#!/usr/bin/env python3
"""Translate English-heavy fields in worker JSON reports to Chinese.

Reads every ``fb_report_*.json``, identifies items whose text fields are
English-heavy, translates the relevant fields in one LLM call per item, and
writes the report back in place. Fields are translated in place so that
``merge_reports.py`` picks up the Chinese versions.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# Ensure the repo root (cwd when run) is importable as a package path.
_REPO_ROOT = os.getcwd()
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from openai import OpenAI

from rss_analyzer.config import build_chat_completion_kwargs, get_openai_task_config


# Fields that carry prose worth translating. Numeric/enum fields (score,
# decision, readflow_domain, ...) and pure identifiers (id, link, domain,
# origin, content_source, similarity_key) are left untouched.
TRANSLATABLE_FIELDS = [
    "title",
    "event",
    "actors",
    "region",
    "core_fact",
    "core_facts",
    "why_it_matters",
    "rec",
    "reasoning",
    "analysis_summary",
]


def is_english_heavy(text: str) -> bool:
    """True when latin alphabetic chars dominate the alphanumeric text."""
    if not text:
        return False
    latin = sum(1 for c in text if c.isascii() and c.isalpha())
    total = sum(1 for c in text if c.isalpha())
    return total > 0 and latin / total > 0.5


def collect_text(item: dict) -> str:
    parts = []
    for f in TRANSLATABLE_FIELDS:
        v = item.get(f)
        if isinstance(v, list):
            parts.extend(f"[{f}]{i+1}: {x}" for i, x in enumerate(v) if x)
        elif v:
            parts.append(f"[{f}]: {v}")
    return "\n".join(parts)


def build_prompt(item: dict) -> tuple[str, list[str]]:
    """Return (user_prompt, field_order) for one item translation."""
    lines = []
    field_order = []
    for f in TRANSLATABLE_FIELDS:
        v = item.get(f)
        if isinstance(v, list):
            for i, x in enumerate(v):
                if x:
                    lines.append(f"[{f}][{i}]: {x}")
                    field_order.append((f, i))
        elif v:
            lines.append(f"[{f}]: {v}")
            field_order.append((f, None))
    body = "\n".join(lines)
    prompt = (
        "把下面每个字段的英文内容翻译成简体中文，保持专业术语、公司名、人名、"
        "数字、URL 不变。只输出翻译后的字段，格式严格为 `[field]: 译文` 或 "
        "`[field][index]: 译文`（对列表项）。不要输出任何解释或多余文字。\n\n"
        + body
    )
    return prompt, field_order


_FIELD_RE = re.compile(r"^\[([^\]]+)\](?:\[(\d+)\])?\s*:\s*(.*)$")


def parse_translation(text: str, field_order: list) -> dict:
    """Parse model output back into a {field: value|list} mapping."""
    out: dict = {}
    for line in text.splitlines():
        m = _FIELD_RE.match(line.strip())
        if not m:
            continue
        field, idx, val = m.group(1), m.group(2), m.group(3).strip()
        if idx:
            out.setdefault(field, {})[int(idx)] = val
        else:
            out[field] = val
    # Reconstruct lists preserving original order
    result: dict = {}
    seen_lists: dict = {}
    for field, idx in field_order:
        if idx is None:
            if field in out:
                result[field] = out[field]
        else:
            if field not in seen_lists:
                seen_lists[field] = []
            # Only append if we have this index; gaps kept from original
            if field in out and idx in out[field]:
                seen_lists[field].append(out[field][idx])
            else:
                seen_lists[field].append(None)
    for field, lst in seen_lists.items():
        # Preserve original list length: replace None with original values
        orig = None
        for k, v in field_order:
            if k == field:
                orig = v
                break
        # Fallback: if any None, keep them so length matches
        result[field] = lst
    return result


def translate_item(client: OpenAI, cfg, item: dict) -> dict:
    prompt, field_order = build_prompt(item)
    if not field_order:
        return item
    try:
        resp = client.chat.completions.create(
            **build_chat_completion_kwargs(
                cfg,
                messages=[
                    {"role": "system", "content": "你是专业中英翻译，输出严格遵循给定字段格式。"},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.2,
            )
        )
        text = resp.choices[0].message.content or ""
        translated = parse_translation(text, field_order)
    except Exception as e:
        sys.stderr.write(f"  translate error for {item.get('id','?')}: {e}\n")
        return item
    new_item = dict(item)
    for field, val in translated.items():
        if val is None:
            continue
        if isinstance(val, list):
            # Merge translated entries with original (preserve None positions)
            orig = item.get(field) or []
            merged = []
            for i, v in enumerate(val):
                if v is not None and i < len(orig):
                    merged.append(v)
                elif i < len(orig):
                    merged.append(orig[i])
            new_item[field] = merged if merged else orig
        else:
            new_item[field] = val
    return new_item


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-glob", default="tmp/readflow/fb_report_*.json")
    parser.add_argument("--default-model", default="gpt-4o-mini")
    parser.add_argument("--limit", type=int, default=0, help="0 = all")
    parser.add_argument("--workers", type=int, default=8, help="concurrent LLM calls")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    cfg = get_openai_task_config("translate", args.default_model)
    client = OpenAI(
        api_key=cfg.api_key,
        base_url=cfg.base_url,
        default_headers={"User-Agent": "feedly-readflow-translate"},
    ) if cfg.base_url else OpenAI(api_key=cfg.api_key)

    paths = sorted(glob.glob(args.report_glob))
    # Collect (path, index, item) jobs for all English-heavy items.
    jobs = []
    for path in paths:
        items = json.loads(Path(path).read_text(encoding="utf-8"))
        for i, item in enumerate(items):
            text = collect_text(item)
            if is_english_heavy(text):
                jobs.append((path, i, item))
    if args.limit:
        jobs = jobs[: args.limit]
    print(f"jobs to translate: {len(jobs)} with {args.workers} workers", flush=True)

    # Translate concurrently; group results by path.
    by_path: dict[str, dict[int, dict]] = {}
    done = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futures = {
            ex.submit(translate_item, client, cfg, item): (path, i)
            for (path, i, item) in jobs
        }
        for fut in as_completed(futures):
            path, i = futures[fut]
            try:
                new_item = fut.result()
            except Exception as e:
                sys.stderr.write(f"  job error {path}[{i}]: {e}\n")
                new_item = None
            if new_item is not None:
                by_path.setdefault(path, {})[i] = new_item
            done += 1
            if done % 20 == 0 or done == len(jobs):
                print(f"  {done}/{len(jobs)} translated", flush=True)

    # Write back per path.
    written = 0
    for path, idx_map in by_path.items():
        if not idx_map:
            continue
        p = Path(path)
        items = json.loads(p.read_text(encoding="utf-8"))
        for i, new_item in idx_map.items():
            if i < len(items) and new_item != items[i]:
                items[i] = new_item
        p.write_text(
            json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        written += 1
        print(f"updated {path}", flush=True)
    print(f"wrote {written} files, translated {done} items", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
