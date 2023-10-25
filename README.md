# nf-aggregate

Nextflow pipeline to aggregate pertinent metrics across pipeline runs on the Seqera Platform.

The pipeline performs the following steps:

1. Downloads run information via the Seqera CLI in parallel
2. Runs MultiQC to aggregate the pertinent run metrics into a single report

The primary input to the pipeline is a file containing a list of run identifiers from the Seqera Platform. These can be obtained from details in the runs page for any pipeline execution. For example, we can create a file called `run_ids.csv` with the following contents:

```
4Bi5xBK6E2Nbhj
4LWT4uaXDaGcDY
38QXz4OfQDpwOV
2lXd1j7OwZVfxh
```

This pipeline can then be executed with the following command:

```
nextflow run seqeralabs/nf-aggregate \
    --input ids.csv \
    --workspace 'community/showcase' \
    --outdir ./results \
    -profile docker \
```
