#!/usr/bin/env python


"""Provide functions to merge multiple versions.yml files."""


import yaml
import platform
from textwrap import dedent


def main():
    """Load all version files and generate merged output."""
    versions_this_module = {}
    versions_this_module["${task.process}"] = {
        "python": platform.python_version(),
        "yaml": yaml.__version__,
    }

    with open("$versions") as f:
        versions_by_process = (
            yaml.load(f, Loader=yaml.BaseLoader) | versions_this_module
        )

    # aggregate versions by the module name (derived from fully-qualified process name)
    versions_by_module = {}
    for process, process_versions in versions_by_process.items():
        module = process.split(":")[-1]
        try:
            if versions_by_module[module] != process_versions:
                raise AssertionError(
                    "We assume that software versions are the same between all modules. "
                    "If you see this error-message it means you discovered an edge-case "
                    "and should open an issue in nf-core/tools. "
                )
        except KeyError:
            versions_by_module[module] = process_versions

    versions_by_module["Workflow"] = {
        "Nextflow": "$workflow.nextflow.version",
        "$workflow.manifest.name": "$workflow.manifest.version",
    }

    with open("software_versions.yml", "w") as f:
        yaml.dump(versions_by_module, f, default_flow_style=False)
    with open("software_mqc_versions.yml", "w") as f:
        yaml.dump(versions_by_module, f, default_flow_style=False)
    with open("versions.yml", "w") as f:
        yaml.dump(versions_this_module, f, default_flow_style=False)


if __name__ == "__main__":
    main()
