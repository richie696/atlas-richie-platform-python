#!/usr/bin/env bash

set -Eeuo pipefail

script_directory="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repository_root="$(cd -- "$script_directory/../../.." && pwd)"
contract_directory="$repository_root/foundation/contracts/tests/rules/managed_publication_v1"
java_directory="$contract_directory/java"

for required_command in uv mvn java; do
  if ! command -v "$required_command" >/dev/null 2>&1; then
    printf 'Required conformance tool not found: %s\n' "$required_command" >&2
    exit 69
  fi
done

cd "$repository_root"
printf '%s\n' 'Python managed rule-publication envelope V1 draft fixtures'
uv run --package atlas-richie-sentinel-dashboard --extra test -- pytest -q \
  foundation/contracts/tests/rules/managed_publication_v1/test_envelope_fixtures.py

printf '%s\n' 'Java managed rule-publication envelope V1 draft fixtures'
(cd "$java_directory" && \
  mvn -q package dependency:copy-dependencies -DincludeScope=runtime && \
  java -cp 'target/classes:target/dependency/*' \
    com.atlas_richie.contracts.managedrulev1.FixtureRunner ../fixtures)

printf '%s\n' 'Draft fixtures passed; this is Python/Java validator conformance, not production runtime interoperability or protocol-owner approval.'
