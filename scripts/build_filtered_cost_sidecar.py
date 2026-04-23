#!/usr/bin/env python3

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

DEFAULT_RUN_ID_ALIASES = [
    'user_unique_run_id',
    'user_nf_unique_run_id',
]
KEEP_COLUMNS = [
    'line_item_usage_start_date',
    'line_item_usage_end_date',
    'line_item_product_code',
    'line_item_line_item_type',
    'line_item_resource_id',
    'product_instance_type',
    'product_product_family',
    'resource_tags',
    'line_item_unblended_cost',
    'line_item_net_unblended_cost',
    'split_line_item_split_cost',
    'split_line_item_net_split_cost',
    'split_line_item_unused_cost',
    'split_line_item_net_unused_cost',
]


def load_run_rows(csv_path: Path) -> list[dict[str, str]]:
    with csv_path.open() as handle:
        return list(csv.DictReader(handle))


def _dedupe_aliases(values: list[str]) -> list[str]:
    seen: set[str] = set()
    aliases: list[str] = []
    for value in values:
        alias = str(value).strip()
        if not alias or alias in seen:
            continue
        seen.add(alias)
        aliases.append(alias)
    return aliases


def _load_run_id_aliases(label_map_path: Path | None) -> list[str]:
    aliases = list(DEFAULT_RUN_ID_ALIASES)
    if label_map_path is None:
        return aliases

    try:
        import yaml
    except ImportError as exc:
        raise SystemExit('pyyaml is required to read --label-map') from exc

    with label_map_path.open() as handle:
        raw_config = yaml.safe_load(handle) or {}

    if not isinstance(raw_config, dict):
        raise SystemExit('--label-map must contain a YAML mapping')

    user_aliases = raw_config.get('run_id')
    if user_aliases is None:
        return aliases
    if isinstance(user_aliases, str):
        return _dedupe_aliases([user_aliases] + aliases)
    if isinstance(user_aliases, list) and all(isinstance(item, str) for item in user_aliases):
        return _dedupe_aliases(user_aliases + aliases)
    raise SystemExit("--label-map field 'run_id' must be a string or list of strings")


def choose_run_id_column(schema: pa.Schema, aliases: list[str]) -> str | None:
    for alias in aliases:
        name = f'resource_tags_{alias}'
        if name in schema.names:
            return name
    return None


def _to_tags_dict(value: object) -> dict[str, object]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, list):
        tags: dict[str, object] = {}
        for item in value:
            if isinstance(item, (tuple, list)) and len(item) == 2:
                tags[str(item[0])] = item[1]
        return tags
    return {}


def build_run_ids(table: pa.Table, run_id_column: str | None, aliases: list[str]) -> list[str | None]:
    flat_alias_values = {
        alias: table[f'resource_tags_{alias}'].combine_chunks().to_pylist()
        for alias in aliases
        if f'resource_tags_{alias}' in table.schema.names
    }
    has_resource_tags = 'resource_tags' in table.schema.names
    if not flat_alias_values and not has_resource_tags:
        raise SystemExit('No supported run-id column or resource_tags map found in parquet schema')

    raw_tags_values = table['resource_tags'].to_pylist() if has_resource_tags else [None] * table.num_rows
    values: list[str | None] = []
    for idx, raw_tags in enumerate(raw_tags_values):
        tag_map = _to_tags_dict(raw_tags)
        run_id = None
        for alias in aliases:
            flat_values = flat_alias_values.get(alias)
            if flat_values is not None:
                flat_value = flat_values[idx]
                if flat_value not in (None, ''):
                    run_id = flat_value
                    break
            tag_value = tag_map.get(alias)
            if tag_value not in (None, ''):
                run_id = tag_value
                break
        values.append(run_id)
    return values


def main() -> None:
    parser = argparse.ArgumentParser(
        description='Build a tiny parquet sidecar containing only the target benchmark run costs from a monthly CUR export.'
    )
    parser.add_argument('cur_parquet', type=Path, help='Path to the monthly CUR parquet file')
    parser.add_argument('--run-ids-csv', type=Path, required=True, help='CSV containing benchmark run IDs')
    parser.add_argument('--output', type=Path, required=True, help='Output parquet path')
    parser.add_argument('--label-map', type=Path, help='Optional YAML mapping file matching benchmark_aws_cur_label_map')
    parser.add_argument(
        '--include-red-herring',
        action='store_true',
        help='Append a single synthetic non-benchmark row to exercise downstream filtering.',
    )
    args = parser.parse_args()

    run_rows = load_run_rows(args.run_ids_csv)
    run_lookup = {row['id']: {'group': row.get('group', 'default')} for row in run_rows}
    target_run_ids = set(run_lookup)
    run_id_aliases = _load_run_id_aliases(args.label_map)

    table = pq.read_table(args.cur_parquet)
    run_id_column = choose_run_id_column(table.schema, run_id_aliases)
    run_ids = build_run_ids(table, run_id_column, run_id_aliases)
    keep_columns = [name for name in KEEP_COLUMNS if name in table.schema.names]
    column_values = {name: table[name].combine_chunks().to_pylist() for name in keep_columns}

    rows: list[dict] = []
    for idx, run_id in enumerate(run_ids):
        if run_id not in target_run_ids:
            continue
        row = {
            'fixture_run_id': run_id,
            'fixture_group': run_lookup[run_id]['group'],
            'fixture_run_id_source': run_id_column or 'resource_tags.' + '|'.join(run_id_aliases),
        }
        for name in keep_columns:
            row[name] = column_values[name][idx]
        rows.append(row)

    if args.include_red_herring:
        rows.append(
            {
                'fixture_run_id': 'red-herring-run-id',
                'fixture_group': 'red-herring',
                'fixture_run_id_source': 'synthetic',
                'line_item_product_code': 'SyntheticCost',
                'line_item_line_item_type': 'Usage',
                'line_item_resource_id': 'synthetic:red-herring',
                'product_instance_type': None,
                'product_product_family': 'Synthetic',
                'resource_tags': [('user_unique_run_id', 'red-herring-run-id')],
                'line_item_unblended_cost': 0.123456789,
                'line_item_net_unblended_cost': 0.123456789,
                'split_line_item_split_cost': 0.123456789,
                'split_line_item_net_split_cost': 0.123456789,
                'split_line_item_unused_cost': 0.000000001,
                'split_line_item_net_unused_cost': 0.000000001,
                'line_item_usage_start_date': None,
                'line_item_usage_end_date': None,
            }
        )

    if not rows:
        raise SystemExit('No matching benchmark rows found in the supplied CUR parquet')

    args.output.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.Table.from_pylist(rows), args.output)
    print(args.output)
    print(f'rows={len(rows)}')
    print(f'run_ids={sorted({row["fixture_run_id"] for row in rows})}')


if __name__ == '__main__':
    main()
