#!/usr/bin/env python3

# Run from the current directory.

import argparse
import config
import logging
import subprocess
from pathlib import Path
from typing import List


def subdirs(root_dirs: List[str]) -> List[Path]:
    dirs: List[Path] = []
    for r in root_dirs:
        dirs.extend(Path(r).rglob("**/"))
    return [d for d in dirs if not (any(c.startswith("_") for c in d.parts) or any(c.startswith(".") for c in d.parts))]


def module_dict(module):
    return {k: v for k, v in module.__dict__.items() if not k.startswith("_")}


def dir_config(dir):
    import importlib

    module_name = str(dir).replace("/", ".") + ".config"
    try:
        return module_dict(importlib.import_module(module_name))
    except ModuleNotFoundError:
        return {}


def read_file(filename):
    with open(filename) as f:
        return f.read()
    return None


# input file
def workflow_yaml_template_text(os):
    return Path(f"runner-templates/build-test-{os}").read_text()


# output file
def workflow_yaml_file(os, test_name):
    return Path(f"../.github/workflows/build-test-{os}-{test_name}.yml")


# test dir to name
def test_name(dir):
    return str(dir).replace("/", "-")


def transform_template(template_text, replacements):
    t = template_text
    for r, v in replacements.items():
        t = t.replace(r, v)
    return t


def test_files_in_dir(dir):
    g = dir.glob("test_*.py")
    return [] if g is None else [f for f in g]


# -----

default_replacements = {
    "INSTALL_TIMELORD": read_file("runner-templates/install-timelord.include.yml").rstrip(),
    "CHECKOUT_TEST_BLOCKS_AND_PLOTS": read_file("runner-templates/checkout-test-plots.include.yml").rstrip(),
    "TEST_DIR": "",
    "TEST_NAME": "",
    "PYTEST_PARALLEL_ARGS": "",
}

# -----


# replace with update_config
def generate_replacements(defaults, conf, dir, test_files):
    assert len(test_files) > 0
    replacements = dict(defaults)

    if not conf["checkout_blocks_and_plots"]:
        replacements[
            "CHECKOUT_TEST_BLOCKS_AND_PLOTS"
        ] = "# Omitted checking out blocks and plots repo Chia-Network/test-cache"
    if not conf["install_timelord"]:
        replacements["INSTALL_TIMELORD"] = "# Omitted installing Timelord"
    if conf["parallel"]:
        replacements["PYTEST_PARALLEL_ARGS"] = "-n auto"
    if conf["job_timeout"]:
        replacements["JOB_TIMEOUT"] = str(conf["job_timeout"])
    test_paths = ["tests/" + str(f) for f in test_files]
    replacements["TEST_DIR"] = " ".join(test_paths)
    replacements["TEST_NAME"] = test_name(str(dir))
    if "test_name" in conf:
        replacements["TEST_NAME"] = conf["test_name"]
    return replacements


# overwrite with directory specific values
def update_config(parent, child):
    if child is None:
        return parent
    conf = child
    for k, v in parent.items():
        if k not in child:
            conf[k] = v
    return conf


# main
arg_parser = argparse.ArgumentParser(description="Build github workflows")
args = arg_parser.parse_args()

test_dirs = subdirs(config.root_test_dirs)  # type: ignore

for os in config.oses:  # type: ignore
    template_text = workflow_yaml_template_text(os)
    for dir in test_dirs:
        test_files = test_files_in_dir(dir)
        if len(test_files) == 0:
            logging.info(f"Skipping {dir}: no tests collected")
            continue
        conf = update_config(module_dict(config), dir_config(dir))
        replacements = generate_replacements(default_replacements, conf, dir, test_files)
        txt = transform_template(template_text, replacements)
        logging.info(f"Writing {os}-{test_name(dir)}")
        workflow_yaml_file(os, test_name(dir)).write_text(txt)

out = subprocess.run(["git", "diff", "../.github/workflows"])
print(out.stdout)
