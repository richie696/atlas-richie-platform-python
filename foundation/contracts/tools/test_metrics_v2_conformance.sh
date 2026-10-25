#!/usr/bin/env bash

set -Eeuo pipefail

script_directory="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repository_root="$(cd -- "$script_directory/../../.." && pwd)"
go_directory="$repository_root/foundation/contracts/tests/reporting/v2/go"
java_directory="$repository_root/foundation/contracts/tests/reporting/v2/java"

for required_command in uv go mvn java; do
  if ! command -v "$required_command" >/dev/null 2>&1; then
    printf 'Required conformance tool not found: %s\n' "$required_command" >&2
    exit 69
  fi
done

printf '%s\n' 'Python frozen V2 model and shared fixtures'
cd "$repository_root"
uv run --package atlas-richie-sentinel-dashboard --extra test -- python -m json.tool \
  foundation/contracts/schemas/reporting/metrics-v2.schema.json >/dev/null
uv run --package atlas-richie-sentinel-dashboard --extra test -- python -m json.tool \
  foundation/contracts/schemas/reporting/metrics-v2-receipt.schema.json >/dev/null
uv run --package atlas-richie-sentinel-dashboard --extra test -- pytest -q \
  foundation/contracts/tests/reporting/v2/test_metrics_v2.py \
  foundation/contracts/tests/reporting/v2/test_metrics_v2_fixtures.py \
  foundation/contracts/tests/reporting/v2/test_metrics_v2_receipt.py

printf '%s\n' 'Go test-only shared-fixture validator'
(cd "$go_directory" && go test -count=1 ./... && go vet ./...)

printf '%s\n' 'Java test-only shared-fixture validator'
(cd "$java_directory" && \
  mvn -q package dependency:copy-dependencies -DincludeScope=runtime && \
  java -cp 'target/classes:target/dependency/*' \
    com.atlas_richie.contracts.metricsv2.FixtureRunner ../fixtures)

printf '%s\n' 'Metrics V2 shared fixture conformance passed; language validators are test utilities, not production SDKs.'
