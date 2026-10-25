import { after, before, test } from "node:test";
import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { E2E_BASE_URL, connectE2EBrowser } from "./cdp.mjs";

const enabled = process.env.SENTINEL_E2E_LIVE_RULES === "1";
const adminPassword = process.env.SENTINEL_LIVE_E2E_PASSWORD;
const adminUsername = process.env.SENTINEL_LIVE_E2E_USERNAME ?? "admin";
const managedBindingId =
  process.env.SENTINEL_T07_MANAGED_BINDING_ID ?? "t07-e2e-flow-20261016-0900";
let browser;

before(async () => {
  if (enabled) browser = await connectE2EBrowser();
});

after(async () => {
  await browser?.close();
});

async function fillByLabel(page, label, value, scope = "dialog[open]") {
  const control = await page.eval(`(()=>{
    const label=[...document.querySelectorAll(${JSON.stringify(`${scope} label`)})].find(node=>node.textContent.trim()===${JSON.stringify(label)});
    const node=label?.control;
    if(!node || !(node instanceof HTMLInputElement || node instanceof HTMLTextAreaElement)) return null;
    node.focus();node.setSelectionRange(0,node.value.length);
    return {id:node.id,tag:node.tagName};
  })()`);
  assert.ok(control, `visible text control exists for label: ${label}`);
  await page.send("Input.insertText", { text: value });
  await page.waitFor(
    `(()=>{const label=[...document.querySelectorAll(${JSON.stringify(`${scope} label`)})].find(node=>node.textContent.trim()===${JSON.stringify(label)});return label?.control?.value===${JSON.stringify(value)}})()`,
    { label: `${label} accepts the synthetic test value` },
  );
}

async function selectByIndex(page, index, option) {
  await page.click('[data-ruleset-editor] [role="combobox"]', { index });
  await page.waitFor(
    `[...document.querySelectorAll('[role=option]')].some(node=>node.offsetParent&&node.textContent.trim()===${JSON.stringify(option)})`,
    { label: `rule selector exposes option ${option}` },
  );
  await page.clickByText(option, "[role=option]");
}

async function ensureAdminSession(page, origin) {
  await page.goto(`${origin}/#/login`);
  try {
    await page.waitFor(
      `!!document.querySelector('.login-page input[autocomplete="username"]') || !!document.querySelector('.app-shell')`,
      { timeoutMs: 15000, label: "login page or existing authenticated shell is ready" },
    );
  } catch (error) {
    const diagnostics = await page.eval(`({
      href:location.href,
      title:document.title,
      readyState:document.readyState,
      body:document.body?.innerText?.slice(0,1200)??"",
      root:document.querySelector("#root")?.innerHTML?.slice(0,1200)??"",
      scripts:[...document.scripts].map(script=>({src:script.src,type:script.type})),
      apiBase:document.querySelector('meta[name="console-api-base"]')?.content??null
    })`);
    throw new Error(
      `${error instanceof Error ? error.message : error}; page diagnostics=${JSON.stringify(diagnostics)}`,
    );
  }
  if (await page.eval(`localStorage.getItem("sentinel.locale") !== "zh-CN"`)) {
    await page.eval(`localStorage.setItem("sentinel.locale", "zh-CN")`);
    await page.goto(`${origin}/#/login`);
    await page.waitFor(
      `localStorage.getItem("sentinel.locale") === "zh-CN" && (!!document.querySelector('.login-page input[autocomplete="username"]') || !!document.querySelector('.app-shell'))`,
      {
        timeoutMs: 15000,
        label: "Edge page uses deterministic Chinese labels for this acceptance",
      },
    );
  }
  const identity = await page.eval(`(async()=>{
    const response=await fetch('/api/v1/auth/me',{headers:{'x-request-id':crypto.randomUUID()},cache:'no-store'});
    return {status:response.status,body:await response.json()};
  })()`);
  if (identity.status === 200 && identity.body?.roleId === "admin") return;
  assert.ok(
    adminPassword,
    "SENTINEL_LIVE_E2E_PASSWORD is required when Edge has no authenticated admin session",
  );
  await page.waitFor(`!!document.querySelector('.login-page input[autocomplete="username"]')`);
  await page.type('.login-page input[autocomplete="username"]', adminUsername);
  await page.type('.login-page input[autocomplete="current-password"]', adminPassword);
  await page.clickByText("登录", ".login-page form button");
  try {
    await page.waitFor(
      `location.hash.startsWith('#/overview') && !!document.querySelector('.app-shell')`,
      { timeoutMs: 15000, label: "Console confirms admin session before live rule operations" },
    );
  } catch (error) {
    const diagnostics = await page.eval(`(async()=>{
      const response=await fetch('/api/v1/auth/me',{headers:{'x-request-id':crypto.randomUUID()},cache:'no-store'});
      return {
        hash:location.hash,
        identityStatus:response.status,
        alerts:[...document.querySelectorAll('[role=alert],[data-login-feedback]')].map(node=>node.textContent.trim()).filter(Boolean),
        hasUsername:!!document.querySelector('.login-page input[autocomplete="username"]'),
        hasPassword:!!document.querySelector('.login-page input[autocomplete="current-password"]')
      };
    })()`);
    throw new Error(
      `${error instanceof Error ? error.message : error}; login diagnostics=${JSON.stringify(diagnostics)}`,
    );
  }
}

async function findBinding(page, bindingId) {
  return page.eval(`(async()=>{
    const scopesResponse=await fetch('/api/v2/rules/binding-scopes',{headers:{'x-request-id':crypto.randomUUID()},cache:'no-store'});
    if(!scopesResponse.ok) return {status:scopesResponse.status,binding:null};
    const scopes=await scopesResponse.json();
    for(const application of scopes.applications??[]){
      const query=new URLSearchParams({environmentId:application.environmentId,appId:application.id,kind:'flow',page:'1',pageSize:'100'});
      const response=await fetch('/api/v1/rulesets?'+query,{headers:{'x-request-id':crypto.randomUUID()},cache:'no-store'});
      if(!response.ok) continue;
      const body=await response.json();
      const binding=body.items?.find(item=>item.id===${JSON.stringify(bindingId)});
      if(binding) return {status:200,binding};
    }
    return {status:200,binding:null};
  })()`);
}

async function navigateHashRoute(page, route) {
  const targetHash = route.hash.startsWith("#") ? route.hash.slice(1) : route.hash;
  await page.eval(`location.hash=${JSON.stringify(targetHash)}`);
  await page.waitFor(`location.hash===${JSON.stringify(`#${targetHash}`)}`, {
    timeoutMs: 10000,
    label: `SPA route changes to ${targetHash.split("?")[0]}`,
  });
}

