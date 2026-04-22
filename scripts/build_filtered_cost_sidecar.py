#!/usr/bin/env python3

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

RUN_ID_COLUMNS = [
    'resource_tags_user_unique_run_id',
    'resource_tags_user_nf_unique_run_id',
]
RUN_ID_TAG_KEYS = [
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


def choose_run_id_column(schema: pa.Schema) -> str | None:
    for name in RUN_ID_COLUMNS:
        if name in schema.names:
            return name
    return None


def build_run_ids(table: pa.Table, run_id_column: str | None) -> list[str | None]:
    if run_id_column is not None:
        return table[run_id_column].combine_chunks().to_pylist()
    if 'resource_tags' not in table.schema.names:
        raise SystemExit('No supported run-id column or resource_tags map found in parquet schema')

    values: list[str | None] = []
    for raw_tags in table['resource_tags'].to_pylist():
        tag_map = dict(raw_tags or [])
        run_id = None
        for key in RUN_ID_TAG_KEYS:
            if key in tag_map:
                run_id = tag_map[key]
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
    parser.add_argument(
        '--include-red-herring',
        action='store_true',
        help='Append a single synthetic non-benchmark row to exercise downstream filtering.',
    )
    args = parser.parse_args()

    run_rows = load_run_rows(args.run_ids_csv)
    run_lookup = {row['id']: {'group': row.get('group', 'default')} for row in run_rows}
    target_run_ids = set(run_lookup)

    table = pq.read_table(args.cur_parquet)
    run_id_column = choose_run_id_column(table.schema)
    run_ids = build_run_ids(table, run_id_column)
    keep_columns = [name for name in KEEP_COLUMNS if name in table.schema.names]
    column_values = {name: table[name].combine_chunks().to_pylist() for name in keep_columns}

    rows: list[dict] = []
    for idx, run_id in enumerate(run_ids):
        if run_id not in target_run_ids:
            continue
        row = {
            'fixture_run_id': run_id,
            'fixture_group': run_lookup[run_id]['group'],
            'fixture_run_id_source': run_id_column or 'resource_tags.' + '|'.join(RUN_ID_TAG_KEYS),
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
