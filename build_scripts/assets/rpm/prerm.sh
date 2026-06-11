#!/usr/bin/env bash
# Pre remove script for the UI .rpm to clean up the symlinks from the installer

set -e

unlink /usr/bin/chia || true
unlink /usr/bin/chia-blockchain || true

# Remove the AppArmor profile installed by postinst, if present.
APPARMOR_PROFILE_TARGET='/etc/apparmor.d/chia-blockchain'
if [ -f "$APPARMOR_PROFILE_TARGET" ]; then
  if command -v apparmor_parser >/dev/null 2>&1 && ! { [ -x '/usr/bin/ischroot' ] && /usr/bin/ischroot; }; then
    apparmor_parser --remove "$APPARMOR_PROFILE_TARGET" 2>/dev/null || true
  fi
  rm -f "$APPARMOR_PROFILE_TARGET" || true
fi
