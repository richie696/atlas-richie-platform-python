import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { test } from "node:test";
import { z } from "zod";
import { createConsoleOpenApi, CONSOLE_OPERATIONS } from "../../src/app/api/consoleContract";
import { RULE_SET_HTTP_CONTRACT } from "../../src/features/rules/api/ruleSetContract";
import { FLEET_ENDPOINT } from "../../src/features/overview/api/fleetHttp";
import { OBSERVATION_CATALOG_ENDPOINT } from "../../src/features/applications/api/catalogHttp";
import { INSTANCE_ENDPOINTS } from "../../src/features/applications/api/instanceHttp";
import { METRICS_ENDPOINT } from "../../src/features/realtime/api/metricsHttp";
import { INCIDENT_ENDPOINTS } from "../../src/features/faults/api/incidentHttp";
import { SYSTEM_OBSERVATION_ENDPOINTS } from "../../src/features/system/api/systemObservationHttp";
import { SOURCE_REGISTRATION_ENDPOINTS } from "../../src/features/system/api/sourceRegistrationHttp";
import { IDENTITY_ENDPOINTS } from "../../src/features/identity/api/identityEndpoints";
import { ACCOUNT_ENDPOINTS } from "../../src/features/identity/api/accountManagementEndpoints";
import {
  AccountCreateInputSchema,
  AccountRecordSchema,
} from "../../src/features/identity/api/accountManagementWire";
import { NewAccountPasswordSchema } from "../../src/features/identity/api/accountPasswordWire";
import { OWN_PASSWORD_ENDPOINT } from "../../src/features/identity/api/ownPasswordHttp";
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
  PUBLICATION_REASON,
  PUBLICATION_STAGE,
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

test("PASSWORD-CONTRACT: all new-password schemas declare and enforce 8–32 UTF-16 units", () => {
  const document = createConsoleOpenApi();
  const requestSchema = (path) =>
    document.paths[path].post.requestBody.content["application/json"].schema;
  const commands = requestSchema("/api/v1/accounts/commands").oneOf;
  const create = commands.find((variant) => variant.properties.kind.const === "create");
  const reset = commands.find((variant) => variant.properties.kind.const === "reset_password");
  const fields = [
    requestSchema("/api/v1/auth/password").properties.newPassword,
    requestSchema("/api/v1/system/bootstrap/initialize").properties.input.properties.admin
      .properties.password,
    create.properties.input.properties.password,
    reset.properties.password,
  ];
  for (const schema of fields) {
    assert.equal(schema.minLength, 8);
    assert.equal(schema.maxLength, 32);
    assert.equal(schema["x-max-utf16-code-units"], 32);
    assert.equal(schema.writeOnly, true);
    const pattern = new RegExp(schema.pattern);
    for (const [value, valid] of [
      ["a".repeat(7), false],
      ["a".repeat(8), true],
      ["a".repeat(32), true],
      ["a".repeat(33), false],
      ["😀".repeat(16), true],
      ["😀".repeat(17), false],
    ]) {
      const declared =
        [...value].length >= schema.minLength &&
        [...value].length <= schema.maxLength &&
        pattern.test(value);
      assert.equal(declared, valid);
      assert.equal(NewAccountPasswordSchema.safeParse(value).success, valid);
    }
  }
  const login = requestSchema("/api/v1/auth/login").properties.password;
  const current = requestSchema("/api/v1/auth/password").properties.currentPassword;
  assert.equal(login.maxLength, 1024);
  assert.equal(current.maxLength, 1024);
});

test("CONSOLE-DOC: published contract counts match the runtime registry and generated OpenAPI", () => {
  const document = createConsoleOpenApi();
  const contract = readFileSync(
    resolve(process.cwd(), "../docs/contract/Console-API-契约.md"),
    "utf8",
  );
  const operations = CONSOLE_OPERATIONS;
  const exchangeExamples = operations.reduce(
    (count, operation) => count + (operation.examples?.length ?? 0),
    0,
  );
  const mediaExamples = operations.reduce((count, operation) => {
    const route = document.paths[operation.endpoint.url.path];
    const generated = route[operation.endpoint.url.method.toLowerCase()];
    const requestCount = Object.values(generated.requestBody?.content ?? {}).reduce(
      (total, media) => total + Object.keys(media.examples ?? {}).length,
      0,
    );
    const responseCount = Object.values(generated.responses ?? {}).reduce(
      (total, response) =>
        total +
        Object.values(response.content ?? {}).reduce(
          (mediaTotal, media) => mediaTotal + Object.keys(media.examples ?? {}).length,
          0,
        ),
      0,
    );
    return count + requestCount + responseCount;
  }, 0);

  assert.match(
    contract,
    new RegExp(`\\*\\*${operations.length}/${operations.length}\\*\\*.*operations?`),
  );
  assert.match(contract, new RegExp(`\\*\\*${Object.keys(document.paths).length} paths\\*\\*`));
  assert.match(contract, new RegExp(`\\*\\*${exchangeExamples}\\*\\*[^\\n]*exchange`));
  assert.match(contract, new RegExp(`\\*\\*${mediaExamples}[^\\n]*media examples`));
});

test("CONSOLE-DOC: source credential input supports explicit modes without browser provider access", () => {
  const contract = readFileSync(
    resolve(process.cwd(), "../docs/contract/Console-API-契约.md"),
    "utf8",
  );
  assert.doesNotMatch(contract, /不做连接凭证的网页写入/);
  assert.match(contract, /不让浏览器直连 Nacos\/Consul/);
  assert.match(contract, /显式选择 `none`、`reference` 或 `direct`/);
  assert.match(contract, /write-only 提交并在服务端保护/);
  assert.match(contract, /不得回显明文或引用值/);
});

test("CONSOLE-DOC: synchronous fixture gateway is historical, not current integration guidance", () => {
  const contract = readFileSync(
    resolve(process.cwd(), "../docs/contract/Console-API-契约.md"),
    "utf8",
  );
  assert.doesNotMatch(contract, /默认是 `fixtureGateway`/);
  assert.match(contract, /已作废的历史接线说明/);
  assert.match(contract, /feature-owned HTTP adapters 与共享 Console transport/);
  assert.match(contract, /demo 仅由[\s\S]*?HTTP boundary 的 MSW 拦截/);
  assert.match(contract, /live 由同一 adapters 请求 Python Console/);
  assert.match(contract, /不保留[\s\S]*?`FixtureGateway` 兼容路径/);
});

