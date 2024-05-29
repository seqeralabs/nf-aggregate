# seqeralabs/nf-aggregate: Changelog

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/)
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [[0.2.0](https://github.com/seqeralabs/nf-aggregate/releases/tag/0.2.0)] - 2024-05-29

### Credits

Special thanks to the following for their contributions to the release:

- [Adam Talbot](https://github.com/adamrtalbot)
- [Arthur Vigil](https://github.com/ahvigil)
- [Esha Joshi](https://github.com/ejseqera)
- [Jonathan Manning](https://github.com/pinin4fjords)
- [Maxime Garcia](https://github.com/maxulysse)
- [Rob Syme](https://github.com/robsyme)

Thank you to everyone else that has contributed by reporting bugs, enhancements or in any other way, shape or form.

### Enhancements & fixes

[PR #19](https://github.com/seqeralabs/nf-aggregate/pull/19) - Allow underscores in workspace name regex
[PR #22](https://github.com/seqeralabs/nf-aggregate/pull/22) - Copy in nf-test CI from nf-core/fetchngs
[PR #23](https://github.com/seqeralabs/nf-aggregate/pull/23) - Bump Platform CLI version to `0.9.2`
[PR #27](https://github.com/seqeralabs/nf-aggregate/pull/27) - Remove escape from `TOWER_ACCESS_TOKEN` env var
[PR #28](https://github.com/seqeralabs/nf-aggregate/pull/28) - Remove special chars from Seqera CLI version
[PR #29](https://github.com/seqeralabs/nf-aggregate/pull/29) - Bump image for `PLOT_GANTT` process for Singularity
[PR #30](https://github.com/seqeralabs/nf-aggregate/pull/30) - Skip Gantt plots with non-fusion runs
[PR #31](https://github.com/seqeralabs/nf-aggregate/pull/31) - Update Platform API URI
[PR #32](https://github.com/seqeralabs/nf-aggregate/pull/32) - Update all nf-core modules and subworkflows
[PR #33](https://github.com/seqeralabs/nf-aggregate/pull/33) - Remove `docker.userEmulation`

### Software dependencies

| Dependency  | Old version | New version |
| ----------- | ----------- | ----------- |
| `multiqc`   | 1.18        | 1.21        |
| `tower-cli` | 0.9.0       | 0.9.2       |

> **NB:** Dependency has been **updated** if both old and new version information is present.
>
> **NB:** Dependency has been **added** if just the new version information is present.
>
> **NB:** Dependency has been **removed** if new version information isn't present.

## [[0.1.0](https://github.com/seqeralabs/nf-aggregate/releases/tag/0.1.0)] - 2023-12-13

Initial release of seqeralabs/nf-aggregate, created as a subset of the [nf-core](https://nf-co.re/) template.
Initial release of seqeralabs/nf-aggregate, created with the [nf-core](https://nf-co.re/) template.

### Credits

Special thanks to the following for their contributions to the release:

- [Adam Talbot](https://github.com/adamrtalbot)
- [Jonathan Manning](https://github.com/pinin4fjords)
- [Rob Syme](https://github.com/robsyme)

### Pipeline summary

The pipeline performs the following steps:

1. Downloads run information via the Seqera CLI in parallel
2. Runs MultiQC to aggregate all of the run metrics into a single report
