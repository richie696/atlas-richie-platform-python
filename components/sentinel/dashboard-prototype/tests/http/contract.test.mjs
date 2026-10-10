import assert from "node:assert/strict";
import { test } from "node:test";
import { z } from "zod";
import { createConsoleOpenApi, CONSOLE_OPERATIONS } from "../../src/app/api/consoleContract";
import { RULE_SET_HTTP_CONTRACT } from "../../src/features/rules/api/ruleSetContract";
import {
  diffFromWire,
  operationFromWire,
  planFromWire,
  publicationFromWire,
  receiptsFromWire,
  ruleSetSnapshotFromWire,
  ruleValidationFromWire,
} from "../../src/features/rules/api/ruleSetMapper";
import {
  RULE_EXAMPLE_BINDING,
  RULE_EXAMPLE_CANDIDATE,
  RULE_EXAMPLE_OPERATION,
  RULE_EXAMPLE_PUBLICATION,
  RULE_EXAMPLE_TIME,
} from "../../src/features/rules/api/ruleContractExamples";
import { RULE_MUTATION } from "../../src/features/rules/model/ruleSetOperations";
import { validRuleOperationObservation } from "../../src/features/rules/model/ruleOperationPolicy";
import {
  validRuleSetDiff,
  validValidationReport,
} from "../../src/features/rules/model/ruleDraftState";
import {
  validRulePublication,
  validPublicationReceipts,
} from "../../src/features/rules/model/ruleDeployment";
import { validRuleActivationPlan } from "../../src/features/rules/model/ruleDeploymentState";
import { validRuleSetSnapshot } from "../../src/features/rules/model/ruleSet";
import { validRulePublicationTargetSnapshot } from "../../src/features/rules/model/rulePublicationTarget";
import {
  CONSOLE_ERROR_STATUS,
  CONSOLE_HEADER,
  ConsoleErrorSchema,
  OpaqueIdentifierSchema,
} from "../../src/core/api/protocol/common";