test("CONSOLE-MACHINE: same runtime registry yields 68 operations across 64 unique paths, finite endpoint/status errors, CSRF/security and bodyless logout", () => {
  const document = createConsoleOpenApi();
  assert.equal(document.openapi, "3.1.0");
  assert.equal(document.info.version, "0.19.0");
  assert.equal(document["x-contract-status"], "frozen");
  assert.match(document.info.description, /0\.19\.0 baseline \(2026-10-24\)/);
  const frozenArtifact = readFileSync(
    resolve(process.cwd(), "../docs/protocol/console-api.openapi.json"),
  );
  assert.equal(
    createHash("sha256").update(frozenArtifact).digest("hex"),
    "c9c6f08797fc6dc3bf3efa7ed9a0bf753a2f99d7d265a991d1233278c9a31d33",
    "Console API 0.19.0 wire changed; review and advance the contract version explicitly",
  );
  const contract = readFileSync(
    resolve(process.cwd(), "../docs/contract/Console-API-契约.md"),
    "utf8",
  );
  assert.match(
    contract,
    /0\.8\.0 于 2026-10-16 按已批准的规则目录设计增加配置中心规则读取与有界刷新/,
  );
  assert.equal(CONSOLE_OPERATIONS.length, 68);
  assert.equal(Object.keys(document.paths).length, 64);
  assert.deepEqual(document["x-pending-capabilities"], []);
  for (const operation of CONSOLE_OPERATIONS) {
    const endpoint = operation.endpoint,
      generated = document.paths[endpoint.url.path][endpoint.url.method.toLowerCase()];
    assert.equal(generated.operationId, operation.operationId);
    assert.equal(generated["x-unknown-outcome"], endpoint.command);
    assert.deepEqual(generated["x-semantic-rules"], operation.semanticRules);
    assert.deepEqual(generated["x-required-access"], operation.requiredAccess);
    const queryParameters = generated.parameters.filter((value) => value.in === "query");
    if (queryParameters.length > 0) {
      assert.deepEqual(generated["x-query-policy"], {
        unknownParameters: "reject",
        duplicateParameters: "reject",
        rejection: { status: 400, code: "invalid_request" },
      });
      for (const parameter of queryParameters) {
        assert.equal(
          parameter["x-query-integer-encoding"],
          parameter.schema.type === "integer" ? "canonical-decimal" : undefined,
          `${operation.operationId}.${parameter.name} integer encoding must be explicit`,
        );
      }
    } else {
      assert.equal("x-query-policy" in generated, false);
    }
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
  const idempotentCommands = CONSOLE_OPERATIONS.filter(
    (operation) => operation.endpoint.idempotency === "required",
  );
  assert.ok(idempotentCommands.length > 0);
  for (const operation of idempotentCommands) {
    assert.ok(
      operation.semanticRules.some((rule) =>
        /idempotency(?:-key| header).*equals?.*requestKey/i.test(rule),
      ),
      `${operation.operationId} must document its header/body idempotency identity`,
    );
  }
});

test("CONSOLE-MACHINE: every rate_limited response requires retryAfterMs in OpenAPI", () => {
  const document = createConsoleOpenApi();
  for (const operation of CONSOLE_OPERATIONS) {
    if (!operation.endpoint.errors.includes("rate_limited")) continue;
    const generated =
      document.paths[operation.endpoint.url.path][operation.endpoint.url.method.toLowerCase()];
    const schema = generated.responses[429].content["application/json"].schema;
    assert.deepEqual(
      schema.properties.error.properties.code.enum ?? [
        schema.properties.error.properties.code.const,
      ],
      ["rate_limited"],
    );
    assert.ok(schema.properties.error.required.includes("retryAfterMs"));
  }
});

test("F7.4: account creation and read contract expose only the intended account fields", () => {
  const document = createConsoleOpenApi();
  const commandSchema =
    document.paths["/api/v1/accounts/commands"].post.requestBody.content["application/json"].schema;
  const createCommand = commandSchema.oneOf.find(
    (variant) => variant.properties.kind.const === "create",
  );
  assert.ok(createCommand, "the account command union includes create");
  assert.deepEqual(Object.keys(createCommand.properties.input.properties).sort(), [
    "password",
    "roleId",
    "username",
  ]);
  assert.equal(createCommand.properties.input.properties.password.writeOnly, true);
  assert.deepEqual(Object.keys(z.toJSONSchema(AccountCreateInputSchema).properties).sort(), [
    "password",
    "roleId",
    "username",
  ]);
  assert.deepEqual(Object.keys(AccountRecordSchema.shape).sort(), [
    "builtIn",
    "id",
    "lastActiveAdmin",
    "lastLoginAt",
    "revision",
    "roleId",
    "status",
    "username",
  ]);

  const pageDesign = readFileSync(
    resolve(process.cwd(), "../docs/design/页面能力与接口设计.md"),
    "utf8",
  );
  const accounts = pageChapter(pageDesign, "## 10. 账户维护", "## 11.");
  assert.match(accounts, /业务输入只有\*\*账号名、密码、角色\*\*/);
  assert.match(accounts, /没有显示名称，也不要求新增时确认密码/);
  assert.match(accounts, /密码只出现在创建请求体/);
});

test("F6.1: disabling an account revokes existing sessions and re-enable cannot restore them", () => {
  const operation = CONSOLE_OPERATIONS.find(
    (candidate) => candidate.operationId === "mutateAccount",
  );
  assert.ok(operation, "the account mutation operation is registered");
  const rule = operation.semanticRules.find((value) =>
    /active to disabled.*re-enabling/i.test(value),
  );
  assert.ok(rule, "the runtime account command contract declares session revocation");

  const openApi = createConsoleOpenApi();
  const generated = openApi.paths["/api/v1/accounts/commands"].post;
  assert.ok(generated["x-semantic-rules"].includes(rule));

  const pageDesign = readFileSync(
    resolve(process.cwd(), "../docs/design/页面能力与接口设计.md"),
    "utf8",
  );
  const accountChapter = pageChapter(pageDesign, "## 10. 账户维护", "## 11.");
  assert.match(accountChapter, /同一事务内撤销该账号所有现有会话/);
  assert.match(accountChapter, /重新启用不会恢复旧 session\/Cookie/);

  const consoleContract = readFileSync(
    resolve(process.cwd(), "../docs/contract/Console-API-契约.md"),
    "utf8",
  );
  assert.match(consoleContract, /同一数据库事务内撤销该账号全部现有 session/);
  assert.match(consoleContract, /重新启用账号不会恢复或重新签发旧 session/);
});

test("F6.1: own-password reauthentication and all-session revocation stay in the page contract", () => {
  const operation = CONSOLE_OPERATIONS.find(
    (candidate) => candidate.operationId === "changeOwnPassword",
  );
  assert.ok(operation, "the own-password operation is registered");
  const rule = operation.semanticRules.find((value) =>
    /atomically updates the password hash, revokes every account session/i.test(value),
  );
  assert.ok(rule, "the runtime contract declares atomic password/session behavior");
  const generated = createConsoleOpenApi().paths["/api/v1/auth/password"].post;
  assert.ok(generated["x-semantic-rules"].includes(rule));

  const pageDesign = readFileSync(
    resolve(process.cwd(), "../docs/design/页面能力与接口设计.md"),
    "utf8",
  );
  const passwordChapter = pageChapter(pageDesign, "## 12. 修改密码", "## 13.");
  assert.match(passwordChapter, /sessionDisposition: "reauthenticate"/);
  assert.match(passwordChapter, /事务修改哈希并撤销该账号所有 session/);
  assert.match(passwordChapter, /然后清除当前 session\/CSRF Cookie/);
});

test("F7.4: all 11 page chapters document runtime operations, schema fields, and wire enums", () => {
  const pageDesign = readFileSync(
    resolve(process.cwd(), "../docs/design/页面能力与接口设计.md"),
    "utf8",
  );
  const chapters = [...pageDesign.matchAll(/^## (\d+)\./gm)]
    .map((match) => Number(match[1]))
    .filter((chapter) => chapter >= 2 && chapter <= 12);
  assert.deepEqual(chapters, [2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]);

  const pageHeadings = [...pageDesign.matchAll(/^## (\d+)\./gm)];
  for (const chapterNumber of chapters) {
    const headingIndex = pageHeadings.findIndex((heading) => Number(heading[1]) === chapterNumber);
    const chapterStart = pageHeadings[headingIndex].index;
    const chapterEnd = pageHeadings[headingIndex + 1]?.index ?? pageDesign.length;
    const chapter = pageDesign.slice(chapterStart, chapterEnd);
    const statusHeading = [...chapter.matchAll(/^### \d+\.\d+ (.*)$/gm)]
      .reverse()
      .find((heading) => /当前实现|状态与验收|失败与验收/.test(heading[1]));
    assert.ok(statusHeading, `page chapter ${chapterNumber} needs a current-state section`);
    const statusSection = chapter.slice(statusHeading.index);
    assert.match(
      statusSection,
      /demo|mock/i,
      `page chapter ${chapterNumber} must state Mock evidence`,
    );
    assert.match(
      statusSection,
      /Python|live|真实.*服务|权威源/i,
      `page chapter ${chapterNumber} must state live/backend authority boundaries`,
    );
  }

  const mappingStart = pageDesign.indexOf("### 13.1 页面动作到当前 machine operations 的映射");
  const mappingEnd = pageDesign.indexOf("### 13.1.1", mappingStart);
  assert.ok(mappingStart >= 0 && mappingEnd > mappingStart, "page operation mapping table exists");
  const mappingLines = pageDesign
    .slice(mappingStart, mappingEnd)
    .split("\n")
    .filter((line) => line.startsWith("| §"));
  const mappedChapters = new Set();
  const mappedOperations = new Set();
  const operationOwners = new Map();
  for (const line of mappingLines) {
    const cells = line.split("|");
    const chapterNumbers = [...cells[1].matchAll(/§(\d+)/g)].map((match) => Number(match[1]));
    const operationIds = [...cells[2].matchAll(/`([a-z][A-Za-z0-9]*)`/g)].map((match) => match[1]);
    for (const chapter of chapterNumbers) mappedChapters.add(chapter);
    for (const operationId of operationIds) {
      mappedOperations.add(operationId);
      const owners = operationOwners.get(operationId) ?? new Set();
      chapterNumbers.forEach((chapter) => owners.add(chapter));
      operationOwners.set(operationId, owners);
    }
  }
  assert.deepEqual(
    [...mappedChapters].sort((left, right) => left - right),
    chapters,
  );

  const registeredOperations = new Set(
    CONSOLE_OPERATIONS.map((operation) => operation.operationId),
  );
  assert.deepEqual(
    [...mappedOperations].filter((operationId) => !registeredOperations.has(operationId)),
    [],
    "page documentation must not name an operation absent from the runtime contract",
  );
  assert.deepEqual(
    [...registeredOperations].filter((operationId) => !mappedOperations.has(operationId)).sort(),
    [],
    "every runtime Console operation must have a page owner in the design mapping",
  );

  const openApi = createConsoleOpenApi();
  const undocumentedSchemaFields = [];
  const undocumentedSchemaEnums = [];
  const undocumentedSchemaBounds = [];
  for (const operation of CONSOLE_OPERATIONS) {
    const endpointMethod = operation.endpoint.url.method.toUpperCase();
    const endpointPath = operation.endpoint.url.path;
    const ownerChapters = operationOwners.get(operation.operationId);
    assert.ok(ownerChapters, `${operation.operationId} must have a page chapter owner`);
    const ownerSections = [...ownerChapters].map((chapter) => {
      const headingIndex = pageHeadings.findIndex((heading) => Number(heading[1]) === chapter);
      assert.notEqual(headingIndex, -1, `chapter ${chapter} must exist`);
      const start = pageHeadings[headingIndex].index;
      const end = pageHeadings[headingIndex + 1]?.index ?? pageDesign.length;
      return pageDesign.slice(start, end);
    });
    const documentedInOwnerChapter = ownerSections.some((section) =>
      section.includes(`${endpointMethod} ${endpointPath}`),
    );
    assert.ok(
      documentedInOwnerChapter,
      `${operation.operationId} must document ${endpointMethod} ${endpointPath} in an owning page chapter`,
    );

    const route = openApi.paths[endpointPath][operation.endpoint.url.method.toLowerCase()];
    for (const parameter of route.parameters.filter(
      (value) => value.in === "path" || value.in === "query",
    )) {
      assert.ok(
        ownerSections.some((section) => section.includes(parameter.name)),
        `${operation.operationId} must document ${parameter.in} parameter ${parameter.name} in an owning page chapter`,
      );
      for (const keyword of [
        "minLength",
        "maxLength",
        "minimum",
        "maximum",
        "minItems",
        "maxItems",
      ]) {
        const expectedValue = parameter.schema?.[keyword];
        if (expectedValue === undefined) continue;
        assert.ok(
          ownerSections.some(
            (section) =>
              section.includes(parameter.name) && section.includes(String(expectedValue)),
          ),
          `${operation.operationId} ${parameter.in} parameter ${parameter.name} must document ${keyword}=${expectedValue}`,
        );
      }
      for (const value of documentedSchemaEnumValues(parameter.schema, openApi)) {
        if (!ownerSections.some((section) => section.includes(value)))
          undocumentedSchemaEnums.push(`${operation.operationId} ${parameter.name}=${value}`);
      }
    }

    const requestSchema = route.requestBody?.content?.["application/json"]?.schema;
    const responseSchema =
      route.responses[String(operation.endpoint.successStatus)]?.content?.["application/json"]
        ?.schema;
    for (const [direction, schema, includeProperty] of [
      ["request", requestSchema],
      [
        "response",
        responseSchema,
        (property) => /^(?:health|phase|quality|reason|result|role|state|status)$/i.test(property),
      ],
    ]) {
      for (const value of documentedSchemaEnumValues(schema, openApi, new Set(), includeProperty)) {
        if (!ownerSections.some((section) => section.includes(value)))
          undocumentedSchemaEnums.push(`${operation.operationId} ${direction}=${value}`);
      }
    }
    for (const [direction, schema] of [
      ["request", requestSchema],
      ["response", responseSchema],
    ]) {
      for (const field of documentedSchemaFields(schema, openApi)) {
        if (!ownerSections.some((section) => section.includes(field)))
          undocumentedSchemaFields.push(`${operation.operationId} ${direction}.${field}`);
      }
    }
    for (const [direction, schema] of [
      ["request", requestSchema],
      ["response", responseSchema],
    ]) {
      for (const bound of documentedSchemaBounds(schema, openApi)) {
        if (
          !ownerSections.some(
            (section) => section.includes(bound.property) && section.includes(String(bound.value)),
          )
        ) {
          undocumentedSchemaBounds.push(
            `${operation.operationId} ${direction}.${bound.property} ${bound.keyword}=${bound.value}`,
          );
        }
      }
    }
  }
  assert.deepEqual(
    undocumentedSchemaFields,
    [],
    "page chapters must document every request/response schema field",
  );
  assert.deepEqual(
    undocumentedSchemaEnums,
    [],
    "page chapters must document every request/response decision enum wire value",
  );
  assert.deepEqual(
    undocumentedSchemaBounds,
    [],
    "page chapters must document every JSON request/response schema bound",
  );
});

test("F7.4: every page chapter names its demo HTTP mock owner and Python authority boundary", () => {
  const pageDesign = readFileSync(
    resolve(process.cwd(), "../docs/design/页面能力与接口设计.md"),
    "utf8",
  );
  const sectionStart = pageDesign.indexOf("### 13.1.1 页面 Mock 工厂与 Python 权威数据责任");
  const sectionEnd = pageDesign.indexOf("### 13.2", sectionStart);
  assert.ok(
    sectionStart >= 0 && sectionEnd > sectionStart,
    "page mock responsibility matrix exists",
  );
  const section = pageDesign.slice(sectionStart, sectionEnd);
  assert.match(section, /页面、workflow 和 feature API 不得直接导入 handler/);
  const rows = section.split("\n").filter((line) => line.startsWith("| §"));
  assert.equal(rows.length, 11, "all page chapters §2 through §12 need one responsibility row");

  const expected = new Map([
    [2, ["createFleetMockHandlers", "createApplicationsMockHandlers"]],
    [3, ["createApplicationsMockHandlers"]],
    [4, ["createRuleSetMockHandlers"]],
    [5, ["createRealtimeMockHandlers"]],
    [6, ["createIncidentMockHandlers"]],
    [7, ["createSystemMockHandlers"]],
    [8, ["createIdentityMockHandlers"]],
    [9, ["createIdentityMockHandlers"]],
    [10, ["createAccountManagementMockHandlers"]],
    [11, ["createAccountManagementMockHandlers"]],
    [12, ["createAccountManagementMockHandlers"]],
  ]);
  const featureForFactory = new Map([
    ["createFleetMockHandlers", "overview"],
    ["createApplicationsMockHandlers", "applications"],
    ["createRuleSetMockHandlers", "rules"],
    ["createRealtimeMockHandlers", "realtime"],
    ["createIncidentMockHandlers", "faults"],
    ["createSystemMockHandlers", "system"],
    ["createIdentityMockHandlers", "identity"],
    ["createAccountManagementMockHandlers", "identity"],
  ]);
  const documentedChapters = new Set();
  for (const row of rows) {
    const chapter = Number(row.match(/^\| §(\d+)/)?.[1]);
    assert.ok(expected.has(chapter), `unexpected page chapter row: ${row}`);
    assert.equal(documentedChapters.has(chapter), false, `duplicate chapter §${chapter}`);
    documentedChapters.add(chapter);
    for (const factory of expected.get(chapter)) {
      assert.ok(row.includes(`\`${factory}\``), `chapter §${chapter} must name ${factory}`);
      const feature = featureForFactory.get(factory);
      assert.ok(feature, `${factory} must have a feature-owned mock entry`);
      const mockEntry = readFileSync(
        resolve(process.cwd(), `src/features/${feature}/mock.ts`),
        "utf8",
      );
      assert.ok(mockEntry.includes(factory), `${factory} must exist in ${feature}/mock.ts`);
    }
    assert.match(row, /已有|尚未|仍未|待验收/, `chapter §${chapter} must state backend status`);
  }
  assert.deepEqual(
    [...documentedChapters].sort((left, right) => left - right),
    [...expected.keys()],
  );

  const accountMock = readFileSync(
    resolve(process.cwd(), "src/features/identity/fixtures/accountManagementMockHandlers.ts"),
    "utf8",
  );
  assert.match(accountMock, /\/api\/v1\/auth\/password/);
});

test("F6.1/F7.4: shared design summary defers to current endpoint wire contracts", () => {
  const pageDesign = readFileSync(
    resolve(process.cwd(), "../docs/design/页面能力与接口设计.md"),
    "utf8",
  );
  const commonStart = pageDesign.indexOf("## 1. 共同边界与数据约束");
  const pageStart = pageDesign.indexOf("## 2. 总览", commonStart);
  assert.ok(commonStart >= 0 && pageStart > commonStart);
  const common = pageDesign.slice(commonStart, pageStart);

  assert.match(common, /不再假设存在统一的 `ObservationQuery` wire 类型/);
  assert.match(common, /`environmentId\/appId\/instanceId\/resource\/scope\/window\{from,to\}`/);
  assert.match(common, /错误 wire 使用 `ConsoleErrorSchema`/);
  assert.match(common, /字段问题是 `\{field,reason\}`/);
  assert.match(common, /`ApiResult<T>` 不是 Console wire envelope/);
  assert.match(common, /`409 idempotency_conflict`/);
  assert.match(common, /`403 bootstrap_unauthorized`/);
  assert.match(common, /账户 last-admin.*通过账号 command observation 的 `rejected.reason`/);
  assert.match(common, /SSE\/EventSource 没有纳入现行 Console runtime operations/);
  assert.doesNotMatch(common, /现有 `\/rules\/publish`/);
  assert.doesNotMatch(common, /409 冲突\/重复初始化\/最后管理员/);
  assert.doesNotMatch(
    pageDesign,
    /内部失败码及最终 HTTP 形状在 F6 固化|字段级服务端问题投影在 F6 冻结 wire 时落实/,
  );
  assert.match(
    pageDesign,
    /`410 target_retired` 由 instance HTTP adapter 映射为本地 `instance_incarnation_changed`/,
  );
  assert.match(pageDesign, /身份需求的历史草案，非规范 API/);
  assert.equal(CONSOLE_OPERATIONS.length, 68);
  assert.equal(CONSOLE_ERROR_STATUS.bootstrap_unauthorized, 403);
  assert.equal(CONSOLE_ERROR_STATUS.idempotency_conflict, 409);
});

test("F7.4: setup and login chapters document current runtime input bounds", () => {
  const pageDesign = readFileSync(
    resolve(process.cwd(), "../docs/design/页面能力与接口设计.md"),
    "utf8",
  );
  const pageChapter = (chapterNumber) => {
    const headings = [...pageDesign.matchAll(/^## (\d+)\./gm)];
    const index = headings.findIndex((heading) => Number(heading[1]) === chapterNumber);
    assert.notEqual(index, -1, `page chapter ${chapterNumber} must exist`);
    return pageDesign.slice(headings[index].index, headings[index + 1]?.index ?? pageDesign.length);
  };
  const openApi = createConsoleOpenApi();
  const cases = [
    ["authorizeBootstrap", ["operatorCode"], { maxLength: 1024 }, 8],
    ["login", ["username"], { minLength: 1, maxLength: 200 }, 9],
    ["login", ["password"], { minLength: 1, maxLength: 1024 }, 9],
    ["checkBootstrapDatabase", ["host"], { minLength: 1, maxLength: 253 }, 8],
    ["checkBootstrapDatabase", ["port"], { minimum: 1, maximum: 65535 }, 8],
    ["checkBootstrapDatabase", ["database"], { minLength: 1, maxLength: 200 }, 8],
    ["checkBootstrapDatabase", ["username"], { minLength: 1, maxLength: 200 }, 8],
    ["checkBootstrapDatabase", ["password"], { minLength: 1, maxLength: 1024 }, 8],
    ["checkBootstrapSource", ["endpoint"], { maxLength: 2048 }, 8],
    ["checkBootstrapSource", ["namespace"], { maxLength: 200 }, 8],
    ["checkBootstrapSource", ["datacenter"], { maxLength: 200 }, 8],
    ["checkBootstrapSource", ["authentication", "reference"], { minLength: 1, maxLength: 512 }, 8],
    ["checkBootstrapSource", ["authentication", "username"], { minLength: 1, maxLength: 200 }, 8],
    ["checkBootstrapSource", ["authentication", "password"], { minLength: 1, maxLength: 1024 }, 8],
    ["checkBootstrapSource", ["authentication", "aclToken"], { minLength: 1, maxLength: 1024 }, 8],
    ["initializeConsole", ["input", "admin", "username"], { minLength: 1, maxLength: 200 }, 8],
    ["initializeConsole", ["input", "admin", "password"], { minLength: 8, maxLength: 32 }, 8],
  ];

  for (const [operationId, path, expectedBounds, chapterNumber] of cases) {
    const operation = CONSOLE_OPERATIONS.find((candidate) => candidate.operationId === operationId);
    assert.ok(operation, `runtime operation ${operationId} must exist`);
    const endpoint = operation.endpoint.url;
    const route = openApi.paths[endpoint.path][endpoint.method.toLowerCase()];
    const schema = route.requestBody?.content?.["application/json"]?.schema;
    const fieldSchema = schemaAtPath(schema, path, openApi);
    assert.ok(fieldSchema, `${operationId} schema must contain ${path.join(".")}`);
    for (const [keyword, value] of Object.entries(expectedBounds)) {
      assert.equal(
        fieldSchema[keyword],
        value,
        `${operationId} ${path.join(".")} ${keyword} must match runtime schema`,
      );
      const chapter = pageChapter(chapterNumber);
      assert.ok(
        chapter.includes(path.at(-1)) && chapter.includes(String(value)),
        `page chapter ${chapterNumber} must document ${path.join(".")} ${keyword}=${value}`,
      );
    }
  }
});

test("F7.4: rules chapter documents current target, candidate, and plan bounds", () => {
  const pageDesign = readFileSync(
    resolve(process.cwd(), "../docs/design/页面能力与接口设计.md"),
    "utf8",
  );
  const rulesPage = pageChapter(pageDesign, "## 4. 规则", "## 5.");
  const openApi = createConsoleOpenApi();
  const cases = [
    ["createRuleBinding", ["target", "namespace"], "maxLength", 512],
    ["createRuleBinding", ["target", "group"], "maxLength", 512],
    ["createRuleBinding", ["target", "dataId"], "maxLength", 512],
    ["createRuleBinding", ["target", "datacenter"], "maxLength", 512],
    ["createRuleBinding", ["target", "key"], "maxLength", 512],
    ["mutateRuleSet", ["mutation", "candidate", "rules"], "maxItems", 1000],
    [
      "mutateRuleSet",
      ["mutation", "candidate", "rules", "[]", "rule", "value", "resource"],
      "maxLength",
      512,
    ],
    [
      "mutateRuleSet",
      ["mutation", "candidate", "rules", "[]", "rule", "value", "refResource"],
      "maxLength",
      512,
    ],
    [
      "mutateRuleSet",
      ["mutation", "candidate", "rules", "[]", "rule", "value", "paramFlowItemList"],
      "maxItems",
      100,
    ],
    [
      "mutateRuleSet",
      [
        "mutation",
        "candidate",
        "rules",
        "[]",
        "rule",
        "value",
        "paramFlowItemList",
        "[]",
        "classType",
      ],
      "maxLength",
      512,
    ],
    [
      "mutateRuleSet",
      [
        "mutation",
        "candidate",
        "rules",
        "[]",
        "rule",
        "value",
        "paramFlowItemList",
        "[]",
        "object",
      ],
      "maxLength",
      512,
    ],
    ["mutateRuleSet", ["mutation", "note"], "maxLength", 2000],
    ["mutateRuleSet", ["mutation", "reason"], "maxLength", 2000],
    ["mutateRuleSet", ["mutation", "schedule", "timeZone"], "maxLength", 128],
  ];

  for (const [operationId, path, keyword, expectedValue] of cases) {
    const operation = CONSOLE_OPERATIONS.find((candidate) => candidate.operationId === operationId);
    assert.ok(operation, `runtime operation ${operationId} must exist`);
    const endpoint = operation.endpoint.url;
    const route = openApi.paths[endpoint.path][endpoint.method.toLowerCase()];
    const schema = route.requestBody?.content?.["application/json"]?.schema;
    const fieldSchema = schemaAtPath(schema, path, openApi);
    assert.ok(fieldSchema, `${operationId} schema must contain ${path.join(".")}`);
    assert.ok(
      schemaContainsConstraint(fieldSchema, keyword, expectedValue, openApi),
      `${operationId} ${path.join(".")} ${keyword} must match runtime schema`,
    );
    assert.ok(
      rulesPage.includes(path.at(-1)) && rulesPage.includes(String(expectedValue)),
      `rule chapter must document ${path.join(".")} ${keyword}=${expectedValue}`,
    );
  }
});

test("F7.4: observation page chapters document current runtime query bounds", () => {
  const pageDesign = readFileSync(
    resolve(process.cwd(), "../docs/design/页面能力与接口设计.md"),
    "utf8",
  );
  const openApi = createConsoleOpenApi();
  const cases = [
    ["readFleet", "environmentId", "maxLength", 200, 2],
    ["readFleet", "appId", "maxLength", 200, 2],
    ["readFleet", "page", "minimum", 1, 2],
    ["readFleet", "page", "maximum", 1_000_000, 2],
    ["readFleet", "pageSize", "minimum", 1, 2],
    ["readFleet", "pageSize", "maximum", 100, 2],
    ["readFleet", "search", "maxLength", 200, 2],
    ["readFleet", "stepMs", "minimum", 1, 2],
    ["readFleet", "stepMs", "maximum", 604_800_000, 2],
    ["readInstanceCatalog", "environmentId", "maxLength", 200, 3],
    ["readInstanceCatalog", "appId", "maxLength", 200, 3],
    ["readInstanceCatalog", "page", "minimum", 1, 3],
    ["readInstanceCatalog", "page", "maximum", 1_000_000, 3],
    ["readInstanceCatalog", "pageSize", "minimum", 1, 3],
    ["readInstanceCatalog", "pageSize", "maximum", 100, 3],
    ["readInstanceCatalog", "search", "maxLength", 200, 3],
    ["readInstanceObservation", "instanceId", "maxLength", 200, 3],
    ["readInstanceObservation", "resource", "maxLength", 200, 3],
    ["readInstanceObservation", "processEpoch", "maxLength", 200, 3],
    ["readInstanceObservation", "stepMs", "maximum", 604_800_000, 3],
    ["readMetrics", "environmentId", "maxLength", 200, 5],
    ["readMetrics", "appId", "maxLength", 200, 5],
    ["readMetrics", "instanceId", "maxLength", 200, 5],
    ["readMetrics", "resource", "maxLength", 200, 5],
    ["readMetrics", "metrics", "minLength", 1, 5],
    ["readMetrics", "metrics", "maxLength", 89, 5],
    ["readMetrics", "stepMs", "maximum", 604_800_000, 5],
    ["readIncidentTimeline", "environmentId", "maxLength", 200, 6],
    ["readIncidentTimeline", "appId", "maxLength", 200, 6],
    ["readIncidentTimeline", "instanceId", "maxLength", 200, 6],
    ["readIncidentTimeline", "pageSize", "minimum", 1, 6],
    ["readIncidentTimeline", "pageSize", "maximum", 100, 6],
    ["readIncidentTimeline", "cursor", "minLength", 1, 6],
    ["readIncidentTimeline", "cursor", "maxLength", 512, 6],
    ["readIncidentEvidence", "incidentId", "maxLength", 200, 6],
  ];

  for (const [operationId, parameterName, keyword, expectedValue, chapterNumber] of cases) {
    const operation = CONSOLE_OPERATIONS.find((candidate) => candidate.operationId === operationId);
    assert.ok(operation, `runtime operation ${operationId} must exist`);
    const endpoint = operation.endpoint.url;
    const route = openApi.paths[endpoint.path][endpoint.method.toLowerCase()];
    const parameter = route.parameters.find((candidate) => candidate.name === parameterName);
    assert.ok(parameter, `${operationId} must expose query parameter ${parameterName}`);
    assert.ok(
      schemaContainsConstraint(parameter.schema, keyword, expectedValue, openApi),
      `${operationId} ${parameterName} ${keyword} must match runtime schema`,
    );
    const chapter = pageChapter(pageDesign, `## ${chapterNumber}.`, `## ${chapterNumber + 1}.`);
    assert.ok(
      chapter.includes(parameterName) && chapter.includes(String(expectedValue)),
      `page chapter ${chapterNumber} must document ${parameterName} ${keyword}=${expectedValue}`,
    );
  }
});

test("F7.4: rules chapter separates JSON number bounds from per-rule validation", () => {
  const pageDesign = readFileSync(
    resolve(process.cwd(), "../docs/design/页面能力与接口设计.md"),
    "utf8",
  );
  const rulesPage = pageChapter(pageDesign, "## 4. 规则", "## 5.");
  const openApi = createConsoleOpenApi();
  const operation = CONSOLE_OPERATIONS.find(
    (candidate) => candidate.operationId === "mutateRuleSet",
  );
  assert.ok(operation, "runtime operation mutateRuleSet must exist");
  const endpoint = operation.endpoint.url;
  const route = openApi.paths[endpoint.path][endpoint.method.toLowerCase()];
  const schema = route.requestBody?.content?.["application/json"]?.schema;
  assert.ok(schema, "mutateRuleSet must expose its JSON request schema");
  const numericField = schemaAtPath(
    schema,
    ["mutation", "candidate", "rules", "[]", "rule", "value", "grade"],
    openApi,
  );
  assert.ok(numericField, "rule value grade must exist in the runtime request schema");

  for (const [keyword, value] of [
    ["minimum", -Number.MAX_SAFE_INTEGER],
    ["maximum", Number.MAX_SAFE_INTEGER],
  ]) {
    assert.ok(
      schemaContainsConstraint(numericField, keyword, value, openApi),
      `rule value ${keyword} must match generated OpenAPI safe-number boundary`,
    );
    assert.ok(
      rulesPage.includes(String(Number.MAX_SAFE_INTEGER)),
      "rule chapter must document the JSON number boundary",
    );
  }
  assert.match(rulesPage, /整数性、正数\/非负范围、ratio 与禁用哨兵仍按第 4\.3 节逐类型校验/);
});

function documentedSchemaFields(schema, document, visitedReferences = new Set()) {
  if (!schema || typeof schema !== "object") return [];
  const fields = [];
  if (typeof schema.$ref === "string") {
    const reference = schema.$ref;
    if (!reference.startsWith("#/"))
      throw new Error(`Unsupported non-local OpenAPI schema reference: ${reference}`);
    if (!visitedReferences.has(reference)) {
      const target = reference
        .slice(2)
        .split("/")
        .map((part) => part.replaceAll("~1", "/").replaceAll("~0", "~"))
        .reduce((value, part) => value?.[part], document);
      if (!target || typeof target !== "object")
        throw new Error(`Unresolved OpenAPI schema reference: ${reference}`);
      fields.push(
        ...documentedSchemaFields(target, document, new Set([...visitedReferences, reference])),
      );
    }
  }
  for (const [field, childSchema] of Object.entries(schema.properties ?? {})) {
    fields.push(field, ...documentedSchemaFields(childSchema, document, visitedReferences));
  }
  if (schema.items)
    fields.push(...documentedSchemaFields(schema.items, document, visitedReferences));
  for (const variant of [
    ...(schema.oneOf ?? []),
    ...(schema.anyOf ?? []),
    ...(schema.allOf ?? []),
  ]) {
    fields.push(...documentedSchemaFields(variant, document, visitedReferences));
  }
  return [...new Set(fields)];
}

function documentedSchemaBounds(schema, document, visitedReferences = new Set(), property) {
  if (!schema || typeof schema !== "object") return [];
  const bounds = [];
  const boundKeywords = ["minLength", "maxLength", "minimum", "maximum", "minItems", "maxItems"];
  if (typeof schema.$ref === "string") {
    const reference = schema.$ref;
    if (!reference.startsWith("#/"))
      throw new Error(`Unsupported non-local OpenAPI schema reference: ${reference}`);
    if (!visitedReferences.has(reference)) {
      const target = reference
        .slice(2)
        .split("/")
        .map((part) => part.replaceAll("~1", "/").replaceAll("~0", "~"))
        .reduce((value, part) => value?.[part], document);
      if (!target || typeof target !== "object")
        throw new Error(`Unresolved OpenAPI schema reference: ${reference}`);
      bounds.push(
        ...documentedSchemaBounds(
          target,
          document,
          new Set([...visitedReferences, reference]),
          property,
        ),
      );
    }
  }
  if (property) {
    for (const keyword of boundKeywords) {
      if (schema[keyword] !== undefined) bounds.push({ property, keyword, value: schema[keyword] });
    }
  }
  for (const [field, childSchema] of Object.entries(schema.properties ?? {})) {
    bounds.push(...documentedSchemaBounds(childSchema, document, visitedReferences, field));
  }
  if (schema.items)
    bounds.push(...documentedSchemaBounds(schema.items, document, visitedReferences, property));
  for (const variant of [
    ...(schema.oneOf ?? []),
    ...(schema.anyOf ?? []),
    ...(schema.allOf ?? []),
  ]) {
    bounds.push(...documentedSchemaBounds(variant, document, visitedReferences, property));
  }
  const uniqueBounds = new Map(
    bounds.map((bound) => [`${bound.property}:${bound.keyword}:${bound.value}`, bound]),
  );
  return [...uniqueBounds.values()];
}

function documentedSchemaEnumValues(
  schema,
  document,
  visitedReferences = new Set(),
  includeProperty,
  propertyName,
) {
  if (!schema || typeof schema !== "object") return [];
  const values = [];
  if (typeof schema.$ref === "string") {
    const reference = schema.$ref;
    if (!reference.startsWith("#/"))
      throw new Error(`Unsupported non-local OpenAPI schema reference: ${reference}`);
    if (!visitedReferences.has(reference)) {
      const target = reference
        .slice(2)
        .split("/")
        .map((part) => part.replaceAll("~1", "/").replaceAll("~0", "~"))
        .reduce((value, part) => value?.[part], document);
      if (!target || typeof target !== "object")
        throw new Error(`Unresolved OpenAPI schema reference: ${reference}`);
      values.push(
        ...documentedSchemaEnumValues(
          target,
          document,
          new Set([...visitedReferences, reference]),
          includeProperty,
          propertyName,
        ),
      );
    }
  }
  if (
    (!includeProperty || !propertyName || includeProperty(propertyName)) &&
    ["string", "number", "boolean"].includes(typeof schema.const)
  ) {
    values.push(String(schema.const));
  }
  for (const value of !includeProperty || !propertyName || includeProperty(propertyName)
    ? (schema.enum ?? [])
    : []) {
    if (["string", "number", "boolean"].includes(typeof value)) values.push(String(value));
  }
  for (const [property, childSchema] of Object.entries(schema.properties ?? {}))
    values.push(
      ...documentedSchemaEnumValues(
        childSchema,
        document,
        visitedReferences,
        includeProperty,
        property,
      ),
    );
  if (schema.items)
    values.push(
      ...documentedSchemaEnumValues(
        schema.items,
        document,
        visitedReferences,
        includeProperty,
        propertyName,
      ),
    );
  for (const variant of [
    ...(schema.oneOf ?? []),
    ...(schema.anyOf ?? []),
    ...(schema.allOf ?? []),
  ]) {
    values.push(
      ...documentedSchemaEnumValues(
        variant,
        document,
        visitedReferences,
        includeProperty,
        propertyName,
      ),
    );
  }
  return [...new Set(values)];
}

test("F7.4: input wire-value collector includes const, enum, and local references", () => {
  const document = {
    components: {
      schemas: {
        Command: {
          type: "object",
          properties: {
            kind: { const: "save_draft" },
            state: { enum: ["pending", "complete"] },
            input: { $ref: "#/components/schemas/Input" },
          },
        },
        Input: {
          type: "object",
          properties: {
            enabled: { const: false },
            mode: { enum: ["open", "closed"] },
          },
        },
      },
    },
  };

  assert.deepEqual(
    documentedSchemaEnumValues({ $ref: "#/components/schemas/Command" }, document).sort(),
    ["closed", "complete", "false", "open", "pending", "save_draft"].sort(),
  );
});

test("F7.4: schema field collector resolves local JSON Pointer references", () => {
  const document = {
    components: {
      schemas: {
        "Nested/Record": {
          type: "object",
          properties: {
            recordId: { type: "string" },
            facts: {
              type: "array",
              items: { $ref: "#/components/schemas/Fact" },
            },
          },
        },
        Fact: {
          type: "object",
          properties: { occurredAt: { type: "string" } },
        },
      },
    },
  };
  assert.deepEqual(
    documentedSchemaFields({ $ref: "#/components/schemas/Nested~1Record" }, document).sort(),
    ["facts", "occurredAt", "recordId"],
  );
  assert.throws(
    () => documentedSchemaFields({ $ref: "https://example.invalid/remote.json#/Fact" }, document),
    /Unsupported non-local OpenAPI schema reference/,
  );
  assert.throws(
    () => documentedSchemaFields({ $ref: "#/components/schemas/Missing" }, document),
    /Unresolved OpenAPI schema reference/,
  );
});

test("F7.4: role-binding chapter separates demo command state from live session authority", () => {
  const pageDesign = readFileSync(
    resolve(process.cwd(), "../docs/design/页面能力与接口设计.md"),
    "utf8",
  );
  const chapterStart = pageDesign.indexOf("## 11. 角色绑定");
  const chapterEnd = pageDesign.indexOf("## 12. 修改密码", chapterStart);
  assert.ok(chapterStart >= 0 && chapterEnd > chapterStart, "role-binding chapter exists");
  const chapter = pageDesign.slice(chapterStart, chapterEnd);
  assert.match(chapter, /显式 demo profile.*HTTP Mock/i);
  assert.match(chapter, /Mock assembly 内.*不是数据库持久化/);
  assert.match(chapter, /不能证明.*(?:会话|session|权限|Python)/i);
});

test("F7.4: overview page documents every runtime fleet error projection", () => {
  const pageDesign = readFileSync(
    resolve(process.cwd(), "../docs/design/页面能力与接口设计.md"),
    "utf8",
  );
  const overviewStart = pageDesign.indexOf("## 2. 总览");
  const overviewEnd = pageDesign.indexOf("## 3.", overviewStart);
  assert.ok(overviewStart >= 0 && overviewEnd > overviewStart);
  const overview = pageDesign.slice(overviewStart, overviewEnd);

  for (const code of FLEET_ENDPOINT.errors) {
    const status = CONSOLE_ERROR_STATUS[code];
    assert.match(
      overview,
      new RegExp(`^\\| ${status} \\| \`${code}\` \\|`, "m"),
      `overview documentation must describe ${status} ${code}`,
    );
  }
  assert.match(overview, /要求有效会话及 `metrics:view`/);
  assert.match(overview, /Live 模式不得在失败时回退到 Mock/);
});

test("F7.4: application page documents observation endpoint errors and retired incarnations", () => {
  const pageDesign = readFileSync(
    resolve(process.cwd(), "../docs/design/页面能力与接口设计.md"),
    "utf8",
  );
  const applicationsStart = pageDesign.indexOf("## 3. 应用与实例");
  const applicationsEnd = pageDesign.indexOf("## 4.", applicationsStart);
  assert.ok(applicationsStart >= 0 && applicationsEnd > applicationsStart);
  const applications = pageDesign.slice(applicationsStart, applicationsEnd);
  const endpoints = [
    ["readObservationCatalog", OBSERVATION_CATALOG_ENDPOINT],
    ["readInstanceCatalog", INSTANCE_ENDPOINTS.Catalog],
    ["readInstanceObservation", INSTANCE_ENDPOINTS.Detail],
  ];

  for (const [operationId, endpoint] of endpoints) {
    for (const code of endpoint.errors) {
      const status = CONSOLE_ERROR_STATUS[code];
      assert.match(
        applications,
        new RegExp(`^\\| \`${operationId}\` \\| ${status} \\| \`${code}\` \\|`, "m"),
        `${operationId} documentation must describe ${status} ${code}`,
      );
    }
  }
  assert.match(
    applications,
    /\| 410 \| `target_retired` \|[\s\S]*?`409 instance_incarnation_changed`/,
  );
  assert.match(applications, /由用户重新选择，不自动切到别的实例/);
  assert.match(applications, /Live 模式不得回退至合成 Mock/);
});

test("F7.4: realtime page documents every metrics endpoint error and authority semantics", () => {
  const pageDesign = readFileSync(
    resolve(process.cwd(), "../docs/design/页面能力与接口设计.md"),
    "utf8",
  );
  const realtimeStart = pageDesign.indexOf("## 5. 实时监控");
  const realtimeEnd = pageDesign.indexOf("## 6.", realtimeStart);
  assert.ok(realtimeStart >= 0 && realtimeEnd > realtimeStart);
  const realtime = pageDesign.slice(realtimeStart, realtimeEnd);

  for (const code of METRICS_ENDPOINT.errors) {
    const status = CONSOLE_ERROR_STATUS[code];
    assert.match(
      realtime,
      new RegExp("^\\| " + status + " \\| `" + code + "` \\|", "m"),
      `realtime page must describe ${status} ${code}`,
    );
  }
  assert.match(realtime, /有效会话及 `metrics:view`/);
  assert.match(realtime, /\| 410 \| `target_retired` \|[\s\S]*?由用户显式重选活动实例/);
  assert.match(realtime, /`retryAfterMs`[\s\S]*?按单调时钟记录最早下一次读取时刻/);
  assert.match(realtime, /暂停\/恢复不会绕过尚未到期的服务端等待时间/);
  assert.match(realtime, /指标权限撤销与 incarnation 退役属于权威状态/);
});

test("F7.4: incident page documents every endpoint error and non-disclosing recovery", () => {
  const pageDesign = readFileSync(
    resolve(process.cwd(), "../docs/design/页面能力与接口设计.md"),
    "utf8",
  );
  const faultsStart = pageDesign.indexOf("## 6. 故障分析");
  const faultsEnd = pageDesign.indexOf("## 7.", faultsStart);
  assert.ok(faultsStart >= 0 && faultsEnd > faultsStart);
  const faults = pageDesign.slice(faultsStart, faultsEnd);
  const endpoints = [
    ["readIncidentTimeline", INCIDENT_ENDPOINTS.Timeline],
    ["readIncidentEvidence", INCIDENT_ENDPOINTS.Evidence],
  ];

  for (const [operationId, endpoint] of endpoints) {
    for (const code of endpoint.errors) {
      const status = CONSOLE_ERROR_STATUS[code];
      assert.match(
        faults,
        new RegExp("^\\| `" + operationId + "` \\| " + status + " \\| `" + code + "` \\|", "m"),
        `${operationId} documentation must describe ${status} ${code}`,
      );
    }
  }
  assert.match(faults, /逐请求要求有效会话和 `metrics:view`/);
  assert.match(faults, /不自动选时间线首条事件/);
  assert.match(faults, /共享查询反馈组件在到期前禁用人工刷新，到期后恢复/);
  assert.match(faults, /404、权限撤销和身份变化清除相应缓存/);
});

test("F7.4: rules page documents every runtime error and async command outcome", () => {
  const pageDesign = readFileSync(
    resolve(process.cwd(), "../docs/design/页面能力与接口设计.md"),
    "utf8",
  );
  const rulesStart = pageDesign.indexOf("## 4. 规则");
  const rulesEnd = pageDesign.indexOf("## 5.", rulesStart);
  assert.ok(rulesStart >= 0 && rulesEnd > rulesStart);
  const rules = pageDesign.slice(rulesStart, rulesEnd);
  const errors = new Set(RULE_SET_HTTP_CONTRACT.flatMap((operation) => operation.endpoint.errors));

  for (const code of errors) {
    assert.ok(rules.includes(`\`${code}\``), `rules page must describe ${code}`);
  }
  assert.match(rules, /HTTP 202 表示服务端已接受/);
  assert.match(rules, /`rejected\/conflict` 是已接受命令的业务回执，不是 HTTP 409/);
  assert.match(rules, /操作查询 body 的 `status: "not-found"` 是 HTTP 200/);
  assert.match(rules, /始终用原 requestKey 核查/);
});

test("F6.1: rules chapter keeps read-back mismatch in publication reason, not stage state", () => {
  const pageDesign = readFileSync(
    resolve(process.cwd(), "../docs/design/页面能力与接口设计.md"),
    "utf8",
  );
  const rules = pageChapter(pageDesign, "## 4. 规则", "## 5.");
  const publicationStates = [...rules.matchAll(/发布阶段 `([^`]+)`/g)].map((match) => match[1]);

  assert.deepEqual(publicationStates, [Object.values(PUBLICATION_STAGE).join("|")]);
  assert.match(rules, /`readback_mismatch` 是发布阶段的失败原因，不是阶段状态/);
  assert.ok(Object.values(PUBLICATION_REASON).includes("readback_mismatch"));
});

test("F7.4: rules page documents current local draft validation separately from server capability checks", () => {
  const pageDesign = readFileSync(
    resolve(process.cwd(), "../docs/design/页面能力与接口设计.md"),
    "utf8",
  );
  const rules = pageChapter(pageDesign, "## 4. 规则", "## 5.");
  assert.match(rules, /`validateRuleDraft` 当前执行的本地编辑校验/);
  assert.match(rules, /不是 Sentinel 运行时\/codec 支持声明/);
  assert.match(
    rules,
    /Flow \|[\s\S]*?线程数模式另要求整数[\s\S]*?窗口毫秒数不得小于样本数并须整除样本数/,
  );
  assert.match(rules, /Degrade \|[\s\S]*?错误比例模式要求不大于 1[\s\S]*?范围为 `\(0,1\]`/);
  assert.match(rules, /System \|[\s\S]*?禁用为 `-1`[\s\S]*?`highestCpuUsage` 限于 `\[0,1\]`/);
  assert.match(rules, /Authority \|[\s\S]*?按逗号分隔后 trim[\s\S]*?非空且去重/);
  assert.match(
    rules,
    /ParamFlow \|[\s\S]*?`paramIdx` 为非负整数[\s\S]*?按 trim 后 classType 与 object 组合去重/,
  );
});

test("F7.4: system page documents endpoint error matrices and rate-limit recovery", () => {
  const pageDesign = readFileSync(
    resolve(process.cwd(), "../docs/design/页面能力与接口设计.md"),
    "utf8",
  );
  const systemStart = pageDesign.indexOf("## 7. 系统管理");
  const systemEnd = pageDesign.indexOf("## 8.", systemStart);
  assert.ok(systemStart >= 0 && systemEnd > systemStart);
  const system = pageDesign.slice(systemStart, systemEnd);
  const endpoints = [
    ["readSystemConnections", SYSTEM_OBSERVATION_ENDPOINTS.Connections],
    ["readSystemProtocols", SYSTEM_OBSERVATION_ENDPOINTS.Protocols],
    ["readAgentReportingProtocolObservations", SYSTEM_OBSERVATION_ENDPOINTS.AgentReporting],
    ["readIncidentEventProtocolObservations", SYSTEM_OBSERVATION_ENDPOINTS.IncidentEvents],
    ["readSystemAudit", SYSTEM_OBSERVATION_ENDPOINTS.Audit],
    ["readRegisteredSources", SOURCE_REGISTRATION_ENDPOINTS.Registry],
    ["checkRegisteredSource", SOURCE_REGISTRATION_ENDPOINTS.Check],
    ["mutateRegisteredSource", SOURCE_REGISTRATION_ENDPOINTS.Command],
    ["readRegisteredSourceOperation", SOURCE_REGISTRATION_ENDPOINTS.Operation],
  ];

  for (const [operationId, endpoint] of endpoints) {
    const row = system.split("\n").find((line) => line.startsWith(`| \`${operationId}\` |`));
    assert.ok(row, `${operationId} must have a dedicated failure-matrix row`);
    for (const code of endpoint.errors) {
      assert.ok(
        row.includes(`${CONSOLE_ERROR_STATUS[code]} ${code}`),
        `${operationId} must document ${code}`,
      );
    }
  }
  assert.match(system, /`429 rate_limited`/);
  assert.match(system, /按钮在期限内禁用，不自动重放/);
  assert.match(system, /编辑字段或清除\/失效旧检查结果不得缩短仍有效的等待期/);
  assert.match(system, /`status: "not_found"` 仍是 HTTP 200 观察结果/);
  assert.match(system, /`503` 只对读模型保留带原 `asOf` 的 stale 事实/);
  assert.ok(system.includes("来源检查的 `status` 为 `reachable|unreachable`"));
  assert.ok(system.includes("失败原因 `reason: connection|authentication|unsupported`"));
});

test("F7.4: setup page documents each bootstrap operation error matrix", () => {
  const pageDesign = readFileSync(
    resolve(process.cwd(), "../docs/design/页面能力与接口设计.md"),
    "utf8",
  );
  const page = pageChapter(pageDesign, "## 8. 首次初始化", "## 9.");
  assertOperationErrorRows(page, [
    ["readBootstrap", IDENTITY_ENDPOINTS.Bootstrap],
    ["authorizeBootstrap", IDENTITY_ENDPOINTS.AuthorizeBootstrap],
    ["checkBootstrapDatabase", IDENTITY_ENDPOINTS.CheckDatabase],
    ["checkBootstrapSource", IDENTITY_ENDPOINTS.CheckSource],
    ["initializeConsole", IDENTITY_ENDPOINTS.Initialize],
    ["readInitialization", IDENTITY_ENDPOINTS.Initialization],
  ]);
  assert.match(page, /`status: "not-found"` 是 HTTP 200 观察/);
  assert.match(page, /后续初始化请求以 `403 bootstrap_unauthorized` 拒绝/);
  assert.match(page, /`409 idempotency_conflict` 仅用于 requestKey\/Idempotency-Key 不匹配或冲突/);
});

test("F7.4: login page documents bootstrap, session, login and logout error matrices", () => {
  const pageDesign = readFileSync(
    resolve(process.cwd(), "../docs/design/页面能力与接口设计.md"),
    "utf8",
  );
  const page = pageChapter(pageDesign, "## 9. 登录", "## 10.");
  assertOperationErrorRows(page, [
    ["readBootstrap", IDENTITY_ENDPOINTS.Bootstrap],
    ["readSession", IDENTITY_ENDPOINTS.Session],
    ["login", IDENTITY_ENDPOINTS.Login],
    ["logout", IDENTITY_ENDPOINTS.Logout],
  ]);
  assert.deepEqual(IDENTITY_ENDPOINTS.Session.errors, ["invalid_request", "service_unavailable"]);
  assert.deepEqual(
    Object.keys(createConsoleOpenApi().paths["/api/v1/auth/me"].get.responses).sort(),
    ["200", "400", "503"],
  );
  assert.match(
    page,
    /缺失、格式错误、过期或已撤销的 Cookie 返回 `200 null`，不返回 `401 unauthenticated`/,
  );
  assert.match(page, /`429` 只有在返回合法有界 `retryAfterMs` 时才禁用提交/);
});

test("F7.4: account and role pages share exact account endpoint failures", () => {
  const pageDesign = readFileSync(
    resolve(process.cwd(), "../docs/design/页面能力与接口设计.md"),
    "utf8",
  );
  const accounts = pageChapter(pageDesign, "## 10. 账户维护", "## 11.");
  const roles = pageChapter(pageDesign, "## 11. 角色绑定", "## 12.");
  const endpoints = [
    ["listAccounts", ACCOUNT_ENDPOINTS.List],
    ["readAccount", ACCOUNT_ENDPOINTS.Read],
    ["mutateAccount", ACCOUNT_ENDPOINTS.Command],
    ["readAccountOperation", ACCOUNT_ENDPOINTS.Operation],
  ];
  assertOperationErrorRows(accounts, endpoints);
  assert.match(roles, /复用 §10 的账号 endpoint 与错误矩阵/);
  assert.match(accounts, /账号业务拒绝[\s\S]*?HTTP 200 命令观察/);
});

test("F7.4: every page chapter documents its runtime role and capability requirements", () => {
  const pageDesign = readFileSync(
    resolve(process.cwd(), "../docs/design/页面能力与接口设计.md"),
    "utf8",
  );
  const mappingStart = pageDesign.indexOf("### 13.1 页面动作到当前 machine operations 的映射");
  const mappingEnd = pageDesign.indexOf("### 13.1.1", mappingStart);
  assert.ok(mappingStart >= 0 && mappingEnd > mappingStart, "page operation mapping exists");
  const ownersByOperation = new Map();
  const mappingRows = pageDesign
    .slice(mappingStart, mappingEnd)
    .split("\n")
    .filter((line) => line.startsWith("| §"));
  for (const line of mappingRows) {
    const cells = line.split("|");
    const chapterNumbers = [...cells[1].matchAll(/§(\d+)/g)].map((match) => Number(match[1]));
    const operationIds = [...cells[2].matchAll(/`([a-z][A-Za-z0-9]*)`/g)].map((match) => match[1]);
    for (const operationId of operationIds) {
      ownersByOperation.set(operationId, chapterNumbers);
    }
  }

  for (const operation of CONSOLE_OPERATIONS) {
    const ownerChapters = ownersByOperation.get(operation.operationId);
    assert.ok(ownerChapters?.length, `${operation.operationId} needs a page owner`);
    const ownerText = ownerChapters
      .map((chapterNumber) => {
        const heading = `## ${chapterNumber}. `;
        const chapterStart = pageDesign.indexOf(heading);
        assert.ok(chapterStart >= 0, `page chapter ${chapterNumber} exists`);
        const nextHeading = pageDesign.indexOf(`\n## ${chapterNumber + 1}. `, chapterStart);
        return pageDesign.slice(chapterStart, nextHeading < 0 ? undefined : nextHeading);
      })
      .join("\n");
    const { role, capabilities } = operation.requiredAccess;
    if (role !== null) {
      assert.match(
        ownerText,
        /\badmin\b|管理员/i,
        `${operation.operationId} requires documented admin authorization`,
      );
    }
    for (const capability of capabilities) {
      assert.ok(
        ownerText.includes(`\`${capability}\``),
        `${operation.operationId} requires documented ${capability} authorization`,
      );
    }
  }
});

test("F7.4: own-password page documents every runtime error and safe recovery", () => {
  const pageDesign = readFileSync(
    resolve(process.cwd(), "../docs/design/页面能力与接口设计.md"),
    "utf8",
  );
  const page = pageChapter(pageDesign, "## 12. 修改密码", null);
  assert.deepEqual(OWN_PASSWORD_ENDPOINT.errors, [
    "invalid_request",
    "current_password_invalid",
    "unauthenticated",
    "csrf_failed",
    "validation_failed",
    "rate_limited",
    "service_unavailable",
  ]);
  assert.equal(OWN_PASSWORD_ENDPOINT.idempotency, "none");
  assert.equal(OWN_PASSWORD_ENDPOINT.errors.includes("conflict"), false);
  assertOperationErrorRows(page, [["changeOwnPassword", OWN_PASSWORD_ENDPOINT]]);
  assert.match(page, /`429` 尊重有界 `retryAfterMs`，期限内禁用人工提交，不自动重发/);
  assert.match(page, /`503`，[\s\S]*?不以页面错误推断变更未提交/);
  assert.match(page, /当前改密合同不定义 `409 conflict`/);
});

function pageChapter(document, startHeading, endHeading) {
  const start = document.indexOf(startHeading);
  const end = endHeading === null ? document.length : document.indexOf(endHeading, start);
  assert.ok(start >= 0 && end > start, `${startHeading} chapter exists`);
  return document.slice(start, end);
}

function schemaAtPath(schema, path, document, visitedReferences = new Set()) {
  if (!schema || typeof schema !== "object") return undefined;
  if (typeof schema.$ref === "string") {
    const reference = schema.$ref;
    if (visitedReferences.has(reference)) return undefined;
    const target = reference
      .slice(2)
      .split("/")
      .map((part) => part.replaceAll("~1", "/").replaceAll("~0", "~"))
      .reduce((value, part) => value?.[part], document);
    return schemaAtPath(target, path, document, new Set([...visitedReferences, reference]));
  }
  if (path.length === 0) return schema;
  const [property, ...remaining] = path;
  if (property === "[]") return schemaAtPath(schema.items, remaining, document, visitedReferences);
  const direct = schema.properties?.[property];
  if (direct) return schemaAtPath(direct, remaining, document, visitedReferences);
  for (const keyword of ["allOf", "anyOf", "oneOf"]) {
    for (const alternative of schema[keyword] ?? []) {
      const found = schemaAtPath(alternative, path, document, visitedReferences);
      if (found) return found;
    }
  }
  return undefined;
}

function schemaContainsConstraint(
  schema,
  keyword,
  expectedValue,
  document,
  visitedReferences = new Set(),
) {
  if (!schema || typeof schema !== "object") return false;
  if (schema[keyword] === expectedValue) return true;
  if (typeof schema.$ref === "string") {
    const reference = schema.$ref;
    if (visitedReferences.has(reference)) return false;
    const target = reference
      .slice(2)
      .split("/")
      .map((part) => part.replaceAll("~1", "/").replaceAll("~0", "~"))
      .reduce((value, part) => value?.[part], document);
    return schemaContainsConstraint(
      target,
      keyword,
      expectedValue,
      document,
      new Set([...visitedReferences, reference]),
    );
  }
  for (const composition of ["allOf", "anyOf", "oneOf"]) {
    if (
      (schema[composition] ?? []).some((part) =>
        schemaContainsConstraint(part, keyword, expectedValue, document, visitedReferences),
      )
    )
      return true;
  }
  return schema.items
    ? schemaContainsConstraint(schema.items, keyword, expectedValue, document, visitedReferences)
    : false;
}

function assertOperationErrorRows(page, endpoints) {
  for (const [operationId, endpoint] of endpoints) {
    const row = page.split("\n").find((line) => line.startsWith(`| \`${operationId}\` |`));
    assert.ok(row, `${operationId} must have a dedicated failure-matrix row`);
    for (const code of endpoint.errors) {
      assert.ok(
        row.includes(`${CONSOLE_ERROR_STATUS[code]} ${code}`),
        `${operationId} must document ${code}`,
      );
    }
  }
}

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
      "authorizeLocalBootstrap",
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
      "readSystemDeploymentGuides",
      "readSystemProtocols",
      "readAgentReportingProtocolObservations",
      "readIncidentEventProtocolObservations",
      "readSystemAudit",
      "readSystemSettings",
      "updateSystemTimeZone",
      "checkMonitoringSource",
      "readRegisteredSources",
      "checkRegisteredSource",
      "mutateRegisteredSource",
      "readRegisteredSourceOperation",
      "readRuleBindingScopes",
      "createRuleBinding",
      "readBindingRegistration",
      "readRuleBindings",
      "readRuleCatalog",
      "refreshRuleCatalog",
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
      "readRuleBindingObservedStates",
      "readRuleLoadObservations",
      "readRuleLoadObservationHistory",
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
    () =>
      createConsoleOpenApi([
        {
          ...CONSOLE_OPERATIONS.find((operation) => operation.pathParameters.length > 0),
          pathParameters: [],
        },
      ]),
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
