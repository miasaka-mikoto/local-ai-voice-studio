"""Lightweight adapter CLI; all commands are model-free by default."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

from .base import AdapterError
from .exporters import ExporterRegistry, export_game_manifest
from .game_manifest import atomic_text_write, export_lines, import_lines
from .mock_engine import MockEngineAdapter
from .models import SynthesisRequest
from .registry import EngineRegistry


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Local AI Voice Studio adapter utilities")
    commands = parser.add_subparsers(dest="command", required=True)

    capabilities = commands.add_parser("capabilities", help="import and print sanitized capability manifests")
    capabilities.add_argument("--deployment", action="append", required=True, type=Path)
    capabilities.add_argument("--output", type=Path)
    capabilities.add_argument("--force", action="store_true", help="replace an existing non-input output")

    normalize = commands.add_parser("normalize-game", help="normalize CSV/JSON/JSONL game lines")
    normalize.add_argument("input", type=Path)
    normalize.add_argument("output", type=Path)
    normalize.add_argument("--force", action="store_true", help="replace an existing non-input output")

    export = commands.add_parser("export-game", help="create a game-engine import manifest")
    export.add_argument("target", choices=ExporterRegistry().targets)
    export.add_argument("input", type=Path)
    export.add_argument("output", type=Path)
    export.add_argument("--audio-root", default="Audio/Voice")
    export.add_argument("--force", action="store_true", help="replace an existing non-input output")

    mock = commands.add_parser("mock", help="generate deterministic PCM-24 mock audio")
    mock.add_argument("--line-id", required=True)
    mock.add_argument("--character-id", required=True)
    mock.add_argument("--text", required=True)
    mock.add_argument("--output-dir", required=True, type=Path)
    mock.add_argument("--locale", default="und")
    mock.add_argument("--emotion", default="neutral")
    mock.add_argument("--emotion-intensity", type=float, default=0.5)
    mock.add_argument("--seed", type=int, default=0)
    mock.add_argument("--take", type=int, default=0)
    mock.add_argument("--duration", type=float)
    return parser


def _write_or_print(payload: object, output: Path | None) -> None:
    rendered = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if output is None:
        print(rendered, end="")
        return
    atomic_text_write(output, rendered)


def _validate_destination(
    output: Path | None,
    inputs: list[Path],
    *,
    force: bool,
) -> None:
    if output is None:
        return
    output_resolved = output.resolve(strict=False)
    for source in inputs:
        source_resolved = source.resolve(strict=False)
        aliases = output_resolved == source_resolved
        if output.exists() and source.exists():
            try:
                aliases = aliases or os.path.samefile(output, source)
            except OSError:
                pass
        if aliases:
            raise ValueError("output must not overwrite or alias an input file")
    if output.exists() and not force:
        raise FileExistsError("output already exists; pass --force to replace it")


def _execute(args: argparse.Namespace) -> int:
    if args.command == "capabilities":
        _validate_destination(args.output, list(args.deployment), force=args.force)
        registry = EngineRegistry()
        sources = []
        warnings = []
        manifests = []
        for path in args.deployment:
            result = registry.import_manifest(path)
            sources.append(result.source_path)
            warnings.extend(result.warnings)
            manifests.append(
                {
                    "source": result.source_path,
                    "schema_version": result.schema_version,
                    "hardware": dict(result.hardware),
                    "policy": dict(result.policy),
                    "warnings": list(result.warnings),
                }
            )
        _write_or_print(
            {
                "schema_version": "1.0",
                "sources": sources,
                "manifests": manifests,
                "warnings": warnings,
                "engines": registry.snapshot(),
            },
            args.output,
        )
        return 0
    if args.command == "normalize-game":
        _validate_destination(args.output, [args.input], force=args.force)
        export_lines(import_lines(args.input), args.output)
        print(args.output)
        return 0
    if args.command == "export-game":
        _validate_destination(args.output, [args.input], force=args.force)
        export_game_manifest(
            args.target,
            import_lines(args.input),
            args.output,
            audio_root=args.audio_root,
        )
        print(args.output)
        return 0
    if args.command == "mock":
        request = SynthesisRequest(
            line_id=args.line_id,
            character_id=args.character_id,
            text=args.text,
            language=args.locale,
            emotion=args.emotion,
            emotion_intensity=args.emotion_intensity,
            duration_budget_seconds=args.duration,
            engine_id="mock",
            seed=args.seed,
            take_index=args.take,
            metadata={"locale": args.locale},
        )
        result = MockEngineAdapter().synthesize(request, args.output_dir)
        print(json.dumps(result.to_dict(), ensure_ascii=False))
        return 0
    raise AssertionError(f"unhandled command: {args.command}")


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        return _execute(args)
    except (AdapterError, OSError, ValueError, json.JSONDecodeError) as exc:
        message = " ".join(str(exc).splitlines())[:400] or type(exc).__name__
        print(f"error: {message}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