test("CONSOLE-MACHINE: same runtime registry yields 44 operations across 43 unique paths, finite endpoint/status errors, CSRF/security and bodyless logout", () => {
  const document = createConsoleOpenApi();
  assert.equal(document.openapi, "3.1.0");
  assert.equal(document["x-contract-status"], "draft-partial");
  assert.equal(CONSOLE_OPERATIONS.length, 44);
  assert.equal(Object.keys(document.paths).length, 43);
  assert.deepEqual(document["x-pending-capabilities"], []);
  for (const operation of CONSOLE_OPERATIONS) {
    const endpoint = operation.endpoint,
      generated = document.paths[endpoint.url.path][endpoint.url.method.toLowerCase()];
    assert.equal(generated.operationId, operation.operationId);
    assert.equal(generated["x-unknown-outcome"], endpoint.command);
    assert.deepEqual(generated["x-semantic-rules"], operation.semanticRules);
    assert.deepEqual(generated["x-required-access"], operation.requiredAccess);
    assert.equal(
      generated.parameters.some((value) => value.name === CONSOLE_HEADER.Csrf),
      endpoint.csrf,
    );
    assert.equal(
      generated.parameters.some((value) => value.name === CONSOLE_HEADER.IdempotencyKey),
      endpoint.idempotency === "required",
    );
    const success = generated.responses[endpoint.successStatus];
    if (endpoint.successStatus === 204) assert.equal("content" in success, false);
    else
      assert.deepEqual(
        withoutUtf16Annotations(success.content["application/json"].schema),
        z.toJSONSchema(endpoint.response, { target: "draft-2020-12", unrepresentable: "throw" }),
      );
    const statuses = [...new Set(endpoint.errors.map((code) => CONSOLE_ERROR_STATUS[code]))];
    for (const status of statuses) {
      const response = generated.responses[status],
        code = response.content["application/json"].schema.properties.error.properties.code;
      assert.deepEqual(
        code.enum ?? [code.const],
        endpoint.errors.filter((value) => CONSOLE_ERROR_STATUS[value] === status),
      );
    }
  }
  const login = document.paths["/api/v1/auth/login"].post;
  assert.equal(
    login.requestBody.content["application/json"].schema.properties.password.writeOnly,
    true,
  );
  assert.equal(login.responses[200].content["application/json"].schema.additionalProperties, false);
  assert.equal(
    document.paths["/api/v1/system/bootstrap/initialize"].post.parameters.some(
      (value) => value.name === CONSOLE_HEADER.IdempotencyKey,
    ),
    true,
  );
  const queries = document.paths["/api/v1/accounts"].get.parameters.filter(
    (value) => value.in === "query",
  );
  assert.deepEqual(
    queries.map((value) => [value.name, value.required]),
    [
      ["page", true],
      ["pageSize", true],
      ["search", true],
      ["status", false],
    ],
  );
  assert.equal(
    document.paths["/api/v1/auth/password"].post.requestBody.content["application/json"].schema
      .properties.newPassword.writeOnly,
    true,
  );
});
test("CONSOLE-MACHINE: all operation positive/negative examples validate against runtime DTOs and OpenAPI", () => {
  const document = createConsoleOpenApi();
  const accountCommand = CONSOLE_OPERATIONS.find(
    (operation) => operation.operationId === "mutateAccount",
  );
  assert.ok(accountCommand);
  assert.equal(
    accountCommand.endpoint.response.safeParse({ status: "pending", requestKey: "account-pending" })
      .success,
    false,
    "account command pending is an in-flight UI state, never a wire receipt",
  );
  const operations = CONSOLE_OPERATIONS.filter((operation) => operation.examples?.length);
  assert.deepEqual(
    operations.map((operation) => operation.operationId),
    [
      "readBootstrap",
      "authorizeBootstrap",
      "readSession",
      "login",
      "logout",
      "checkBootstrapDatabase",
      "checkBootstrapSource",
      "initializeConsole",
      "readInitialization",
      "listAccounts",
      "readAccount",
      "mutateAccount",
      "readAccountOperation",
      "changeOwnPassword",
      "readMetrics",
      "readFleet",
      "readInstanceCatalog",
      "readInstanceObservation",
      "readObservationCatalog",
      "readIncidentTimeline",
      "readIncidentEvidence",
      "readSystemConnections",
      "readSystemProtocols",
      "readSystemAudit",
      "readRegisteredSources",
      "checkRegisteredSource",
      "mutateRegisteredSource",
      "readRegisteredSourceOperation",
      "createRuleBinding",
      "readRuleBindings",
      "readRuleSetSnapshot",
      "readRuleDrafts",
      "readRuleDraft",
      "validateRuleCandidate",
      "compareRuleCandidate",
      "readRuleVersions",
      "readRuleVersion",
      "readRulePublications",
      "readRulePublication",
      "readRulePublicationReceipts",
      "readRuleActivationPlans",
      "readRulePublicationTarget",
      "mutateRuleSet",
      "readRuleOperation",
    ],
  );

  for (const operation of operations) {
    const examples = operation.examples ?? [];
    assert.deepEqual(
      [...new Set(examples.map((example) => example.kind))].sort(),
      ["negative", "positive"],
      operation.operationId,
    );
    const generated =
      document.paths[operation.endpoint.url.path][operation.endpoint.url.method.toLowerCase()];
    assert.deepEqual(generated["x-contract-examples"], examples);

    for (const example of examples) {
      for (const parameter of operation.pathParameters) {
        const value = example.request.pathParameters?.[parameter.name];
        assert.notEqual(
          value,
          undefined,
          `${operation.operationId}:${example.name}:${parameter.name}`,
        );
        assert.equal(parameter.schema.safeParse(value).success, true, example.name);
        const generatedParameter = generated.parameters.find(
          (entry) => entry.in === "path" && entry.name === parameter.name,
        );
        assert.deepEqual(generatedParameter.examples[example.name].value, value);
      }
      for (const parameter of operation.queryParameters ?? []) {
        const value = example.request.queryParameters?.[parameter.name];
        if (value !== undefined) {
          assert.equal(parameter.schema.safeParse(value).success, true, example.name);
          const generatedParameter = generated.parameters.find(
            (entry) => entry.in === "query" && entry.name === parameter.name,
          );
          assert.deepEqual(generatedParameter.examples[example.name].value, value);
        }
      }
      if (Object.hasOwn(example.request, "body")) {
        assert.ok(operation.input, operation.operationId);
        assert.equal(
          operation.input.safeParse(example.request.body).success,
          example.request.bodyConforms ?? true,
          `${operation.operationId}:${example.name}:request`,
        );
        const requestExamples = generated.requestBody.content["application/json"].examples;
        assert.deepEqual(requestExamples[example.name].value, example.request.body);
      }

      const { status, body } = example.response;
      const response = generated.responses[status];
      assert.ok(response, `${operation.operationId}:${example.name}:status`);
      if (status === operation.endpoint.successStatus) {
        if (status === 204) assert.equal(body, undefined, example.name);
        else {
          assert.equal(operation.endpoint.response.safeParse(body).success, true, example.name);
          assert.deepEqual(response.content["application/json"].examples[example.name].value, body);
        }
      } else {
        const parsed = ConsoleErrorSchema.safeParse(body);
        assert.equal(parsed.success, true, `${operation.operationId}:${example.name}:error-body`);
        assert.ok(operation.endpoint.errors.includes(parsed.data.error.code), example.name);
        assert.equal(CONSOLE_ERROR_STATUS[parsed.data.error.code], status, example.name);
        assert.deepEqual(response.content["application/json"].examples[example.name].value, body);
      }
    }
  }
});

