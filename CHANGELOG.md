# seqeralabs/nf-aggregate: Changelog

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/)
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [[0.1.0](https://github.com/seqeralabs/nf-aggregate/releases/tag/0.1.0)] - 2023-12-13

Initial release of seqeralabs/nf-aggregate, created as a subset of the [nf-core](https://nf-co.re/) template.

### Credits

Special thanks to the following for their contributions to the release:

- [Adam Talbot](https://github.com/adamrtalbot)
- [Jonathan Manning](https://github.com/pinin4fjords)
- [Rob Syme](https://github.com/robsyme)

### Pipeline summary

The pipeline performs the following steps:

1. Downloads run information via the Seqera CLI in parallel
2. Runs MultiQC to aggregate all of the run metrics into a single report