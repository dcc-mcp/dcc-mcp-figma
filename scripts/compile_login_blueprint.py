"""Compile a private offline design into bounded, typed wire data only.

No Figma operation, process launch, installation, credential or permission is
created. Use a fresh output directory; existing files are never replaced.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from dcc_mcp_figma.blueprint import BlueprintError, compilation_report, compile_blueprint


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise BlueprintError()
        result[key] = value
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        default=str(Path(__file__).resolve().parents[2] / "dcc-login-showcase/native-blueprint.json"),
    )
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args(argv)
    try:
        source_bytes = Path(args.source).read_bytes()
        source = json.loads(source_bytes.decode("utf-8"), object_pairs_hook=unique_object)
        wire = compile_blueprint(source)
        report = compilation_report(source, wire)
        report["input_sha256"] = hashlib.sha256(source_bytes).hexdigest()
        encoded = json.dumps(
            wire, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
        output = Path(args.output_dir)
        output.mkdir(parents=True, exist_ok=False)
        (output / "wire.json").write_bytes(encoded)
        (output / "compiler-report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    except (BlueprintError, OSError, ValueError, TypeError, RecursionError):
        print(
            "Blueprint compilation stopped; source or fresh output requirements were not met.",
            file=sys.stderr,
        )
        return 2
    print(
        json.dumps(
            {"wire_sha256": report["wire_sha256"], "stats": report["stats"], "native_execution": "NOT_RUN"}
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
