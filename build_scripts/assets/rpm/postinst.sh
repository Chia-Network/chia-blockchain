#!/usr/bin/env bash
# Post install script for the UI .rpm to place symlinks in places to allow the CLI to work similarly in both versions

set -e

ln -s /opt/chia/resources/app.asar.unpacked/daemon/chia /usr/bin/chia || true
ln -s /opt/chia/chia-blockchain /usr/bin/chia-blockchain || true

# Install the AppArmor profile bundled by electron-builder, mirroring the deb
# postinst. Most RPM distros do not ship AppArmor, so everything is gated on
# apparmor_parser being present and AppArmor being enabled; otherwise this is a
# no-op. See build_scripts/assets/deb/postinst.sh for the full rationale.
APPARMOR_PROFILE_SOURCE='/opt/chia/resources/apparmor-profile'
APPARMOR_PROFILE_TARGET='/etc/apparmor.d/chia-blockchain'
if [ -f "$APPARMOR_PROFILE_SOURCE" ] && command -v apparmor_parser >/dev/null 2>&1 && apparmor_status --enabled >/dev/null 2>&1; then
  if apparmor_parser --skip-kernel-load --debug "$APPARMOR_PROFILE_SOURCE" >/dev/null 2>&1; then
    cp -f "$APPARMOR_PROFILE_SOURCE" "$APPARMOR_PROFILE_TARGET" || true
    if ! { [ -x '/usr/bin/ischroot' ] && /usr/bin/ischroot; } && hash apparmor_parser 2>/dev/null; then
      apparmor_parser --replace --write-cache --skip-read-cache "$APPARMOR_PROFILE_TARGET" || true
    fi
  else
    echo "Skipping AppArmor profile install: this version of AppArmor does not support the bundled profile"
  fi
fi