async function ensureEmptyConsulKey({ key, datacenter }) {
  const consulUrl = process.env.SENTINEL_E2E_CONSUL_URL;
  assert.ok(consulUrl, "SENTINEL_E2E_CONSUL_URL is required for the live provider fixture");
  const consulBaseUrl = consulUrl.replace(/\/$/, "");
  const encodedKey = key.split("/").map(encodeURIComponent).join("/");
  const sourceQuery = new URLSearchParams();
  if (datacenter) sourceQuery.set("dc", datacenter);
  const path = `${consulBaseUrl}/v1/kv/${encodedKey}`;
  const rawQuery = new URLSearchParams(sourceQuery);
  rawQuery.set("raw", "");
  const current = await fetch(`${path}?${rawQuery}`, { signal: AbortSignal.timeout(3000) });
  if (current.status === 200) {
    assert.equal(await current.text(), "[]", "refuse to overwrite a non-empty Consul test key");
    return;
  }
  assert.equal(
    current.status,
    404,
    "Consul fixture key is either absent or the expected empty array",
  );
  const written = await fetch(`${path}${sourceQuery.size ? `?${sourceQuery}` : ""}`, {
    method: "PUT",
    headers: { "content-type": "application/json" },
    body: "[]",
    signal: AbortSignal.timeout(3000),
  });
  assert.equal(written.status, 200, "seed the run-owned Consul key with a valid empty ruleset");
  assert.equal(await written.text(), "true");
}

async function readConsulManagedEnvelope({ key, datacenter }) {
  const consulBaseUrl = process.env.SENTINEL_E2E_CONSUL_URL?.replace(/\/$/, "");
  assert.ok(consulBaseUrl, "SENTINEL_E2E_CONSUL_URL is required for provider read-back");
  const encodedKey = key.split("/").map(encodeURIComponent).join("/");
  const query = new URLSearchParams({ raw: "" });
  if (datacenter) query.set("dc", datacenter);
  const response = await fetch(`${consulBaseUrl}/v1/kv/${encodedKey}?${query}`, {
    signal: AbortSignal.timeout(3000),
  });
  assert.equal(response.status, 200, "exact Consul target is readable after publication");
  return JSON.parse(await response.text());
}

async function registerConsulBinding(
  page,
  {
    origin,
    bindingId,
    environmentId,
    appId,
    profile = "sentinel-python-v1",
    seedEmptySnapshot = false,
  },
) {
  const route = new URL(`${origin}/#/rules`);
  route.hash = `/rules?env=${encodeURIComponent(environmentId)}&app=${encodeURIComponent(appId)}`;
  await page.goto(route.toString());
  await page.waitFor(`!!document.querySelector('[data-binding-total]')`, {
    timeoutMs: 15000,
    label: "deep-linked environment/application scope opens the rule directory",
  });

  const sources = await page.eval(`(async()=>{
    const response=await fetch('/api/v1/system/sources',{headers:{'x-request-id':crypto.randomUUID()},cache:'no-store'});
    const body=await response.json();
    return {status:response.status,items:body.items};
  })()`);
  assert.equal(sources.status, 200);
  const consul = sources.items.find((source) => source.provider === "consul");
  assert.ok(consul, "an admin-registered Consul source is available");
  const key = `sentinel/e2e/${bindingId}/flow-rules.json`;
  if (seedEmptySnapshot) await ensureEmptyConsulKey({ key, datacenter: consul.datacenter });

  await page.clickByText("登记规则绑定", ".app-shell button");
  await page.waitFor(`!!document.querySelector('dialog[open]')`);
  await page.waitFor(
    `!![...document.querySelectorAll('dialog[open] [role=combobox]')].find(node=>node.textContent.includes('选择'))`,
    { timeoutMs: 15000, label: "registered source catalog finishes loading" },
  );
  await fillByLabel(page, "绑定标识", bindingId);
  await fillByLabel(page, "部署环境", environmentId);
  await fillByLabel(page, "应用", appId);
  await fillByLabel(page, "兼容配置标识", profile);
  await page.click('dialog[open] [role="combobox"]', { index: 1 });
  const sourceOption = `${consul.name} · Consul`;
  await page.waitFor(
    `[...document.querySelectorAll('[role=option]')].some(node=>node.offsetParent&&node.textContent.trim()===${JSON.stringify(sourceOption)})`,
    { label: "registered Consul source is available as a binding target" },
  );
  await page.clickByText(sourceOption, "[role=option]");
  await fillByLabel(page, "Consul KV 键", key);
  await page.clickByText("登记绑定", "dialog button");
  await page.waitFor(`!document.querySelector('dialog[open]')`, {
    timeoutMs: 15000,
    label: "Console accepts and closes binding registration dialog",
  });
  await page.waitFor(
    `new URL(location.href).hash.includes(${JSON.stringify(`binding=${bindingId}`)})`,
    { timeoutMs: 15000, label: "new binding becomes the selected rule scope" },
  );

  const persisted = await page.eval(`(async()=>{
    const requestId=crypto.randomUUID();
    const query=new URLSearchParams({environmentId:${JSON.stringify(environmentId)},appId:${JSON.stringify(appId)},kind:'flow',page:'1',pageSize:'20'});
    const response=await fetch('/api/v1/rulesets?'+query,{headers:{'x-request-id':requestId},cache:'no-store'});
    const body=await response.json();
    return {status:response.status,requestId:response.headers.get('x-request-id'),total:body.total,binding:body.items?.find(item=>item.id===${JSON.stringify(bindingId)})??null};
  })()`);
  assert.equal(persisted.status, 200);
  assert.ok(persisted.requestId);
  assert.equal(persisted.total, 1);
  assert.deepEqual(
    {
      id: persisted.binding.id,
      environmentId: persisted.binding.environmentId,
      appId: persisted.binding.appId,
      kind: persisted.binding.kind,
      profile: persisted.binding.profile,
      sourceId: persisted.binding.sourceId,
      location: persisted.binding.location,
    },
    {
      id: bindingId,
      environmentId,
      appId,
      kind: "flow",
      sourceId: consul.id,
      location: `consul://${consul.datacenter}/${key}`,
      profile,
    },
  );
  return { bindingId, environmentId, appId, source: consul, key, persisted };
}

test(
  "LIVE RULE-01 slice: register a Consul binding from the UI and read the persisted binding back",
  { skip: !enabled },
  async () => {
    const page = await browser.newPage();
    const origin = new URL(E2E_BASE_URL).origin;
    const runId = randomUUID().replaceAll("-", "").slice(0, 12);
    const bindingId = process.env.SENTINEL_T07_BINDING_ID ?? `t07-edge-flow-${runId}`;
    let environmentId = process.env.SENTINEL_T07_BINDING_ENVIRONMENT_ID ?? `sentinel-e2e-${runId}`;
    let appId = process.env.SENTINEL_T07_BINDING_APP_ID ?? `sentinel-live-${runId}`;
    const profile = process.env.SENTINEL_T07_RULE_PROFILE ?? "sentinel-python-v1";
    try {
      await ensureAdminSession(page, origin);
      const { persisted } = await registerConsulBinding(page, {
        origin,
        bindingId,
        environmentId,
        appId,
        profile,
        seedEmptySnapshot: process.env.SENTINEL_T07_SEED_EMPTY_SNAPSHOT === "1",
      });
      assert.deepEqual(page.consoleErrors, []);
      console.log(`live_rule_binding_id=${bindingId}`);
      console.log(`live_rule_profile=${profile}`);
      console.log(`live_rule_environment_id=${environmentId}`);
      console.log(`live_rule_app_id=${appId}`);
      console.log(`live_rule_source_key=sentinel/e2e/${bindingId}/flow-rules.json`);
      console.log(`live_rule_binding_read_request_id=${persisted.requestId}`);
    } finally {
      await page.close();
    }
  },
);

