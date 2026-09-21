"""Generate/check the frontend's actual backend validation projection offline."""

import argparse
import asyncio
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.application.validation_example import example_report
from src.application.validation_telemetry import project_validation


async def main(check, medium):
    filename = "validation.medium.json" if medium else "validation.json"
    path = Path(__file__).resolve().parents[2] / "frontend/src/test/fixtures" / filename
    if medium:
        from validation_release_fixture import medium_report
        report = await medium_report()
    else:
        report = await example_report()
    content = project_validation(report).model_dump_json(indent=2) + "\n"
    if check:
        if not path.exists() or path.read_text(encoding="utf-8") != content:
            raise SystemExit("Validation projection fixture is outdated")
    else:
        path.write_text(content, encoding="utf-8", newline="\n")
    print("Deterministic validation projection fixture " + ("verified" if check else "exported"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--medium", action="store_true")
    args = parser.parse_args()
    asyncio.run(main(args.check, args.medium))
