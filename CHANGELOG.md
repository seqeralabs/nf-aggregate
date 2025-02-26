# seqeralabs/nf-aggregate: Changelog

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/)
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## dev

### Credits

Special thanks to the following for their contributions to the release:

- [Adam Talbot](https://github.com/adamrtalbot)
- [Edmund Miller](https://github.com/edmundmiller)
- [Florian Wuennemann](https://github.com/FloWuenne)
- [Maxime Garcia](https://github.com/maxulysse)

Thank you to everyone else that has contributed by reporting bugs, enhancements or in any other way, shape or form.

### Enhancements & fixes

- [PR #73](https://github.com/seqeralabs/nf-aggregate/pull/73) - Add process for generating Benchmark reports
- [PR #74](https://github.com/seqeralabs/nf-aggregate/pull/74) - Add process for generating Benchmark reports
- [PR #75](https://github.com/seqeralabs/nf-aggregate/pull/75) - Skip failed jobs in benchmarking report
- [PR #76](https://github.com/seqeralabs/nf-aggregate/pull/76) - Sync with nf-core tools 3.2.0

## [[0.5.0](https://github.com/seqeralabs/nf-aggregate/releases/tag/0.5.0)] - 2024-11-12

### Credits

Special thanks to the following for their contributions to the release:

- [Adam Talbot](https://github.com/adamrtalbot)
- [Esha Joshi](https://github.com/ejseqera)
- [Jonathan Manning](https://github.com/pinin4fjords)
- [Maxime Garcia](https://github.com/maxulysse)
- [Rob Syme](https://github.com/robsyme)

Thank you to everyone else that has contributed by reporting bugs, enhancements or in any other way, shape or form.

### Enhancements & fixes

- [PR #61](https://github.com/seqeralabs/nf-aggregate/pull/61) - Remove dependency on external library/grape
- [PR #63](https://github.com/seqeralabs/nf-aggregate/pull/63) - Add `maxForks` setting for Seqera CLI to overcome API issues
- [PR #65](https://github.com/seqeralabs/nf-aggregate/pull/65) - Replace eclint GHA by pre-commit
- [PR #67](https://github.com/seqeralabs/nf-aggregate/pull/67) - Update tests to use a non-fusion run from Seqera Cloud community/showcase
- [PR #69](https://github.com/seqeralabs/nf-aggregate/pull/69) - Fix parsing of extra args to tw CLI

## [[0.4.0](https://github.com/seqeralabs/nf-aggregate/releases/tag/0.4.0)] - 2024-07-26

### Credits

Special thanks to the following for their contributions to the release:

- [Friederike Hanssen](https://github.com/FriederikeHanssen)

Thank you to everyone else that has contributed by reporting bugs, enhancements or in any other way, shape or form.

### Enhancements & fixes

- [PR #52](https://github.com/seqeralabs/nf-aggregate/pull/52) - Organise results folder structure by pipeline
- [PR #53](https://github.com/seqeralabs/nf-aggregate/pull/53) - Throw exception and terminate workflow in case config can't be read
- [PR #57](https://github.com/seqeralabs/nf-aggregate/pull/57) - Check if fusion is enabled via the Platform API

## [[0.3.0](https://github.com/seqeralabs/nf-aggregate/releases/tag/0.3.0)] - 2024-07-01

### Credits

Special thanks to the following for their contributions to the release:

- [Adam Talbot](https://github.com/adamrtalbot)
- [Esha Joshi](https://github.com/ejseqera)
- [Rob Syme](https://github.com/robsyme)

Thank you to everyone else that has contributed by reporting bugs, enhancements or in any other way, shape or form.

### Enhancements & fixes

[PR #49](https://github.com/seqeralabs/nf-aggregate/pull/49) - Add custom java truststore support and improved exception handling

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
[PR #40](https://github.com/seqeralabs/nf-aggregate/pull/40) - Sync with nf-core tools 2.14.1

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
