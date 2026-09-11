#!/usr/bin/env bash
# Compatibility notice for the retired PATH-shim generator.
set -euo pipefail
printf '%s\n' 'fleet dispatch now resolves the runtime and delivers its rendered seed directly.' >&2
printf '%s\n' 'Remove the old fleet shim from PATH and run fleet dispatch with the same profile and seed-extra file.' >&2
exit 2
