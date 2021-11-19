#!/usr/bin/env python3
import argparse
import json
import logging
import os
from pathlib import Path
from typing import Dict, List

import testconfig


root_path = Path(__file__).parent.resolve()


def subdirs() -> List[Path]:
    dirs: List[Path] = []
    for r in root_path.iterdir():
        if r.is_dir():
            dirs.extend(Path(r).rglob("**/"))
    return sorted(d for d in dirs if not (any(c.startswith("_") for c in d.parts) or any(c.startswith(".") for c in d.parts)))


def module_dict(module):
    return {k: v for k, v in module.__dict__.items() if not k.startswith("_")}


def dir_config(dir):
    import importlib

    module_name = ".".join([*dir.relative_to(root_path).parts, "config"])
    try:
        return module_dict(importlib.import_module(module_name))
    except ModuleNotFoundError:
        return {}


def read_file(filename: Path) -> str:
    return filename.read_bytes().decode("utf8")


# # Input file
# def workflow_yaml_template_text(os):
#     return read_file(Path(root_path / f"runner-templates/build-test-{os}"))


# # Output files
# def workflow_yaml_file(dir, os, test_name):
#     return Path(dir / f"build-test-{os}-{test_name}.yml")


# String function from test dir to test name
def test_name(dir):
    return "-".join(dir.relative_to(root_path).parts)


# def transform_template(template_text, replacements):
#     t = template_text
#     for r, v in replacements.items():
#         t = t.replace(r, v)
#     return t


# # Replace with update_config
# def generate_replacements(conf, dir):
#     replacements = {
#         "INSTALL_TIMELORD": read_file(Path(root_path / "runner-templates/install-timelord.include.yml")).rstrip(),
#         "CHECKOUT_TEST_BLOCKS_AND_PLOTS": read_file(
#             Path(root_path / "runner-templates/checkout-test-plots.include.yml")
#         ).rstrip(),
#         "TEST_DIR": "",
#         "TEST_NAME": "",
#         "PYTEST_PARALLEL_ARGS": "",
#     }
#
#     if not conf["checkout_blocks_and_plots"]:
#         replacements[
#             "CHECKOUT_TEST_BLOCKS_AND_PLOTS"
#         ] = "# Omitted checking out blocks and plots repo Chia-Network/test-cache"
#     if not conf["install_timelord"]:
#         replacements["INSTALL_TIMELORD"] = "# Omitted installing Timelord"
#     if conf["parallel"]:
#         replacements["PYTEST_PARALLEL_ARGS"] = " -n auto"
#     if conf["job_timeout"]:
#         replacements["JOB_TIMEOUT"] = str(conf["job_timeout"])
#     replacements["TEST_DIR"] = "/".join([*dir.relative_to(root_path.parent).parts, "test_*.py"])
#     replacements["TEST_NAME"] = test_name(dir)
#     if "test_name" in conf:
#         replacements["TEST_NAME"] = conf["test_name"]
#     for var in conf["custom_vars"]:
#         replacements[var] = conf[var] if var in conf else ""
#     return replacements


# Overwrite with directory specific values
def update_config(parent, child):
    if child is None:
        return parent
    conf = child
    for k, v in parent.items():
        if k not in child:
            conf[k] = v
    return conf


def dir_path(string):
    p = Path(root_path / string)
    if p.is_dir():
        return p
    else:
        raise NotADirectoryError(string)


# args
arg_parser = argparse.ArgumentParser(description="Generate GitHub test matrix configuration")
arg_parser.add_argument("--verbose", "-v", action="store_true")
args = arg_parser.parse_args()

if args.verbose:
    logging.basicConfig(format="%(asctime)s:%(message)s", level=logging.DEBUG)

# main
test_dirs = subdirs()
# current_workflows: Dict[Path, str] = {file: read_file(file) for file in args.output_dir.iterdir()}
# changed: bool = False

configuration = []

for dir in test_dirs:
    relative_dir = dir.relative_to(root_path)
    logging.info(f"Considering: {relative_dir}")
    if len([f for f in Path(root_path / dir).glob("test_*.py")]) == 0:
        logging.info(f"Skipping {dir}: no tests collected")
        continue

    conf = update_config(module_dict(testconfig), dir_config(dir))

    for_matrix = {
        # TODO: handle CHECK_RESOURCE_USAGE
        'job_timeout': conf['job_timeout'],
        # TODO: disabled for now while debugging
        'pytest_parallel_args': '-n auto' if conf['parallel'] else '',
        'checkout_blocks_and_plots': conf["checkout_blocks_and_plots"],
        'install_timelord': conf["install_timelord"],
        'path': os.fspath(relative_dir),
        'name': '.'.join(relative_dir.with_suffix('').parts),
    }
    for_matrix = dict(sorted(for_matrix.items()))
    configuration.append(for_matrix)


# configuration = [{'path': os.fspath(path), 'name': '.'.join(path.with_suffix('').parts)} for path in test_paths]
# # TODO: remove this.  filtering just to avoid the hanging tests while
# # configuration = [c for c in configuration if c['name'] in ['plotting', 'generator', 'core.full_node']]
# # TODO: these are entirely commented out
# configuration = [c for c in configuration if c['name'] not in ['wallet.test_backup', 'wallet.test_wallet_store']]
# # TODO: these seem to hang
# # configuration = [
# #     c
# #     for c in configuration
# #     if c['name'] not in [
# #         'blockchain.test_blockchain_transactions',
# #         'core.full_node.test_mempool',
# #         'core.full_node.test_node_load',
# #         'core.full_node.test_performance',
# #         'core.full_node.test_transactions',
# #         'wallet.cc_wallet.test_cc_wallet',
# #         'wallet.sync.test_wallet_sync',
# #         'wallet.test_wallet_store',
# #     ]
# # ]

configuration_json = json.dumps(configuration)

for line in json.dumps(configuration, indent=4).splitlines():
    logging.info(line)

print(f'{configuration_json}')
