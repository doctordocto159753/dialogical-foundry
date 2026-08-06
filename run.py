#!/usr/bin/env python3
"""
CLI entrypoint. Runs a data-defined pipeline end-to-end.

  python run.py pipelines/foundry_v1.json --format both --brief "..."

With provider=mock (the default baked into the demo pipeline) this needs no key
and no network — it proves the full orchestration. Switch a node's model.provider
to "anthropic" (and set ANTHROPIC_API_KEY) to run it for real; no engine code
changes.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from engine import Pipeline, PipelineExecutor


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pipeline", nargs="?", default="pipelines/foundry_v1.json", help="path to pipeline JSON")
    ap.add_argument("--brief", default="A local-first tool that turns a rough idea into a mature, spec'd MVP.",
                    help="the user's initial brief (<=2000 words)")
    ap.add_argument("--format", choices=["json", "md", "both"], default=None,
                    help="output format (default: pipeline's default_format)")
    ap.add_argument("--runs", default="runs", help="runs root dir")
    args = ap.parse_args()

    data = json.loads(Path(args.pipeline).read_text(encoding="utf-8"))
    pipeline = Pipeline.from_dict(data)
    ex = PipelineExecutor(pipeline, runs_root=args.runs, fmt=args.format)
    ex.run(user_brief=args.brief)


if __name__ == "__main__":
    main()
