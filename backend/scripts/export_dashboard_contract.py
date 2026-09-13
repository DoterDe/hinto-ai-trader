"""Offline contract/help export. --check detects frontend/backend contract drift."""

import argparse
import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from src.application.explanations import MODULES, TERMS
from src.application.live_paper_telemetry import LiveDashboardSnapshot
from pydantic.json_schema import GenerateJsonSchema


class DashboardSchema(GenerateJsonSchema):
    def decimal_schema(self, schema):
        result = super().decimal_schema(schema)
        if self.mode == 'serialization':
            # Decimal JSON can contain scientific notation (including 0E+33).
            # Pydantic's generated fixed-point pattern omits that valid output.
            result['pattern'] = r'^[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?$'
        return result


def artifacts() -> dict[Path, str]:
    frontend = BACKEND.parent / 'frontend' / 'src'
    schema = LiveDashboardSnapshot.model_json_schema(mode='serialization', schema_generator=DashboardSchema)
    # FastAPI uses model_dump with defaults included. Declare that actual output
    # shape, including nullable defaults, rather than the more permissive input.
    def output_required(node):
        if isinstance(node, dict):
            if 'properties' in node:
                node['required'] = list(node['properties'])
            for value in node.values():
                output_required(value)
        elif isinstance(node, list):
            for value in node:
                output_required(value)
    output_required(schema)
    objects = {
        frontend / 'api' / 'dashboard.schema.json': schema,
        frontend / 'help' / 'catalog.json': {
            'terms': [item.model_dump(mode='json') for item in TERMS],
            'modules': [item.model_dump(mode='json') for item in MODULES],
        },
    }
    return {path: json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False)+'\n' for path, value in objects.items()}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    for path, content in artifacts().items():
        if args.check:
            if not path.exists() or path.read_text(encoding='utf-8') != content:
                raise SystemExit(f'Outdated generated contract: {path.name}')
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding='utf-8', newline='\n')
    print('Dashboard schema and explanation catalog: '+('verified' if args.check else 'exported'))
