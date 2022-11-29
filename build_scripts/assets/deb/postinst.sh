#!/usr/bin/env bash
# Post install script for the UI .deb to place symlinks in places to allow the CLI to work similarly in both versions

set -e

ln -s /opt/chia/resources/app.asar.unpacked/daemon/chia /usr/bin/chia || true
ln -s /opt/chia/chia-blockchain /usr/bin/chia-blockchain || true
