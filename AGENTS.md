# nf-aggregate

Nextflow pipeline to aggregate metrics across Seqera Platform pipeline runs.

## Architecture

```
input CSV (id, workspace, group, logs, fusion)
  → branch: api (SeqeraApi.fetchRunData) | external (EXTRACT_TARBALL)
  → collect JSON files
  → BENCHMARK_REPORT process (benchmark_report.py build-db + report)
  → benchmark.duckdb + benchmark_report.html
```

## Key Params

| Param                       | Default                       | Purpose                           |
| --------------------------- | ----------------------------- | --------------------------------- |
| `generate_benchmark_report` | false                         | Enable benchmark report           |
| `benchmark_aws_cur_report`  | null                          | AWS CUR parquet for cost analysis |
| `seqera_api_endpoint`       | `https://api.cloud.seqera.io` | Platform API URL                  |

## Plugins

- `nf-schema@2.3.0` — param validation, samplesheet parsing
- `nf-boost@0.6.0` — `request()`, `fromJson`/`toJson` for API calls

## Env Requirements

- `TOWER_ACCESS_TOKEN` — Seqera Platform API token (forwarded via `env {}` block in nextflow.config)

## Rebuild Command (local testing)

```bash
# Build DuckDB from JSON data:
uv run --with duckdb --with typer --with pyyaml --with pyarrow \
  python bin/benchmark_report.py build-db \
  --data-dir /path/to/json_data --output /tmp/benchmark.duckdb

# Render HTML report from DuckDB:
uv run --with duckdb --with jinja2 --with typer --with pyyaml \
  python bin/benchmark_report.py report \
  --db /tmp/benchmark.duckdb --brand assets/brand.yml --output /tmp/report.html

# Fetch run data from Seqera Platform API (standalone):
uv run --with duckdb --with typer --with pyyaml --with httpx \
  python bin/benchmark_report.py fetch \
  --run-ids <id> --workspace org/name --output-dir /tmp/json_data
```

## Gotchas

- Wave freeze strategy: `['conda', 'container', 'dockerfile']` — no `spack` (breaks builds)
- DuckDB `read_json_auto` needs file paths, not JSON strings — use temp files
- `commit.gpgsign` must be true (SSH signing via 1Password)
- RTK `buildOutputFiltering` / `testOutputAggregation` can swallow nf-test output — disable to debug

## Cursor Cloud specific instructions

### Services overview

| Service | Purpose | Run command |
|---------|---------|-------------|
| Nextflow pipeline | Core product — aggregates metrics from Seqera Platform runs | `nextflow run . --input <csv> --outdir results -profile docker` |
| Python benchmark_report.py | Builds DuckDB + renders HTML report | See "Rebuild Command" section above |

### Running tests

- **pytest (Python unit tests):** `uv run --with duckdb --with typer --with pyyaml --with jinja2 --with pyarrow --with pytest --with httpx pytest bin/test_benchmark_report.py -v`
- **nf-test (pipeline integration tests):** `nf-test test --profile=+docker --verbose`
- **Lint:** `pre-commit run --all-files`

### Docker in Cloud VM (cgroupv2 workaround)

The Cloud VM runs inside a Firecracker VM where the root cgroupv2 hierarchy cannot delegate `memory`/`io` controllers. Docker containers that request resource limits (`--memory`, `--cpu-shares` — used by Nextflow's `process { memory; cpus }`) will fail with `"cannot enter cgroupv2 ... with domain controllers"`.

**Workaround:** A `runc` wrapper at `/usr/bin/runc` strips `linux.resources` from the OCI spec before passing to the real runtime at `/usr/bin/runc.real`. This is already set up in the VM snapshot. If Docker container launches fail with cgroup errors after a fresh setup, re-apply:

```bash
# Ensure /usr/bin/runc.real exists (backup of original runc)
sudo cp /usr/bin/runc /usr/bin/runc.real 2>/dev/null || true
# Install wrapper
cat > /tmp/runc-wrapper.sh << 'WRAPPER'
#!/bin/bash
for arg in "$@"; do
    if [ "$arg" = "create" ]; then
        bundle_dir=""
        next_is_bundle=false
        for a in "$@"; do
            if $next_is_bundle; then bundle_dir="$a"; break; fi
            if [ "$a" = "--bundle" ] || [ "$a" = "-b" ]; then next_is_bundle=true; fi
        done
        if [ -n "$bundle_dir" ] && [ -f "$bundle_dir/config.json" ]; then
            python3 -c "
import json
with open('$bundle_dir/config.json') as f: config = json.load(f)
if 'linux' in config and 'resources' in config['linux']: del config['linux']['resources']
with open('$bundle_dir/config.json', 'w') as f: json.dump(config, f)
" 2>/dev/null
        fi
        break
    fi
done
exec /usr/bin/runc.real "$@"
WRAPPER
chmod +x /tmp/runc-wrapper.sh
sudo cp /tmp/runc-wrapper.sh /usr/bin/runc
```

### Running the pipeline without TOWER_ACCESS_TOKEN

The default test profile CSV references API runs requiring `TOWER_ACCESS_TOKEN`. For offline testing, use the external tarball fixtures:

```bash
nextflow run . --input workflows/nf_aggregate/assets/test_benchmark.csv \
  --generate_benchmark_report --outdir results -profile docker
```

### Docker daemon startup

Docker must be started manually in the Cloud VM:

```bash
sudo dockerd &>/tmp/dockerd.log &
sleep 3
sudo chmod 666 /var/run/docker.sock
```
