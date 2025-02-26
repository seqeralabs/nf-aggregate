# seqeralabs/nf-aggregate

[![GitHub Actions CI Status](https://github.com/seqeralabs/nf-aggregate/actions/workflows/ci.yml/badge.svg)](https://github.com/seqeralabs/nf-aggregate/actions/workflows/ci.yml)
[![GitHub Actions Linting Status](https://github.com/seqeralabs/nf-aggregate/actions/workflows/linting.yml/badge.svg)](https://github.com/seqeralabs/nf-aggregate/actions/workflows/linting.yml)
[![nf-test](https://img.shields.io/badge/unit_tests-nf--test-337ab7.svg)](https://www.nf-test.com)

[![Nextflow](https://img.shields.io/badge/version-%E2%89%A524.04.2-green?style=flat&logo=nextflow&logoColor=white&color=%230DC09D&link=https%3A%2F%2Fnextflow.io)](https://www.nextflow.io/)
[![nf-core template version](https://img.shields.io/badge/nf--core_template-3.3.0.dev0-green?style=flat&logo=nfcore&logoColor=white&color=%2324B064&link=https%3A%2F%2Fnf-co.re)](https://github.com/nf-core/tools/releases/tag/3.3.0.dev0)
[![run with conda](http://img.shields.io/badge/run%20with-conda-3EB049?labelColor=000000&logo=anaconda)](https://docs.conda.io/en/latest/)
[![run with docker](https://img.shields.io/badge/run%20with-docker-0db7ed?labelColor=000000&logo=docker)](https://www.docker.com/)
[![run with singularity](https://img.shields.io/badge/run%20with-singularity-1d355c.svg?labelColor=000000)](https://sylabs.io/docs/)
[![Launch on Seqera Platform](https://img.shields.io/badge/Launch%20%F0%9F%9A%80-Seqera%20Platform-%234256e7)](https://cloud.seqera.io/launch?pipeline=https://github.com/seqeralabs/nf-aggregate)

## Introduction

**seqeralabs/nf-aggregate** is a Nextflow pipeline to aggregate pertinent metrics across pipeline runs on the Seqera Platform.

<p align="center">
  <img src="assets/multiqc_screenshot.png" alt="MultiQC screenshot" width="75%"/>
</p>

The pipeline performs the following steps:

1. Downloads run information via the Seqera CLI in parallel
2. Runs MultiQC to aggregate all of the run metrics into a single report

You can download an example MultiQC report [here](assets/multiqc_report.html).

## Prerequisites

- [Nextflow](https://www.nextflow.io/docs/latest/getstarted.html#installation) >=23.10.0
- Account in [Seqera Platform](https://seqera.io/platform/)
- [Access token](https://docs.seqera.io/platform/23.3.0/api/overview#authentication) which is your personal authorization token for the Seqera Platform CLI. This can be created in the user menu under **Your tokens**. Export the token as a shell variable directly into your terminal if running the pipelie locally. You will not need to set this if running the pipeline within the Seqera Platform as it will automatically be inherited from the executing environment.

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

If you are using a Seqera Platform Enterprise instance that is secured with a private CA SSL certificate not recognized by default Java certificate authorities, you can specify a custom `cacerts` store path through the `--java_truststore_path` parameter and optionally, a password with the `--java_truststore_password`. This certificate will be used to achieve connectivity with your Seqera Platform instance through API and CLI.

### Benchmark reports

If you want to generate a benchmark report comparing multiple runs, you can include a `group` column in your `run_ids.csv` file. This allows you to organize and analyze runs based on custom groupings in the final report.

```
id,workspace,group
3VcLMAI8wyy0Ld,community/showcase,group1
4VLRs7nuqbAhDy,community/showcase,group2
```

To incorporate AWS cost data into the benchmark report, use the benchmark_aws_cur_report parameter. This should point to a valid AWS Cost and Usage Report (CUR) file in Parquet format, supporting both CUR 1.0 and CUR 2.0 schemas. The file can be stored locally or in a cloud bucket. To run nf-aggregate and generate benchmark reports, you can use the following command:

```
nextflow run seqeralabs/nf-aggregate \
    --input run_ids.csv \
    --outdir ./results \
    --run_benchmark \
    --benchmark_aws_cur_report ./aws_cost_report.parquet
```

## Output

The results from the pipeline will be published in the path specified by the `--outdir` and will consist of the following contents:

```
./results
├── multiqc/
│   ├── multiqc_data/
│   ├── multiqc_plots/
│   └── multiqc_report.html                 ## MultiQC report
├── nf-core_rnaseq/
│   ├── gantt/
│   │   └── 4Bi5xBK6E2Nbhj_gantt.html       ## Gantt plot for run
│   └── runs_dump/
│       └── 4Bi5xBK6E2Nbhj/                 ## Output of 'tw runs dump'
│           ├── service-info.json
│           ├── workflow-launch.json
│           ├── workflow-load.json
│           ├── workflow-metrics.json
│           ├── workflow-tasks.json
│           └── workflow.json
└── pipeline_info/
```

> [!NOTE]
> Gantt plots depend on information derived from the Fusion logs. For that reason, Gantt plots will be ommitted from the pipeline outputs for non-Fusion runs, irrespective of whether the `--skip_run_gantt` parameter has been set.

## Contributions and Support

If you would like to contribute to this pipeline, please see the [contributing guidelines](.github/CONTRIBUTING.md).

## Credits

nf-aggregate was written by the Scientific Development and MultiQC teams at [Seqera Labs](https://seqera.io/).

## Citations

This pipeline uses code and infrastructure developed and maintained by the [nf-core](https://nf-co.re) community, reused here under the [MIT license](https://github.com/nf-core/tools/blob/master/LICENSE).

You can cite the `nf-core` publication as follows:

> **The nf-core framework for community-curated bioinformatics pipelines.**
>
> Philip Ewels, Alexander Peltzer, Sven Fillinger, Harshil Patel, Johannes Alneberg, Andreas Wilm, Maxime Ulysse Garcia, Paolo Di Tommaso & Sven Nahnsen.
>
> _Nat Biotechnol._ 2020 Feb 13. doi: [10.1038/s41587-020-0439-x](https://dx.doi.org/10.1038/s41587-020-0439-x).