test("CONSOLE-MACHINE: rule lifecycle examples also satisfy domain identity and state invariants", () => {
  const operation = (operationId) =>
    RULE_SET_HTTP_CONTRACT.find((entry) => entry.operationId === operationId);
  const example = (operationId, name) =>
    operation(operationId).examples.find((entry) => entry.name === name);

  assert.equal(
    validRuleSetSnapshot(
      ruleSetSnapshotFromWire(
        example("readRuleSetSnapshot", "authoritative-empty-snapshot").response.body,
      ),
      RULE_EXAMPLE_BINDING.id,
    ),
    true,
  );
  assert.equal(
    validValidationReport(
      ruleValidationFromWire(
        example("validateRuleCandidate", "candidate-publishable").response.body,
      ),
      RULE_EXAMPLE_CANDIDATE,
    ),
    true,
  );
  assert.equal(
    validRuleSetDiff(
      diffFromWire(example("compareRuleCandidate", "candidate-diff").response.body),
      RULE_EXAMPLE_CANDIDATE,
    ),
    true,
  );

  const publication = publicationFromWire(
    example("readRulePublication", "publication-phases").response.body,
  );
  assert.equal(validRulePublication(publication, RULE_EXAMPLE_BINDING.id), true);
  assert.equal(
    validPublicationReceipts(
      receiptsFromWire(
        example("readRulePublicationReceipts", "unknown-instance-population").response.body,
      ),
      publication,
      1,
      50,
    ),
    true,
  );
  assert.equal(
    validRuleActivationPlan(
      planFromWire(
        example("readRuleActivationPlans", "scheduled-activation").response.body.items[0],
      ),
      RULE_EXAMPLE_BINDING.id,
    ),
    true,
  );
  assert.equal(
    validRulePublicationTargetSnapshot(
      example("readRulePublicationTarget", "configured-target").response.body,
      RULE_EXAMPLE_BINDING.id,
    ),
    true,
  );

  const pendingRequest = example("mutateRuleSet", "save-draft-pending").request.body;
  const mutation = {
    ...pendingRequest.mutation,
    bindingId: RULE_EXAMPLE_BINDING.id,
    requestKey: pendingRequest.requestKey,
  };
  assert.equal(
    validRuleOperationObservation(
      operationFromWire(example("mutateRuleSet", "save-draft-pending").response.body),
      mutation,
      false,
    ),
    true,
  );
  assert.equal(
    validRuleOperationObservation(
      operationFromWire(example("readRuleOperation", "command-completed").response.body),
      mutation,
      true,
    ),
    true,
  );
  assert.equal(RULE_EXAMPLE_OPERATION.requestKey, mutation.requestKey);
  assert.equal(RULE_EXAMPLE_PUBLICATION.id, publication.id);
  assert.ok(Date.parse(RULE_EXAMPLE_TIME.activateAt) > Date.parse(RULE_EXAMPLE_TIME.asOf));
});
test("CONSOLE-MACHINE: role and capability authorization is explicit and separate from session security", () => {
  const document = createConsoleOpenApi();
  for (const pathItem of Object.values(document.paths)) {
    for (const operation of Object.values(pathItem)) {
      const access = operation["x-required-access"];
      assert.deepEqual(Object.keys(access).sort(), ["capabilities", "role"]);
      assert.ok(access.role === null || access.role === "admin");
      assert.ok(Array.isArray(access.capabilities));
      assert.ok(
        access.capabilities.every((capability) =>
          ["metrics:view", "rules:write"].includes(capability),
        ),
      );
      if (access.role !== null || access.capabilities.length > 0) {
        assert.equal(operation.security.length, 1);
        assert.deepEqual(operation.security[0].BrowserSession, []);
      }
    }
  }
});
test("CONSOLE-MACHINE: duplicate operation/route and missing path declaration fail rather than produce misleading API coverage", () => {
  assert.throws(
    () => createConsoleOpenApi([CONSOLE_OPERATIONS[0], CONSOLE_OPERATIONS[0]]),
    /Duplicate/,
  );
  assert.throws(
    () => createConsoleOpenApi([{ ...CONSOLE_OPERATIONS[8], pathParameters: [] }]),
    /missing path/,
  );
  assert.throws(
    () =>
      createConsoleOpenApi([
        CONSOLE_OPERATIONS[0],
        { ...CONSOLE_OPERATIONS[0], operationId: "different-name" },
      ]),
    /Duplicate Console method/,
  );
  assert.throws(
    () =>
      createConsoleOpenApi([
        { ...CONSOLE_OPERATIONS[0], requiredAccess: { role: "admin", capabilities: [] } },
      ]),
    /requires a session-protected operation/,
  );
});

