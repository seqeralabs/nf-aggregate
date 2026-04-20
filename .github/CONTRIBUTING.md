# `seqeralabs/nf-aggregate`: Contributing Guidelines

Hi there!
Many thanks for taking an interest in improving seqeralabs/nf-aggregate.

We try to manage the required tasks for seqeralabs/nf-aggregate using GitHub issues, you probably came to this page when creating one.
Please use the pre-filled template to save time.

However, don't be put off by this template - other more general issues and suggestions are welcome!
Contributions to the code are even more welcome ;)

## Contribution workflow

If you'd like to write some code for seqeralabs/nf-aggregate, the standard workflow is as follows:

1. Check that there isn't already an issue about your idea in the [seqeralabs/nf-aggregate issues](https://github.com/seqeralabs/nf-aggregate/issues) to avoid duplicating work. If there isn't one already, please create one so that others know you're working on this
2. [Fork](https://help.github.com/en/github/getting-started-with-github/fork-a-repo) the [seqeralabs/nf-aggregate repository](https://github.com/seqeralabs/nf-aggregate) to your GitHub account
3. Make the necessary changes / additions within your forked repository following [Pipeline conventions](#pipeline-contribution-conventions)
4. Update `nextflow_schema.json` for any new or changed parameters.
5. Submit a Pull Request against `main` and wait for the code to be reviewed and merged

If you're not used to this workflow with git, you can start with some [docs from GitHub](https://help.github.com/en/github/collaborating-with-issues-and-pull-requests) or even their [excellent `git` resources](https://try.github.io/).

## Tests

When you create a pull request with changes, [GitHub Actions](https://github.com/features/actions) will run automatic tests.
Typically, pull-requests are only fully reviewed when these tests are passing, though of course we can help out before then.

## Patch

:warning: Only in the unlikely and regretful event of a release happening with a bug.

- On your own fork, make a new branch `patch` based on `upstream/main` or `upstream/master`.
- Fix the bug, and bump version (X.Y.Z+1).
- Open a pull-request from `patch` to `main`/`master` with the changes.

## Pipeline contribution conventions

To make the `seqeralabs/nf-aggregate` code and processing logic more understandable for new contributors and to ensure quality, we semi-standardise the way the code and other contributions are written.

### Adding a new step

If you wish to contribute a new step, please use the following coding standards:

1. Define the corresponding input channel into your new process from the expected previous process channel.
2. Write the process block (see below).
3. Define the output channel if needed (see below).
4. Add any new parameters to `nextflow.config` with a default (see below).
5. Add any new parameters to `nextflow_schema.json` with help text.
6. Add sanity checks and validation for all relevant parameters.
7. Perform local tests to validate that the new code works as expected.
8. If applicable, add a new test in the `tests` directory.
9. Update any user-facing docs touched by the change.

### Default values

Parameters should be initialised / defined with default values within the `params` scope in `nextflow.config`.

Once there, update `nextflow_schema.json` to match.

### Default processes resource requirements

Set sensible defaults for process CPUs, memory, and time close to the workflow or module that owns them.

The process resources can be passed on to the tool dynamically within the process with the `${task.cpus}` and `${task.memory}` variables in the `script:` block.

### Naming schemes

Please use the following naming schemes, to make it easy to understand what is going where.

- initial process channel: `ch_output_from_<process>`
- intermediate and terminal channels: `ch_<previousprocess>_for_<nextprocess>`

## GitHub Codespaces

This repo includes a devcontainer configuration which will create a GitHub Codespaces for Nextflow development! This is an online developer environment that runs in your browser, complete with VSCode and a terminal.

To get started:

- Open the repo in [Codespaces](https://github.com/seqeralabs/nf-aggregate/codespaces)
- Tools installed
  - Nextflow

Devcontainer specs:

- [DevContainer config](.devcontainer/devcontainer.json)
