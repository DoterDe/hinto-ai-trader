import ast
import json
import re
from pathlib import Path

from scripts.export_dashboard_contract import artifacts
from src.application.explanations import MODULES
from src.application.live_paper_telemetry import LiveDashboardSnapshot

ROOT = Path(__file__).resolve().parents[2]


def test_generated_dashboard_schema_and_help_match_backend():
    for path, content in artifacts().items():
        assert path.read_text(encoding='utf-8') == content, path


def test_exported_decimal_contract_covers_actual_scientific_serialization():
    schema = json.loads(next(content for path, content in artifacts().items() if path.name == 'dashboard.schema.json'))
    pattern = schema['$defs']['PaperPortfolioState']['properties']['gross_exposure_fraction']['anyOf'][0]['pattern']
    for value in ('0E+33', '1.25E-10', '-0.5', '123456789012345678.00001', '0'):
        assert re.fullmatch(pattern, value)
    for value in ('NaN', 'Infinity', '-Infinity', '', '.', '+', '1e'):
        assert not re.fullmatch(pattern, value)


def test_real_runtime_frontend_fixtures_revalidate_and_reconcile_unknowns():
    directory = ROOT / 'frontend' / 'src' / 'test' / 'fixtures'
    for name in ('disabled', 'running', 'incomplete', 'blocked'):
        model = LiveDashboardSnapshot.model_validate_json((directory / (name+'.json')).read_text())
        assert model.status.mode == 'paper'
        if name == 'incomplete':
            assert model.portfolio.state.marked_equity is None and not model.portfolio.valuation_complete
            assert model.positions.active and model.positions.active[0].unrealized_net_pnl is None
        if name == 'blocked':
            assert model.decisions[0].portfolio.upstream.outcome == 'BLOCKED'
            assert model.decisions[0].portfolio.action == 'IGNORED'


def test_explanation_source_modules_exist():
    assert all((ROOT / module.source_path).exists() for module in MODULES)


def test_phase8_runtime_has_no_execution_or_private_network_dependency():
    paths = list((ROOT / 'backend' / 'src' / 'application').glob('live_*.py'))
    paths += [ROOT / 'backend' / 'src' / 'api' / 'live_paper.py', ROOT / 'backend' / 'src' / 'domain' / 'live_paper.py']
    forbidden_names = {'TradeIntent', 'ApprovedTradeIntent', 'RiskEngine', 'PaperExecutionGateway', 'ExecutionGateway', 'OpenAI'}
    forbidden_modules = ('src.infrastructure', 'src.application.risk_engine', 'httpx', 'requests', 'websockets',
        'openai', 'sqlite3', 'sqlalchemy', 'redis', 'optuna', 'sklearn', 'tensorflow', 'torch')
    for path in paths:
        for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
            if isinstance(node, ast.Name):
                assert node.id not in forbidden_names, path
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or '').startswith(forbidden_modules), path
            if isinstance(node, ast.Import):
                assert all(not item.name.startswith(forbidden_modules) for item in node.names), path
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                assert node.func.attr not in {'submit_order', 'create_order', 'place_order', 'transfer', 'withdraw', 'deposit'}, path
