#!/usr/bin/env bash
# Post install script for the UI .deb to place symlinks in places to allow the CLI to work similarly in both versions

set -e

chown -f root:root /opt/chia/chrome-sandbox || true
chmod -f 4755 /opt/chia/chrome-sandbox || true
ln -s /opt/chia/resources/app.asar.unpacked/daemon/chia /usr/bin/chia || true
ln -s /opt/chia/chia-blockchain /usr/bin/chia-blockchain || true

# Install the AppArmor profile bundled by electron-builder. (Ubuntu 24.04+)
#
# We override electron-builder's default afterInstall script (above), which
# means its built-in AppArmor handling is not emitted. Ubuntu 24.04+ ships
# kernel.apparmor_restrict_unprivileged_userns=1, so the Electron renderer
# sandbox cannot create its user namespace unless an AppArmor profile authorizes
# it -- without this, no renderer process is spawned and the GUI never appears.
#
# The profile is shipped at /opt/chia/resources/apparmor-profile but is inert
# until copied into /etc/apparmor.d/ and loaded. The compatibility dry-run keeps
# this a no-op on Ubuntu 22.04, whose AppArmor does not support the abi/4.0
# profile (the app runs fine there without it).
APPARMOR_PROFILE_SOURCE='/opt/chia/resources/apparmor-profile'
APPARMOR_PROFILE_TARGET='/etc/apparmor.d/chia-blockchain'
if [ -f "$APPARMOR_PROFILE_SOURCE" ] && command -v apparmor_parser >/dev/null 2>&1 && apparmor_status --enabled >/dev/null 2>&1; then
  if apparmor_parser --skip-kernel-load --debug "$APPARMOR_PROFILE_SOURCE" >/dev/null 2>&1; then
    cp -f "$APPARMOR_PROFILE_SOURCE" "$APPARMOR_PROFILE_TARGET" || true
    # Loading a profile is meaningless inside a chroot (e.g. image builders).
    if ! { [ -x '/usr/bin/ischroot' ] && /usr/bin/ischroot; } && hash apparmor_parser 2>/dev/null; then
      apparmor_parser --replace --write-cache --skip-read-cache "$APPARMOR_PROFILE_TARGET" || true
    fi
  else
    echo "Skipping AppArmor profile install: this version of AppArmor does not support the bundled profile"
  fi
fi
