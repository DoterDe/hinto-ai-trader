"""Generate representative frontend fixtures through the real offline runtime."""
import asyncio
import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from backtest_fixtures import wave_bars
from live_paper_fixtures import publish_group, running, ManualLiveClock
from src.application.live_paper_coordinator import LivePaperCoordinator
from src.application.live_paper_settings import LivePaperSettings
from src.application.decision_settings import DecisionSettings
from src.application.live_paper_telemetry import dashboard_snapshot
from src.application.market_data_hub import MarketDataHub


async def examples():
    clock = ManualLiveClock()
    disabled = LivePaperCoordinator(MarketDataHub(('BTCUSDT',), clock=clock.now),
        clock=clock, settings=LivePaperSettings(enabled=False))
    result = {'disabled': dashboard_snapshot(disabled).model_dump(mode='json')}
    async with running() as (runtime, hub, clock):
        for event in wave_bars():
            await publish_group(runtime, hub, clock, [event])
        result['running'] = dashboard_snapshot(runtime, 6).model_dump(mode='json')
    async with running() as (runtime, hub, clock):
        # Choose an actual open position for the missing-horizon example.
        for event in wave_bars():
            await publish_group(runtime, hub, clock, [event])
            if runtime.portfolio.active:
                break
        assert runtime.portfolio.active
        runtime.portfolio.invalidate()
        result['incomplete'] = dashboard_snapshot(runtime, 6).model_dump(mode='json')
    async with running(decision_settings=DecisionSettings(min_contributing_strategies=3)) as (runtime, hub, clock):
        for event in wave_bars():
            await publish_group(runtime, hub, clock, [event])
            if runtime.decisions[-1].portfolio.upstream.outcome == 'BLOCKED':
                break
        assert runtime.decisions[-1].portfolio.upstream.outcome == 'BLOCKED'
        result['blocked'] = dashboard_snapshot(runtime, 6).model_dump(mode='json')
    return result


if __name__ == '__main__':
    output = BACKEND.parent / 'frontend' / 'src' / 'test' / 'fixtures'
    check = '--check' in sys.argv
    for name, value in asyncio.run(examples()).items():
        content = json.dumps(value, indent=2, allow_nan=False)+'\n'
        path = output / (name+'.json')
        if check:
            if not path.exists() or path.read_text(encoding='utf-8') != content:
                raise SystemExit('Outdated dashboard fixture: '+name)
        else:
            output.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding='utf-8', newline='\n')
    print('Four deterministic runtime dashboard fixtures '+('verified' if check else 'exported'))
