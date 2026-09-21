"""Offline deterministic JSON export; --check proves repeatability or checks a file."""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.application.backtest_settings import BacktestSettings
from src.application.historical_dataset_codec import HistoricalDatasetCodec
from src.application.validation_example import example_report
from src.application.validation_report import build_validation_report
from src.application.validation_report_codec import ValidationReportCodec
from src.application.walk_forward_evaluator import WalkForwardEvaluator
from src.domain.historical_dataset import MAX_JSON_BYTES
from src.domain.validation_report import MAX_REPORT_BYTES
from src.domain.walk_forward import WalkForwardProtocol


async def export(args):
    async def run():
        if args.dataset is None:
            return await example_report(mode=args.mode)
        with args.dataset.open("rb") as stream:
            data = HistoricalDatasetCodec.decode(stream.read(MAX_JSON_BYTES + 1))
        protocol = WalkForwardProtocol(dataset_id=data.manifest.dataset_id, symbols=data.manifest.symbols,
            interval=data.manifest.interval, mode=args.mode,
            rolling_context_boundaries=50 if args.mode == "ROLLING" else None)
        costs = BacktestSettings(holding_period_bars=5, fee_bps_per_side=5, slippage_bps_per_side=2, chronological_segments=4)
        return build_validation_report(data, await WalkForwardEvaluator(protocol, backtest_settings=costs).run(data), costs)

    first = await run()
    payload = ValidationReportCodec.encode(first)
    if args.check:
        if args.output:
            with args.output.open("rb") as stream:
                existing = stream.read(MAX_REPORT_BYTES + 1)
            ValidationReportCodec.decode(existing)
            if existing != payload:
                raise ValueError("export differs from fixed input replay")
        else:
            second = ValidationReportCodec.encode(await run())
            if payload != second:
                raise ValueError("repeated validation report differs")
        print("Deterministic validation report verified:", first.report_id, "bytes:", len(payload))
    elif args.output:
        args.output.write_bytes(payload)
        print("Validation report exported:", first.report_id, "bytes:", len(payload))
    else:
        raise ValueError("use --output FILE or --check; no implicit filesystem destination")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, help="canonical local dataset; otherwise an explicitly synthetic fixture")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--mode", choices=("EXPANDING", "ROLLING"), default="EXPANDING")
    parser.add_argument("--check", action="store_true")
    asyncio.run(export(parser.parse_args()))
