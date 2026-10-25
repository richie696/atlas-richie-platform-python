#!/usr/bin/env bash

set -Eeuo pipefail

script_directory="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repository_root="$(cd -- "$script_directory/../../.." && pwd)"
go_directory="$repository_root/foundation/contracts/tests/incidents/v1/go"
java_directory="$repository_root/foundation/contracts/tests/incidents/v1/java"

for required_command in uv go mvn java; do
  if ! command -v "$required_command" >/dev/null 2>&1; then
    printf 'Required conformance tool not found: %s\n' "$required_command" >&2
    exit 69
  fi
done

cd "$repository_root"
printf '%s\n' 'Python Incident Event V1 shared fixtures'
uv run --package atlas-richie-sentinel-dashboard --extra test -- pytest -q \
  foundation/contracts/tests/incidents/v1/test_incident_event.py \
  foundation/contracts/tests/incidents/v1/test_incident_event_fixtures.py

printf '%s\n' 'Go Incident Event V1 shared fixtures'
(cd "$go_directory" && go test -count=1 ./... && go vet ./...)

printf '%s\n' 'Java Incident Event V1 shared fixtures'
(cd "$java_directory" && \
  mvn -q package dependency:copy-dependencies -DincludeScope=runtime && \
  java -cp 'target/classes:target/dependency/*' \
    com.atlas_richie.contracts.incidentv1.FixtureRunner ../fixtures)

printf '%s\n' 'Incident Event V1 shared fixtures passed; Go and Java validators are test utilities, not production SDKs or owner signatures.'
