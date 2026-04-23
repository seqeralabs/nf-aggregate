# seqeralabs/nf-aggregate

[![GitHub Actions CI Status](https://github.com/seqeralabs/nf-aggregate/actions/workflows/ci.yml/badge.svg)](https://github.com/seqeralabs/nf-aggregate/actions/workflows/ci.yml)
[![nf-test](https://img.shields.io/badge/unit_tests-nf--test-337ab7.svg)](https://www.nf-test.com)

[![Nextflow](https://img.shields.io/badge/version-%E2%89%A525.10.0-green?style=flat&logo=nextflow&logoColor=white&color=%230DC09D&link=https%3A%2F%2Fnextflow.io)](https://www.nextflow.io/)
[![run with conda](http://img.shields.io/badge/run%20with-conda-3EB049?labelColor=000000&logo=anaconda)](https://docs.conda.io/en/latest/)
[![run with docker](https://img.shields.io/badge/run%20with-docker-0db7ed?labelColor=000000&logo=docker)](https://www.docker.com/)
[![run with singularity](https://img.shields.io/badge/run%20with-singularity-1d355c.svg?labelColor=000000)](https://sylabs.io/docs/)
[![Launch on Seqera Platform](https://img.shields.io/badge/Launch%20%F0%9F%9A%80-Seqera%20Platform-%234256e7)](https://cloud.seqera.io/launch?pipeline=https://github.com/seqeralabs/nf-aggregate)

## Introduction

**seqeralabs/nf-aggregate** is a Nextflow pipeline to aggregate pertinent metrics across pipeline runs on the Seqera Platform.

The pipeline fetches run data from the Seqera Platform API and generates benchmark reports comparing pipeline runs.

## Prerequisites

- [Nextflow](https://www.nextflow.io/docs/latest/getstarted.html#installation) >=25.10.0
- Account in [Seqera Platform](https://seqera.io/platform/)
- [Access token](https://docs.seqera.io/platform/23.3.0/api/overview#authentication) which is your personal authorization token for the Seqera Platform CLI. This can be created in the user menu under **Your tokens**. Export the token as a shell variable directly into your terminal if running the pipeline locally. You will not need to set this if running the pipeline within the Seqera Platform as it will automatically be inherited from the executing environment.

  ```bash
  export TOWER_ACCESS_TOKEN=<your access token>
  ```

## Usage

The primary input to the pipeline is a file containing a list of run identifiers from the Seqera Platform. These can be obtained from details in the runs page for any pipeline execution. For example, we can create a file called `run_ids.csv` with the following contents:

```
id,workspace
4Bi5xBK6E2Nbhj,community/showcase
4LWT4uaXDaGcDY,community/showcase
38QXz4OfQDpwOV,community/showcase
2lXd1j7OwZVfxh,community/showcase
```

This pipeline can then be executed with the following command:

```
nextflow run seqeralabs/nf-aggregate \
    --input run_ids.csv \
    --outdir ./results \
    -profile docker
```

If you are using a Seqera Platform Enterprise instance that is secured with a private CA SSL certificate not recognized by default Java certificate authorities, you can specify a custom `cacerts` store path through the `--java_truststore_path` parameter and optionally, a password with the `--java_truststore_password`. This configures the Nextflow JVM used for Seqera Platform API access (see `lib/SeqeraApi.groovy`).

### Seqera Platform Enterprise with a private CA (containers)

For API access from Nextflow, `--java_truststore_path` / `--java_truststore_password` are usually sufficient. Task containers may still lack your private CA when they open TLS connections. As a workaround, add the following under **Advanced options → Nextflow config** in Seqera Platform (replace `tower-server-url` with your Seqera host name only, without `https://`):

```groovy
process {
   withName: /NORMALIZE_BENCHMARK_JSONL|AGGREGATE_BENCHMARK_REPORT_DATA|RENDER_BENCHMARK_REPORT|EXTRACT_TARBALL/ {
     beforeScript = '''
keytool -printcert -rfc -sslserver tower-server-url:443 > PRIVATE_CERT.pem
keytool -importcert -alias seqera-ca -file PRIVATE_CERT.pem -keystore truststore.jks -storepass changeit -noprompt
export JAVA_TOOL_OPTIONS="-Djavax.net.ssl.trustStore=$(pwd)/truststore.jks -Djavax.net.ssl.trustStorePassword=changeit"
'''
   }
}
```

This downloads the server certificate, builds a small JKS truststore in the task work directory, and points the JVM inside the task at it.

### Benchmark reports

If you want to generate a benchmark report comparing multiple runs, you can include a `group` column in your `run_ids.csv` file. This allows you to organize and analyze runs based on custom groupings in the final report.

```
id,workspace,group
3VcLMAI8wyy0Ld,community/showcase,group1
4VLRs7nuqbAhDy,community/showcase,group2
```

## Use logs from an external Seqera Platform deployment

Sometimes we want to compile benchmark reports from runs from two different Seqera platform deployments, for example a dev and a production environment to compare performance. External logs in nf-aggregate can be used by specifying the workspace as `external` and providing a `logs` column that points to the log folder or tarball.

```
id,workspace,group,logs
3VcLMAI8wyy0Ld,community/showcase,group1,
1JI5B1avuj3o58,external,group2,/path/to/my/run_dumps_tarball.tar.gz
1vsww7GjKBsVNa,external,group2,/path/to/my/run_dumps_folder
```

## Incorporate AWS split cost allocation data

To incorporate AWS cost data into the benchmark report, use the `benchmark_aws_cur_report` parameter. This should point to a valid AWS Cost and Usage Report (CUR) file in Parquet format, currently only supporting CUR 1.0. The file can be stored locally or in a cloud bucket.
To run nf-aggregate and generate benchmark reports, you can use the following command:

```
nextflow run seqeralabs/nf-aggregate \
    --input run_ids.csv \
    --outdir ./results \
    --generate_benchmark_report \
    --benchmark_aws_cur_report ./aws_cost_report.parquet
```

If your CUR export uses custom resource label names, pass an optional YAML alias map with `benchmark_aws_cur_label_map`:

```
nextflow run seqeralabs/nf-aggregate \
    --input run_ids.csv \
    --outdir ./results \
    --generate_benchmark_report \
    --benchmark_aws_cur_report ./aws_cost_report.parquet \
    --benchmark_aws_cur_label_map ./cur_label_map.yml
```

The benchmark report can be generated without cost data - simply omit the `--benchmark_aws_cur_report` parameter if cost analysis is not needed.

When CUR data is provided, nf-aggregate only joins cost rows that carry the resource labels needed to match a Nextflow task back to a benchmark run. By default the logical fields map to:

- run ID: `user_unique_run_id` or `user_nf_unique_run_id`
- process name: `user_pipeline_process`
- task hash: `user_task_hash`

To accept manual/custom label names, create a YAML file listing aliases for the logical fields:

```
run_id:
  - my_team_run_id
  - user_unique_run_id
process:
  - my_process_label
  - user_pipeline_process
task_hash:
  - my_task_hash_label
  - user_task_hash
```

Aliases are tried in order, then the built-in defaults are still checked as a fallback.

The normalizer accepts both of the common CUR layouts:

- flattened CUR columns such as `resource_tags_user_unique_run_id`, `resource_tags_my_process_label`, and `resource_tags_user_task_hash`
- map-style `resource_tags` entries containing `user_unique_run_id`, `my_process_label`, and `user_task_hash`

If those labels are missing from the CUR export, the benchmark report still renders, but CUR-backed cost rows cannot be associated with runs or tasks.

For AWS Batch or other cloud executors that propagate resource labels into CUR tags, configure labels equivalent to:

```
user_unique_run_id=${workflow.runId}
user_pipeline_process=${task.process}
user_task_hash=${task.hash}
```

If you want workflow-level failed runs to appear in downstream benchmark sections (run metrics, charts, task tables), pass `--include_failed_runs`. By default, failed workflows are listed in the run summary but excluded from downstream metrics. Cancelled workflows remain excluded.

For a checked-in real-world example that exercises external run JSON directories plus a tiny filtered cost parquet, see:

- `workflows/nf_aggregate/assets/test_benchmark_realworld_costs.csv`
- `workflows/nf_aggregate/assets/realworld_log_dirs/`
- `workflows/nf_aggregate/assets/test_benchmark_realworld_costs.parquet`
- `tests/pipeline_benchmark_realworld_costs/main.nf.test`

If you want to regenerate the tiny parquet locally from a monthly CUR export while stripping out every non-benchmark real cost row, run:

```
python scripts/build_filtered_cost_sidecar.py \
    /path/to/scidev-detailed-usage-YYYY-MM.snappy.parquet \
    --run-ids-csv workflows/nf_aggregate/assets/test_benchmark_realworld_costs.csv \
    --output workflows/nf_aggregate/assets/test_benchmark_realworld_costs.parquet
```

The helper script also accepts `--cost-label-map ./cur_label_map.yml` when the monthly CUR export uses custom run-id label aliases.

Add `--include-red-herring` only if you want one synthetic non-benchmark row for robustness testing.

## Output

The results from the pipeline will be published in the path specified by the `--outdir` and will consist of the following contents:

```
./results
├── benchmark_report/
│   ├── benchmark_report.html                ## Benchmark report
│   ├── report_data.json                     ## Aggregated report data boundary
│   └── jsonl_bundle/                        ## Streaming stage handoff (runs/tasks/metrics[/costs].jsonl)
└── pipeline_info/
```

## Contributions and Support

If you would like to contribute to this pipeline, please see the [contributing guidelines](.github/CONTRIBUTING.md).

## Credits

nf-aggregate was written by the Scientific Development team at [Seqera Labs](https://seqera.io/).

## Citations

See [CITATIONS.md](CITATIONS.md), including the pinned plugin references for `nf-core-utils@0.4.0` and `nf-schema@2.3.0` used by this pipeline.
