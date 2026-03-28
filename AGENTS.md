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
NXF_DOCKER_LEGACY=true nextflow run . -profile test,docker --outdir ./results -c /tmp/nf-no-limits.config
```

### Linting

```bash
pre-commit run --all-files
nf-core pipelines lint --dir .
```

### Testing

See `.github/CONTRIBUTING.md` for the canonical test command. In the Cloud VM, you must use the custom nf-test config to disable Docker resource limits:

```bash
NXF_DOCKER_LEGACY=true nf-test test tests/default.nf.test --profile debug,test,docker --verbose --config /tmp/nf-test-cloud.config
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
- After starting Docker: `sudo chmod 666 /var/run/docker.sock`

### Cgroup v2 workaround (critical for Cloud VM)

The Cloud VM's cgroup v2 is in "threaded" mode, which prevents Docker from applying resource limits (`--memory`, `--cpu-shares`). Nextflow by default passes these flags to `docker run`, causing all containerized processes to fail with `cannot enter cgroupv2 ... with domain controllers -- it is in threaded mode`.

**Workaround:** You must disable Docker resource limits in two ways:

1. Set `NXF_DOCKER_LEGACY=true` (avoids `--cpu-shares`)
2. Pass a Nextflow config that nullifies process resource settings:

```bash
cat > /tmp/nf-no-limits.config << 'EOF'
process {
    memory = null
    cpus = null
    time = null
}
EOF
```

For nf-test, create `/tmp/nf-test-cloud.config` that references a combined Nextflow test config (including resource nullification) and use `--config /tmp/nf-test-cloud.config`.

The snapshot test for the default profile (`-profile test`) has a **pre-existing mismatch** caused by upstream data drift (Seqera Platform runs now include additional files like fusion logs and task directories not in the original snapshot). The benchmark test passes.

### Key files

- `main.nf` — pipeline entry point
- `nextflow.config` — main config (params, profiles, plugins)
- `nf-test.config` — test framework config
- `.pre-commit-config.yaml` — linting hooks
- `.nf-core.yml` — lint ignore rules
- `workflows/nf_aggregate/main.nf` — primary workflow logic