test(
  "LIVE RULE-01: save, validate, freeze, publish to Consul, and read back the full rule set",
  { skip: !enabled },
  async () => {
    const page = await browser.newPage();
    const origin = new URL(E2E_BASE_URL).origin;
    const runId = randomUUID().replaceAll("-", "").slice(0, 12);
    let environmentId = `sentinel-e2e-${runId}`;
    let appId = `sentinel-live-${runId}`;
    const resource =
      process.env.SENTINEL_T07_DEMO_RESOURCE ?? `GET /api/t07/${runId}`;
    const versionName = `T07 ${runId}`;
    const key = `sentinel/e2e/${managedBindingId}/flow-rules.json`;
    try {
      await ensureAdminSession(page, origin);
      const existing = await findBinding(page, managedBindingId);
      assert.equal(existing.status, 200, "Console rule binding scope is readable");
      if (existing.binding) {
        environmentId = existing.binding.environmentId;
        appId = existing.binding.appId;
        const location = new URL(existing.binding.location);
        assert.equal(location.protocol, "consul:");
        const sourceRows = await page.eval(`(async()=>{
          const response=await fetch('/api/v1/system/sources',{headers:{'x-request-id':crypto.randomUUID()},cache:'no-store'});
          const body=await response.json();return {status:response.status,items:body.items};
        })()`);
        assert.equal(sourceRows.status, 200);
        const consul = sourceRows.items.find((source) => source.id === existing.binding.sourceId);
        assert.ok(consul);
        assert.match(location.pathname.replace(/^\/+/, ""), /^sentinel\/e2e\//);
        await page.goto(
          `${origin}/#/rules?env=${encodeURIComponent(environmentId)}&app=${encodeURIComponent(appId)}&view=flow&binding=${encodeURIComponent(managedBindingId)}`,
        );
      } else {
        await registerConsulBinding(page, {
          origin,
          bindingId: managedBindingId,
          environmentId,
          appId,
          seedEmptySnapshot: true,
        });
      }

      await page.waitFor(
        `(()=>{const button=document.querySelector('[data-rule-action="begin"]');return !!button&&!button.disabled})()`,
        {
          timeoutMs: 15000,
          label:
            "Console read the authoritative Consul snapshot and unlocked draft creation for this exact binding",
        },
      );
      await page.eval(
        `window.__t07ClickEvents=[];document.addEventListener('click',event=>window.__t07ClickEvents.push({target:event.target?.outerHTML?.slice(0,240),trusted:event.isTrusted}),true)`,
      );
      await page.click('[data-rule-action="begin"]');
      await page.waitFor(`!!document.querySelector('[data-ruleset-editor]')`);
      try {
        await page.waitFor(
          `!!document.querySelector('[data-rule-action="add"]') || !!document.querySelector('[data-rule-record]')`,
          {
            timeoutMs: 15000,
            label: "rule editor shows either an existing record or its add action",
          },
        );
      } catch (error) {
        const state = await page.eval(`(() => {
          const editor=document.querySelector('[data-ruleset-editor]');
          return {
            url:location.href,
            editorText:editor?.innerText.slice(0,1200)??null,
            actions:[...document.querySelectorAll('[data-rule-action]')].map(node=>({id:node.dataset.ruleAction,disabled:node.disabled,text:node.innerText})),
            records:document.querySelectorAll('[data-rule-record]').length,
            routeState:[...document.querySelectorAll('[data-route-state]')].map(node=>node.dataset.routeState),
            clickEvents:window.__t07ClickEvents,
            consoleErrors:window.__t07ConsoleErrors??[],
          };
        })()`);
        throw new Error(`${error.message}\nRule editor state: ${JSON.stringify(state)}`);
      }
      const hasExistingRecord = await page.eval(
        `document.querySelectorAll('[data-rule-record]').length>0`,
      );
      if (!hasExistingRecord) await page.click('[data-rule-action="add"]');
      await page.waitFor(`!!document.querySelector('[data-ruleset-editor] label')`);
      await fillByLabel(page, "资源名称", resource, "[data-ruleset-editor]");
      await fillByLabel(page, "单机阈值", "3", "[data-ruleset-editor]");
      await selectByIndex(page, 0, "QPS");
      await selectByIndex(page, 1, "直接");
      await selectByIndex(page, 2, "直接拒绝");
      await page.waitFor(
        `document.querySelector('[data-rule-full-preview]')?.textContent.includes(${JSON.stringify(resource)})`,
      );
      await page.click('[data-rule-action="save"]');
      await page.waitFor(
        `document.querySelector('[data-rule-dirty]')?.textContent.includes('当前内容无未保存修改') && !document.querySelector('[data-ruleset-editor]')?.textContent.includes('尚未保存到后台')`,
        { timeoutMs: 15000, label: "complete candidate was saved as a durable draft" },
      );

      await page.click('[data-rule-action="validate"]');
      await page.waitFor(
        `document.querySelector('[data-rule-validation]')?.textContent.includes('目标兼容性校验通过') && !document.querySelector('[data-rule-action="freeze"]')?.disabled`,
        { timeoutMs: 20000, label: "Python rule profile validates the complete flow candidate" },
      );
      await page.click('[data-rule-action="freeze"]');
      await page.waitFor(`!!document.querySelector('dialog[open]')`);
      await fillByLabel(page, "版本名称", versionName);
      await fillByLabel(page, "版本说明", "Disposable live Edge acceptance; synthetic rule.");
      await page.clickByText("固化不可变版本", "dialog button");
      await page.waitFor(`!document.querySelector('dialog[open]')`, {
        timeoutMs: 15000,
        label: "candidate becomes an immutable version",
      });
      await page.clickByText("刷新版本目录", ".app-shell button");
      await page.waitFor(
        `[...document.querySelectorAll('[data-deployment-version]')].some(button=>button.textContent.trim()===${JSON.stringify(versionName)})`,
        { timeoutMs: 15000, label: "immutable version appears in the live version directory" },
      );
      const versionId = await page.eval(
        `[...document.querySelectorAll('[data-deployment-version]')].find(button=>button.textContent.trim()===${JSON.stringify(versionName)})?.getAttribute('data-deployment-version')??null`,
      );
      assert.ok(versionId);
      await page.click(`[data-deployment-version="${versionId}"]`);
      await page.waitFor(`!!document.querySelector('[data-version-detail]')`);

      const currentTarget = await page.eval(`(async()=>{
        const response=await fetch('/api/v1/rulesets/${managedBindingId}/publication-target',{headers:{'x-request-id':crypto.randomUUID()},cache:'no-store'});
        return {status:response.status,body:await response.json()};
      })()`);
      assert.equal(currentTarget.status, 200);
      const targetAlreadyMatches =
        currentTarget.body.target?.provider === "consul" && currentTarget.body.target?.key === key;
      await page.click('[aria-labelledby="rule-publication-target-title"] button');
      await page.waitFor(`!!document.querySelector('dialog[open]')`);
      await page.click('dialog[open] [role="combobox"]');
      await page.waitFor(
        `[...document.querySelectorAll('[role=option]')].some(option=>option.offsetParent&&option.textContent.trim()==='Consul')`,
        { label: "Consul is an available publication provider" },
      );
      await page.clickByText("Consul", "[role=option]");
      await fillByLabel(page, "Consul 键", key);
      if (targetAlreadyMatches) {
        await page.send("Input.dispatchKeyEvent", {
          type: "keyDown",
          key: "Escape",
          code: "Escape",
        });
        await page.send("Input.dispatchKeyEvent", { type: "keyUp", key: "Escape", code: "Escape" });
      } else {
        await page.clickByText("保存目标", "dialog button");
      }
      await page.waitFor(`!document.querySelector('dialog[open]')`);

      const target = await page.eval(`(async()=>{
        const response=await fetch('/api/v1/rulesets/${managedBindingId}/publication-target',{headers:{'x-request-id':crypto.randomUUID()},cache:'no-store'});
        return {status:response.status,body:await response.json()};
      })()`);
      assert.equal(target.status, 200);
      assert.equal(target.body.target?.provider, "consul");
      assert.equal(target.body.target?.key, key);

      await page.click("[data-deployment-publish]");
      await page.waitFor(`!!document.querySelector('[data-deployment-submit-publish]')`);
      await fillByLabel(page, "操作原因", `T07 Edge live ${runId}`);
      await page.waitFor(`!document.querySelector('[data-deployment-submit-publish]')?.disabled`, {
        timeoutMs: 15000,
        label: "publication command is enabled after the operation reason is entered",
      });
      await page.click("[data-deployment-submit-publish]");

      let publication;
      for (let attempt = 0; attempt < 60; attempt += 1) {
        publication = await page.eval(`(async()=>{
          const response=await fetch('/api/v1/rulesets/${managedBindingId}/publications',{
            headers:{'x-request-id':crypto.randomUUID()},cache:'no-store'
          });
          const body=await response.json();
          const item=body.items?.find(row=>row.targetVersionId===${JSON.stringify(versionId)});
          return {status:response.status,body,item};
        })()`);
        if (publication.status !== 200) break;
        if (
          publication.item &&
          (publication.item.readBack?.state === "succeeded" ||
            [
              publication.item.validation,
              publication.item.configurationWrite,
              publication.item.readBack,
            ].some((phase) => phase?.state === "failed" || phase?.state === "unknown"))
        ) {
          break;
        }
        publication = { ...publication, status: 408 };
        await new Promise((resolve) => setTimeout(resolve, 1000));
      }
      assert.equal(publication.status, 200);
      assert.ok(publication.item, "Console persisted a publication lifecycle record");
      assert.equal(publication.item.targetVersionId, versionId);
      assert.equal(
        publication.item.validation.state,
        "succeeded",
        `publication validation phase: ${JSON.stringify(publication.item.validation)}`,
      );
      assert.equal(
        publication.item.configurationWrite.state,
        "succeeded",
        `publication configuration-write phase: ${JSON.stringify(publication.item.configurationWrite)}`,
      );
      assert.equal(
        publication.item.readBack.state,
        "succeeded",
        `publication read-back phase: ${JSON.stringify(publication.item.readBack)}`,
      );

      const snapshot = await page.eval(`(async()=>{
        const response=await fetch('/api/v1/rulesets/${managedBindingId}/snapshot',{headers:{'x-request-id':crypto.randomUUID()},cache:'no-store'});
        return {status:response.status,requestId:response.headers.get('x-request-id'),body:await response.json()};
      })()`);
      assert.equal(snapshot.status, 200);
      assert.ok(snapshot.requestId);
      assert.equal(snapshot.body.records.length, 1);
      assert.equal(snapshot.body.records[0].rule.value.resource, resource);
      assert.equal(snapshot.body.records[0].rule.value.count, 3);
      const envelope = await readConsulManagedEnvelope({ key, datacenter: "dc1" });
      assert.equal(envelope.binding_id, managedBindingId);
      assert.equal(envelope.publication_id, publication.item.id);
      assert.equal(envelope.target_version_id, versionId);
      assert.equal(envelope.payload_sha256, snapshot.body.checksum.replace(/^sha256:/, ""));
      const expectedProviderRules =
        process.env.SENTINEL_T07_RULE_PROFILE === "sentinel-go-v1"
          ? [
              {
                resource,
                threshold: 3,
                statIntervalInMs: 1000,
                tokenCalculateStrategy: 0,
                controlBehavior: 0,
                relationStrategy: 0,
                refResource: "",
              },
            ]
          : [snapshot.body.records[0].rule.value];
      assert.deepEqual(JSON.parse(envelope.rule_payload), expectedProviderRules);
      assert.deepEqual(page.consoleErrors, []);
      console.log(`live_rule_publication_binding_id=${managedBindingId}`);
      console.log(`live_rule_publication_id=${publication.item.id}`);
      console.log(`live_rule_publication_readback_request_id=${snapshot.requestId}`);
    } finally {
      await page.close();
    }
  },
);

const liveRuntimeBindings = ["JAVA", "GO", "RUST"].map((language) => ({
  language,
  bindingId: process.env[`SENTINEL_T07_${language}_BINDING_ID`],
  profileId: `sentinel-${language.toLowerCase()}-v1`,
}));
const liveRuntimeObservationsEnabled =
  enabled && liveRuntimeBindings.every(({ bindingId }) => Boolean(bindingId));

test(
  "LIVE RULE-OBS-01: Java, Go, and Rust runtime snapshots are durable and visible in the rules page",
  { skip: !liveRuntimeObservationsEnabled },
  async () => {
    const page = await browser.newPage();
    const origin = new URL(E2E_BASE_URL).origin;
    try {
      await ensureAdminSession(page, origin);
      for (const target of liveRuntimeBindings) {
        const bindingRead = await findBinding(page, target.bindingId);
        assert.equal(bindingRead.status, 200, `${target.language} binding directory is readable`);
        assert.ok(
          bindingRead.binding,
          `${target.language} binding exists in the authoritative directory`,
        );
        assert.equal(bindingRead.binding.profile, target.profileId);
        const { environmentId, appId } = bindingRead.binding;
        const observation = await page.eval(`(async()=>{
          const query=new URLSearchParams({
            environmentId:${JSON.stringify(environmentId)},
            appId:${JSON.stringify(appId)},
            bindingId:${JSON.stringify(target.bindingId)},
            page:'1',pageSize:'20'
          });
          let last=null;
          for(let attempt=0;attempt<35;attempt++){
            const requestId=crypto.randomUUID();
            const response=await fetch('/api/v2/rules/load-observations?'+query,{
              headers:{'x-request-id':requestId},cache:'no-store'
            });
            last={status:response.status,requestId,body:await response.json()};
            if(response.status!==200)return last;
            const targets=last.body.targets;
            if(targets.expected>=1 && targets.observed===targets.expected && targets.stale===0) return last;
            await new Promise(resolve=>setTimeout(resolve,1000));
          }
          return last;
        })()`);
        assert.equal(observation.status, 200, `${target.language} observation API succeeds`);
        assert.ok(observation.requestId, `${target.language} observation has a request ID`);
        const { body } = observation;
        assert.equal(body.query.bindingId, target.bindingId);
        assert.equal(body.query.environmentId, environmentId);
        assert.equal(body.query.appId, appId);
        assert.equal(body.coverage, "complete");
        assert.ok(
          body.targets.expected >= 1,
          `${target.language} enrollment is an expected target`,
        );
        assert.equal(
          body.targets.observed,
          body.targets.expected,
          `${target.language} expected every enrolled worker to report: ${JSON.stringify(body.targets)}; items=${JSON.stringify(body.items)}`,
        );
        assert.equal(
          body.targets.stale,
          0,
          `${target.language} must have no stale workers: ${JSON.stringify(body.targets)}; items=${JSON.stringify(body.items)}`,
        );
        assert.equal(
          body.targets.notObserved,
          0,
          `${target.language} must have no unobserved workers: ${JSON.stringify(body.targets)}; items=${JSON.stringify(body.items)}`,
        );
        const runtime = body.items.find((item) => item.profileId === target.profileId);
        assert.ok(runtime, `${target.language} runtime is present in the durable observation page`);
        assert.equal(runtime.bindingId, target.bindingId);
        assert.equal(runtime.loadState, "applied");
        assert.equal(runtime.freshness, "current");
        assert.ok(
          ["snapshot_applied", "heartbeat"].includes(runtime.eventKind),
          `${target.language} must expose an applied snapshot or its current heartbeat, got ${runtime.eventKind}`,
        );
        assert.ok(runtime.activeSnapshot, `${target.language} active snapshot survives heartbeats`);
        assert.equal(runtime.activeSnapshot.membershipComplete, true);
        assert.ok(
          runtime.activeSnapshot.members.some((member) => member.ruleKind === "flow"),
          `${target.language} applied Flow rule membership is reported`,
        );

        const route = new URL(origin);
        route.hash = `/rules?env=${encodeURIComponent(environmentId)}&app=${encodeURIComponent(appId)}&range=1h&view=flow&binding=${encodeURIComponent(target.bindingId)}`;
        await page.goto(route.toString());
        await page.waitFor(
          `document.body.innerText.includes(${JSON.stringify(runtime.instanceId)})`,
          {
            timeoutMs: 15000,
            label: `${target.language} runtime instance appears in the rendered rules page`,
          },
        );
        assert.deepEqual(page.consoleErrors, []);
        console.log(
          `live_rule_observation_${target.language.toLowerCase()}_binding_id=${target.bindingId}`,
        );
        console.log(
          `live_rule_observation_${target.language.toLowerCase()}_instance_id=${runtime.instanceId}`,
        );
        console.log(
          `live_rule_observation_${target.language.toLowerCase()}_request_id=${observation.requestId}`,
        );
      }
    } finally {
      await page.close();
    }
  },
);

const rustRuntime = {
  bindingId: process.env.SENTINEL_T07_RUST_BINDING_ID,
  demoUrl: process.env.SENTINEL_T07_RUST_DEMO_URL,
};
const liveRustRuntimeEnabled = enabled && Object.values(rustRuntime).every(Boolean);

test(
  "LIVE RUST-RULES-01: Rust loads the exact managed Consul publication and enforces the flow threshold",
  { skip: !liveRustRuntimeEnabled },
  async () => {
    const page = await browser.newPage();
    const origin = new URL(E2E_BASE_URL).origin;
    try {
      await ensureAdminSession(page, origin);
      const bindingRead = await findBinding(page, rustRuntime.bindingId);
      assert.equal(bindingRead.status, 200);
      assert.ok(bindingRead.binding, "Rust binding is present in the authoritative catalog");
      assert.equal(bindingRead.binding.profile, "sentinel-rust-v1");

      const runtimeRulesResponse = await fetch(`${rustRuntime.demoUrl}/rules`, {
        headers: { accept: "application/json" },
        signal: AbortSignal.timeout(5000),
      });
      assert.equal(runtimeRulesResponse.status, 200);
      const runtimeRules = await runtimeRulesResponse.json();
      assert.equal(runtimeRules.rules_loaded, true);
      assert.equal(runtimeRules.profile_id, "sentinel-rust-v1");
      assert.equal(runtimeRules.rule_count, 1);
      assert.equal(runtimeRules.last_failure, null);
      assert.equal(runtimeRules.managed_publication?.binding_id, rustRuntime.bindingId);

      const publicationsResponse = await page.eval(`(async()=>{
        const response=await fetch('/api/v1/rulesets/${rustRuntime.bindingId}/publications',{
          headers:{'x-request-id':crypto.randomUUID()},cache:'no-store'
        });
        return {status:response.status,body:await response.json()};
      })()`);
      assert.equal(publicationsResponse.status, 200);
      const publication = publicationsResponse.body.items?.find(
        (item) => item.id === runtimeRules.managed_publication.publication_id,
      );
      assert.ok(publication, "Runtime-reported publication is present in Console history");
      assert.equal(publication.targetVersionId, runtimeRules.managed_publication.target_version_id);
      assert.equal(publication.readBack?.state, "succeeded");

      const statuses = [];
      for (let attempt = 0; attempt < 10; attempt += 1) {
        const response = await fetch(`${rustRuntime.demoUrl}/api/hello`, {
          headers: { accept: "application/json" },
          signal: AbortSignal.timeout(5000),
        });
        statuses.push(response.status);
        assert.ok([200, 429].includes(response.status));
      }
      assert.ok(statuses.includes(200), `Rust should admit below-threshold requests: ${statuses}`);
      assert.ok(statuses.includes(429), `Rust should block above-threshold requests: ${statuses}`);
      assert.deepEqual(page.consoleErrors, []);
      console.log(`live_rust_rule_publication_id=${publication.id}`);
      console.log(`live_rust_demo_statuses=${statuses.join(",")}`);
      console.log(`live_rust_canonical_rules_sha256=${runtimeRules.canonical_rules_sha256}`);
    } finally {
      await page.close();
    }
  },
);

const receiptRuntime = {
  bindingId: process.env.SENTINEL_T07_RECEIPT_BINDING_ID,
  instanceId: process.env.SENTINEL_T07_RECEIPT_INSTANCE_ID,
};
const duplicatePublicationReceiptEnabled = enabled && Object.values(receiptRuntime).every(Boolean);

test(
  "LIVE RECEIPT-01: same version has two exact durable runtime receipts and both publication details render",
  { skip: !duplicatePublicationReceiptEnabled },
  async () => {
    const page = await browser.newPage();
    const origin = new URL(E2E_BASE_URL).origin;
    try {
      await ensureAdminSession(page, origin);
      const bindingRead = await findBinding(page, receiptRuntime.bindingId);
      assert.equal(bindingRead.status, 200);
      assert.ok(bindingRead.binding, "receipt binding is resolved from the authority directory");
      const { environmentId, appId } = bindingRead.binding;

      const initialPublication = await page.eval(`(async()=>{
        const response=await fetch('/api/v1/rulesets/${receiptRuntime.bindingId}/publications',{
          headers:{'x-request-id':crypto.randomUUID()},cache:'no-store'
        });
        const body=await response.json();
        const item=(body.items??[]).find(row=>row.readBack?.state==='succeeded');
        return {status:response.status,requestId:response.headers.get('x-request-id'),item};
      })()`);
      assert.equal(initialPublication.status, 200);
      assert.ok(initialPublication.requestId);
      assert.ok(initialPublication.item, "first provider publication is confirmed");
      const firstId = initialPublication.item.id;
      const targetVersionId = initialPublication.item.targetVersionId;
      const targetChecksum = initialPublication.item.targetChecksum;

      const firstReceipt = await page.eval(`(async()=>{
        const url='/api/v1/rulesets/${receiptRuntime.bindingId}/publications/${firstId}/receipts?page=1&pageSize=20';
        for(let attempt=0;attempt<90;attempt++){
          const response=await fetch(url,{headers:{'x-request-id':crypto.randomUUID()},cache:'no-store'});
          const body=await response.json();
          if(response.status!==200)return {status:response.status,body};
          const item=(body.items??[]).find(row=>row.instanceId===${JSON.stringify(receiptRuntime.instanceId)} && row.state==='applied' && row.loadedVersionId===${JSON.stringify(targetVersionId)});
          if(item)return {status:response.status,requestId:response.headers.get('x-request-id'),body,item};
          await new Promise(resolve=>setTimeout(resolve,1000));
        }
        return {status:408,body:null};
      })()`);
      assert.equal(
        firstReceipt.status,
        200,
        "first runtime receipt is durably readable before republish",
      );
      assert.ok(firstReceipt.requestId);
      assert.equal(firstReceipt.body.publicationId, firstId);
      assert.equal(firstReceipt.body.bindingId, receiptRuntime.bindingId);

      const route = new URL(origin);
      route.hash = `/rules?env=${encodeURIComponent(environmentId)}&app=${encodeURIComponent(appId)}&range=1h&view=flow&binding=${encodeURIComponent(receiptRuntime.bindingId)}`;
      await navigateHashRoute(page, route);
      await page.waitFor(
        `!!document.querySelector('[data-deployment-version="${targetVersionId}"]')`,
        {
          timeoutMs: 20000,
          label: "same immutable version is selectable for a repeat publication",
        },
      );
      await page.click(`[data-deployment-version="${targetVersionId}"]`);
      await page.waitFor(`!!document.querySelector('[data-version-detail]')`);
      await page.click("[data-deployment-publish]");
      await page.waitFor(`!!document.querySelector('[data-deployment-submit-publish]')`);
      await fillByLabel(page, "操作原因", `T07 same-version republish ${randomUUID().slice(0, 8)}`);
      await page.waitFor(`!document.querySelector('[data-deployment-submit-publish]')?.disabled`);
      await page.click("[data-deployment-submit-publish]");

      const secondPublication = await page.eval(`(async()=>{
        const url='/api/v1/rulesets/${receiptRuntime.bindingId}/publications';
        for(let attempt=0;attempt<60;attempt++){
          const response=await fetch(url,{headers:{'x-request-id':crypto.randomUUID()},cache:'no-store'});
          const body=await response.json();
          if(response.status!==200)return {status:response.status,body};
          const item=(body.items??[]).find(row=>row.id!==${JSON.stringify(firstId)} && row.targetVersionId===${JSON.stringify(targetVersionId)} && row.readBack?.state==='succeeded');
          if(item)return {status:response.status,requestId:response.headers.get('x-request-id'),item};
          await new Promise(resolve=>setTimeout(resolve,1000));
        }
        return {status:408};
      })()`);
      assert.equal(secondPublication.status, 200);
      assert.ok(secondPublication.requestId);
      assert.ok(
        secondPublication.item,
        "a new publication ID was created for the same immutable version",
      );
      const secondId = secondPublication.item.id;
      assert.notEqual(secondId, firstId);
      assert.equal(
        secondPublication.item.targetChecksum,
        targetChecksum,
        "native target payload checksum is unchanged",
      );
      await page.waitFor(
        `(()=>{const dialog=document.querySelector('dialog[open]');return !dialog || !!dialog.querySelector('[data-command-state="result-unknown"]')})()`,
        {
          timeoutMs: 20000,
          label:
            "publication UI exposes a completed or inspectable result before leaving the workflow",
        },
      );
      const needsResultInspection = await page.eval(
        `!!document.querySelector('dialog[open] [data-command-state="result-unknown"]')`,
      );
      if (needsResultInspection) {
        await page.click('dialog[open] [data-command-state="result-unknown"] button');
      }
      try {
        await page.waitFor(`document.querySelector('dialog[open]') === null`, {
          timeoutMs: 20000,
          label: "confirmed publication closes its dialog before further UI navigation",
        });
      } catch (error) {
        const state = await page.eval(`({
          dialogs:[...document.querySelectorAll('dialog[open],[role="dialog"]')].map(node=>({
            tag:node.tagName,
            text:node.innerText?.slice(0,800)??"",
            busy:node.getAttribute('aria-busy'),
            disabled:[...node.querySelectorAll('button')].map(button=>({text:button.innerText,disabled:button.disabled}))
          })),
          body:{position:getComputedStyle(document.body).position,overflow:getComputedStyle(document.body).overflow},
          hash:location.hash
        })`);
        throw new Error(
          `${error instanceof Error ? error.message : error}; publication dialog lifecycle state=${JSON.stringify(state)}`,
        );
      }
      const scrollLock = await page.eval(`({
        position:getComputedStyle(document.body).position,
        overflow:getComputedStyle(document.body).overflow
      })`);
      assert.notEqual(
        scrollLock.position,
        "fixed",
        "closing the publication confirmation restores document scrolling",
      );
      assert.notEqual(
        scrollLock.overflow,
        "hidden",
        "closing the publication confirmation releases the body overflow lock",
      );
      await page.clickByText("刷新发布事实", ".app-shell button");
      await page.waitFor(
        `!!document.querySelector('[data-deployment-publication="${firstId}"]') && !!document.querySelector('[data-deployment-publication="${secondId}"]')`,
        {
          timeoutMs: 20000,
          label:
            "refreshing publication facts lists both distinct publications of the same version",
        },
      );

      const secondReceipt = await page.eval(`(async()=>{
        const ids=${JSON.stringify([firstId, secondId])};
        const results=[];
        for(const id of ids){
          const url='/api/v1/rulesets/${receiptRuntime.bindingId}/publications/'+encodeURIComponent(id)+'/receipts?page=1&pageSize=20';
          let result={status:408};
          for(let attempt=0;attempt<90;attempt++){
            const response=await fetch(url,{headers:{'x-request-id':crypto.randomUUID()},cache:'no-store'});
            const body=await response.json();
            if(response.status!==200){result={status:response.status,body};break;}
            const item=(body.items??[]).find(row=>row.instanceId===${JSON.stringify(receiptRuntime.instanceId)} && row.state==='applied' && row.loadedVersionId===${JSON.stringify(targetVersionId)});
            if(item){result={status:response.status,requestId:response.headers.get('x-request-id'),body,item};break;}
            await new Promise(resolve=>setTimeout(resolve,1000));
          }
          results.push(result);
        }
        return results;
      })()`);
      assert.equal(secondReceipt.length, 2);
      for (const [index, result] of secondReceipt.entries()) {
        const expectedId = index === 0 ? firstId : secondId;
        assert.equal(result.status, 200, `publication ${expectedId} has a durable receipt`);
        assert.ok(result.requestId);
        assert.equal(result.body.publicationId, expectedId);
        assert.equal(result.body.bindingId, receiptRuntime.bindingId);
        assert.equal(result.item.instanceId, receiptRuntime.instanceId);
        assert.equal(result.item.targetVersionId, targetVersionId);
        assert.equal(result.item.loadedVersionId, targetVersionId);
        assert.equal(result.item.state, "applied");
      }

      for (const publicationId of [firstId, secondId]) {
        await navigateHashRoute(page, route);
        await page.waitFor(
          `!!document.querySelector('[data-deployment-publication="${publicationId}"]')`,
          {
            timeoutMs: 20000,
            label: `publication ${publicationId} is visible in the installed Rules page`,
          },
        );
        await page.click(`[data-deployment-publication="${publicationId}"]`);
        await page.waitFor(`!!document.querySelector('[data-publication-detail]')`);
        await page.click("[data-deployment-receipts]");
        await page.waitFor(`!!document.querySelector('[data-publication-receipts]')`);
        const renderedReceipt = await page.text("[data-publication-receipts]");
        assert.ok(renderedReceipt.includes(receiptRuntime.instanceId));
        assert.ok(renderedReceipt.includes(targetVersionId));
        assert.match(renderedReceipt, /已生效|已应用|Applied/);
      }
      assert.deepEqual(page.consoleErrors, []);
      console.log(`live_receipt_binding_id=${receiptRuntime.bindingId}`);
      console.log(`live_receipt_first_publication_id=${firstId}`);
      console.log(`live_receipt_second_publication_id=${secondId}`);
      console.log(`live_receipt_same_target_checksum=${targetChecksum}`);
      console.log(`live_receipt_instance_id=${receiptRuntime.instanceId}`);
    } finally {
      await page.close();
    }
  },
);

const liveConsumerWorker = {
  reporterId: process.env.SENTINEL_T07_CONSUMER_REPORTER_ID,
  environmentId: process.env.SENTINEL_T07_CONSUMER_ENVIRONMENT_ID,
  appId: process.env.SENTINEL_T07_CONSUMER_APP_ID,
  instanceId: process.env.SENTINEL_T07_CONSUMER_INSTANCE_ID,
  incidentEventId: process.env.SENTINEL_T07_CONSUMER_INCIDENT_EVENT_ID,
};
const liveConsumerWorkerEnabled = enabled && Object.values(liveConsumerWorker).every(Boolean);

test(
  "LIVE PROTOCOL-01 / INCIDENT-01: durable worker negotiations and one incident appear in System and Faults",
  { skip: !liveConsumerWorkerEnabled },
  async () => {
    const page = await browser.newPage();
    const origin = new URL(E2E_BASE_URL).origin;
    try {
      await ensureAdminSession(page, origin);
      console.log("live_protocol_incident_stage=authenticated");
      const apiFacts = JSON.parse(
        await page.eval(`(async()=>{
        const worker=${JSON.stringify(liveConsumerWorker)};
        const read=async(path)=>{
          const headers={'x-request-id':crypto.randomUUID()};
          const response=await fetch(path,{headers,cache:'no-store'});
          return {status:response.status,requestId:response.headers.get('x-request-id'),body:await response.json()};
        };
        const paging='?page=1&pageSize=100';
        const agent=await read('/api/v2/system/protocol-observations/agent-reporting'+paging);
        const incidentsProtocol=await read('/api/v2/system/protocol-observations/incident-events'+paging);
        const from=new Date(Date.now()-60*60*1000).toISOString();
        const to=new Date(Date.now()+60*1000).toISOString();
        const query=new URLSearchParams({environmentId:worker.environmentId,appId:worker.appId,scope:'application',from,to,pageSize:'50'});
        const timeline=await read('/api/v1/incidents?'+query);
        return JSON.stringify({
          agent:{status:agent.status,requestId:agent.requestId,worker:agent.body.items?.find(item=>item.reporterId===worker.reporterId)??null},
          incidentsProtocol:{status:incidentsProtocol.status,requestId:incidentsProtocol.requestId,worker:incidentsProtocol.body.items?.find(item=>item.reporterId===worker.reporterId)??null},
          timeline:{status:timeline.status,requestId:timeline.requestId,matchingEvents:(timeline.body.items??[]).filter(item=>item.sourceEventId===worker.incidentEventId)},
        });
      })()`),
      );
      console.log("live_protocol_incident_stage=api-readback");
      for (const [name, result] of [
        ["Agent Reporting", apiFacts.agent],
        ["Incident Event", apiFacts.incidentsProtocol],
        ["incident timeline", apiFacts.timeline],
      ]) {
        assert.equal(
          result.status,
          200,
          `${name} API returns live data: ${JSON.stringify(result.body)}`,
        );
        assert.ok(result.requestId, `${name} API returns a correlated request ID`);
      }
      const agent = apiFacts.agent.worker;
      const eventProtocol = apiFacts.incidentsProtocol.worker;
      assert.ok(agent, "the enrolled worker has an Agent Reporting observation");
      assert.ok(eventProtocol, "the enrolled worker has an independent Incident Event observation");
      for (const [name, fact] of [
        ["Agent Reporting", agent],
        ["Incident Event", eventProtocol],
      ]) {
        assert.equal(fact.environmentId, liveConsumerWorker.environmentId);
        assert.equal(fact.appId, liveConsumerWorker.appId);
        assert.equal(fact.instanceId, liveConsumerWorker.instanceId);
        assert.equal(fact.compatibility, "compatible", `${name} negotiated independently`);
        assert.ok(fact.runtimeVersion, `${name} reports the negotiated runtime version`);
        assert.ok(!Object.keys(fact).some((key) => /certificate|principal|fingerprint/i.test(key)));
      }
      const matchingEvents = apiFacts.timeline.matchingEvents;
      assert.equal(matchingEvents.length, 1, "durable exact replay projects one timeline event");
      assert.equal(matchingEvents[0].instanceId, liveConsumerWorker.instanceId);
      assert.equal(matchingEvents[0].severity, "warning");
      const observedIncidentId = matchingEvents[0].id;
      assert.ok(observedIncidentId, "the durable incident projection has a display ID");

      const systemRoute = new URL(origin);
      systemRoute.hash = "/system?view=protocol";
      await page.goto(systemRoute.toString());
      console.log("live_protocol_incident_stage=system-route");
      await page.waitFor(
        `!!document.querySelector('[data-system-protocol-worker="${liveConsumerWorker.instanceId}"]')`,
        { timeoutMs: 15000, label: "durably negotiated worker is visible in System → Protocol" },
      );
      assert.ok(
        await page.eval(
          `document.querySelector('[data-system-protocol-worker="${liveConsumerWorker.instanceId}"]')?.innerText.includes('版本兼容')`,
        ),
        "System shows the worker's compatible protocol state",
      );

      const faultsRoute = new URL(origin);
      faultsRoute.hash = `/faults?env=${encodeURIComponent(liveConsumerWorker.environmentId)}&app=${encodeURIComponent(liveConsumerWorker.appId)}&range=1h`;
      await page.goto(faultsRoute.toString());
      console.log("live_protocol_incident_stage=faults-route");
      await page.waitFor(
        `!!document.querySelector('[data-observed-incident="${observedIncidentId}"]')`,
        { timeoutMs: 15000, label: "durable synthetic incident is visible once in Faults" },
      );
      assert.equal(
        await page.eval(
          `document.querySelectorAll('[data-observed-incident="${observedIncidentId}"]').length`,
        ),
        1,
      );
      assert.deepEqual(page.consoleErrors, []);
      console.log(`live_protocol_incident_reporter_id=${liveConsumerWorker.reporterId}`);
      console.log(`live_protocol_incident_event_id=${liveConsumerWorker.incidentEventId}`);
      console.log(`live_protocol_incident_projection_id=${observedIncidentId}`);
      console.log(`live_protocol_incident_agent_request_id=${apiFacts.agent.requestId}`);
      console.log(
        `live_protocol_incident_events_request_id=${apiFacts.incidentsProtocol.requestId}`,
      );
      console.log(`live_protocol_incident_timeline_request_id=${apiFacts.timeline.requestId}`);
    } finally {
      await page.close();
    }
  },
);

const protocolMatrixWorker = {
  reporterId: process.env.SENTINEL_T07_MATRIX_REPORTER_ID,
  environmentId: process.env.SENTINEL_T07_MATRIX_ENVIRONMENT_ID,
  appId: process.env.SENTINEL_T07_MATRIX_APP_ID,
  instanceId: process.env.SENTINEL_T07_MATRIX_INSTANCE_ID,
  agentState: process.env.SENTINEL_T07_MATRIX_AGENT_STATE,
  incidentState: process.env.SENTINEL_T07_MATRIX_INCIDENT_STATE,
  revoked: process.env.SENTINEL_T07_MATRIX_REVOKED === "1",
  primaryReporterId: process.env.SENTINEL_T07_CONSUMER_REPORTER_ID,
  primaryInstanceId: process.env.SENTINEL_T07_CONSUMER_INSTANCE_ID,
};
const protocolMatrixEnabled =
  enabled &&
  Boolean(
    protocolMatrixWorker.reporterId &&
    protocolMatrixWorker.environmentId &&
    protocolMatrixWorker.appId &&
    protocolMatrixWorker.instanceId &&
    protocolMatrixWorker.primaryReporterId &&
    protocolMatrixWorker.primaryInstanceId &&
    (protocolMatrixWorker.revoked ||
      (protocolMatrixWorker.agentState && protocolMatrixWorker.incidentState)),
  );

test(
  "LIVE PROTOCOL-01: per-worker unknown, unsupported, independent, and revoked states are visible",
  { skip: !protocolMatrixEnabled },
  async () => {
    const page = await browser.newPage();
    const origin = new URL(E2E_BASE_URL).origin;
    const matrixWorker = JSON.stringify(protocolMatrixWorker);
    const expectedStates = protocolMatrixWorker.revoked
      ? { agent: null, incident: null }
      : {
          agent: protocolMatrixWorker.agentState,
          incident: protocolMatrixWorker.incidentState,
        };
    const expectedLabel = {
      compatible: "版本兼容",
      incompatible: "版本不兼容",
      unknown: "尚未确认",
    };
    try {
      await ensureAdminSession(page, origin);
      const facts = await page.eval(`(async()=>{
        const worker=${matrixWorker};
        const read=async(boundary)=>{
          const requestId=crypto.randomUUID();
          const response=await fetch('/api/v2/system/protocol-observations/'+boundary+'?page=1&pageSize=100',{
            headers:{'x-request-id':requestId},cache:'no-store'
          });
          const body=await response.json();
          return {status:response.status,requestId,worker:body.items?.find(item=>item.reporterId===worker.reporterId)??null,
            primary:body.items?.find(item=>item.reporterId===worker.primaryReporterId)??null};
        };
        return {
          agent:await read('agent-reporting'),
          incident:await read('incident-events')
        };
      })()`);
      for (const [boundary, result] of Object.entries(facts)) {
        assert.equal(result.status, 200, `${boundary} observation API succeeds`);
        assert.ok(result.requestId, `${boundary} request has a correlation ID`);
        assert.ok(result.primary, `${boundary} keeps the first worker independently visible`);
        assert.equal(result.primary.compatibility, "compatible");
        assert.equal(result.worker?.compatibility ?? null, expectedStates[boundary]);
        if (result.worker) {
          assert.equal(result.worker.environmentId, protocolMatrixWorker.environmentId);
          assert.equal(result.worker.appId, protocolMatrixWorker.appId);
          assert.equal(result.worker.instanceId, protocolMatrixWorker.instanceId);
          assert.ok(
            !Object.keys(result.worker).some((key) =>
              /certificate|principal|fingerprint/i.test(key),
            ),
            `${boundary} projection does not expose credential identity`,
          );
        }
      }

      const systemRoute = new URL(origin);
      systemRoute.hash = "/system?view=protocol";
      await page.goto(systemRoute.toString());
      const selector = (section, instanceId) =>
        `[data-system-protocol-boundary="${section}"] [data-system-protocol-worker="${instanceId}"]`;
      const agentPrimary = selector(
        "agent-reporting-workers-title",
        protocolMatrixWorker.primaryInstanceId,
      );
      const incidentPrimary = selector(
        "incident-event-workers-title",
        protocolMatrixWorker.primaryInstanceId,
      );
      await page.waitFor(
        `!!document.querySelector(${JSON.stringify(agentPrimary)}) && !!document.querySelector(${JSON.stringify(incidentPrimary)})`,
        {
          timeoutMs: 15000,
          label: "both protocol worker lists render their independent primary worker",
        },
      );
      for (const [boundary, section] of [
        ["agent", "agent-reporting-workers-title"],
        ["incident", "incident-event-workers-title"],
      ]) {
        const workerSelector = selector(section, protocolMatrixWorker.instanceId);
        if (protocolMatrixWorker.revoked) {
          assert.equal(
            await page.eval(`!!document.querySelector(${JSON.stringify(workerSelector)})`),
            false,
          );
          continue;
        }
        await page.waitFor(`!!document.querySelector(${JSON.stringify(workerSelector)})`, {
          timeoutMs: 15000,
          label: `${boundary} worker row is rendered`,
        });
        assert.ok(
          await page.eval(
            `document.querySelector(${JSON.stringify(workerSelector)})?.innerText.includes(${JSON.stringify(expectedLabel[expectedStates[boundary]])})`,
          ),
          `${boundary} UI shows ${expectedStates[boundary]} for the second worker`,
        );
      }
      assert.deepEqual(page.consoleErrors, []);
      console.log(`live_protocol_matrix_reporter_id=${protocolMatrixWorker.reporterId}`);
      console.log(`live_protocol_matrix_agent_state=${expectedStates.agent ?? "revoked-excluded"}`);
      console.log(
        `live_protocol_matrix_incident_state=${expectedStates.incident ?? "revoked-excluded"}`,
      );
      console.log(`live_protocol_matrix_agent_request_id=${facts.agent.requestId}`);
      console.log(`live_protocol_matrix_incident_request_id=${facts.incident.requestId}`);
    } finally {
      await page.close();
    }
  },
);