test("CONSOLE-MACHINE: bounded strings declare JavaScript/Python UTF-16 length semantics", () => {
  const document = createConsoleOpenApi();
  const boundedStrings = collectBoundedStringSchemas(document);
  assert.ok(boundedStrings.length > 0);
  for (const schema of boundedStrings) {
    assert.equal(schema["x-max-utf16-code-units"], schema.maxLength);
  }
  assert.equal(OpaqueIdentifierSchema.safeParse("a".repeat(200)).success, true);
  assert.equal(OpaqueIdentifierSchema.safeParse("😀".repeat(100)).success, true);
  assert.equal(OpaqueIdentifierSchema.safeParse("😀".repeat(101)).success, false);
  assert.equal(OpaqueIdentifierSchema.safeParse(`${"a".repeat(199)}\n`).success, true);
  assert.equal(OpaqueIdentifierSchema.safeParse(`${"a".repeat(200)}\n`).success, false);
});

function collectBoundedStringSchemas(value, schemas = []) {
  if (Array.isArray(value)) {
    for (const entry of value) collectBoundedStringSchemas(entry, schemas);
    return schemas;
  }
  if (value === null || typeof value !== "object") return schemas;
  if (value.type === "string" && typeof value.maxLength === "number") schemas.push(value);
  for (const nested of Object.values(value)) collectBoundedStringSchemas(nested, schemas);
  return schemas;
}

function withoutUtf16Annotations(value) {
  if (Array.isArray(value)) return value.map(withoutUtf16Annotations);
  if (value === null || typeof value !== "object") return value;
  return Object.fromEntries(
    Object.entries(value)
      .filter(([key]) => key !== "x-max-utf16-code-units")
      .map(([key, nested]) => [key, withoutUtf16Annotations(nested)]),
  );
}
