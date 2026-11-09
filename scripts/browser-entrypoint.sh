#!/usr/bin/env bash
set -euo pipefail
# One container owns this profile for its whole lifetime. Never remove its cookies.
profile_dir=/home/seluser/workbench-profile
exec 9>"$profile_dir/.workbench-container.lock"
if ! flock -n 9; then
  echo 'Another browser container owns this profile. Stop it before starting this browser.' >&2
  exit 1
fi
# Containers have different hostnames/PIDs. Chrome otherwise mistakes an old
# SingletonLock for a running browser after a container replacement.
rm -f "$profile_dir/SingletonLock" "$profile_dir/SingletonCookie" "$profile_dir/SingletonSocket"
exec /opt/bin/entry_point.sh
