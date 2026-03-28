# AGENTS.md

## Cursor Cloud specific instructions

### Project overview

This is a **Nextflow DSL2 bioinformatics pipeline** (not a web app). It aggregates metrics across pipeline runs on the Seqera Platform. There are no databases, no package managers (npm/pip), and no traditional build steps.

### Required tools

| Tool       | Version                            | Purpose                                                                  |
| ---------- | ---------------------------------- | ------------------------------------------------------------------------ |
| Nextflow   | >= 24.04.2 (use `NXF_VER=24.10.4`) | Workflow engine                                                          |
| Java JDK   | 11+                                | Nextflow runtime                                                         |
| Docker     | latest                             | Container runtime for pipeline processes                                 |
| nf-test    | >= 0.9.2                           | Test framework                                                           |
| nf-core    | 3.3.1                              | Pipeline linting                                                         |
| pre-commit | latest                             | Code formatting hooks (prettier, trailing-whitespace, end-of-file-fixer) |

### Running the pipeline

The pipeline requires `TOWER_ACCESS_TOKEN` (Seqera Platform API token) exported as an environment variable. Without it, the pipeline will fail at the `SEQERA_RUNS_DUMP` process. Add it as a secret named `TOWER_ACCESS_TOKEN`.

```bash
export TOWER_ACCESS_TOKEN=<your-token>
nextflow run . -profile test,docker --outdir ./results
```

### Linting

```bash
pre-commit run --all-files
nf-core pipelines lint --dir .
```

### Testing

See `.github/CONTRIBUTING.md` for the canonical test command:

```bash
nf-test test --profile debug,test,docker --verbose
```

All pipeline and module tests require `TOWER_ACCESS_TOKEN` because they call the Seqera Platform API. The only tests that can run without a token are the utility subworkflow tests:

```bash
nf-test test --tag subworkflows --verbose
```

### Docker-in-Docker setup (Cloud VM)

The Cloud VM requires special Docker configuration:

- `fuse-overlayfs` storage driver (kernel doesn't support all overlay2 features)
- `iptables-legacy` (kernel doesn't support all nftables features)
- Docker daemon must be started manually: `sudo dockerd &>/tmp/dockerd.log &`

### Key files

- `main.nf` — pipeline entry point
- `nextflow.config` — main config (params, profiles, plugins)
- `nf-test.config` — test framework config
- `.pre-commit-config.yaml` — linting hooks
- `.nf-core.yml` — lint ignore rules
- `workflows/nf_aggregate/main.nf` — primary workflow logic
