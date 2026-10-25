import { after, before, test } from "node:test";
import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { E2E_BASE_URL, connectE2EBrowser } from "./cdp.mjs";

const enabled = process.env.SENTINEL_E2E_LIVE_MONITORING === "1";
const adminPassword = process.env.SENTINEL_LIVE_E2E_PASSWORD;
const prometheusEndpoint = process.env.SENTINEL_T07_PROMETHEUS_ENDPOINT;
const prometheusJob = process.env.SENTINEL_T07_PROMETHEUS_JOB;
const prometheusHostLabel = process.env.SENTINEL_T07_PROMETHEUS_HOST_LABEL ?? "host";
const prometheusHostId = process.env.SENTINEL_T07_PROMETHEUS_HOST_ID ?? "synthetic-node-a";
const environmentId = process.env.SENTINEL_T07_MONITORING_ENVIRONMENT ?? "sentinel-e2e";
let browser;

async function waitForPrometheusJob(job) {
  assert.ok(prometheusEndpoint, "Prometheus endpoint is configured");
  let lastObservation = null;
  for (let attempt = 0; attempt < 12; attempt += 1) {
    const url = new URL("/api/v1/query", prometheusEndpoint);
    url.searchParams.set("query", `up{job=${JSON.stringify(job)}}`);
    try {
      const response = await fetch(url, { signal: AbortSignal.timeout(10000) });
      const body = await response.json();
      lastObservation = { status: response.status, result: body?.data?.result ?? null };
      if (
        response.ok &&
        body?.status === "success" &&
        body?.data?.result?.some((sample) => sample?.value?.[1] === "1")
      ) {
        return;
      }
    } catch (error) {
      lastObservation = error instanceof Error ? error.message : String(error);
    }
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  assert.fail(
    `Prometheus scrape target ${job} did not become healthy: ${JSON.stringify(lastObservation)}`,
  );
}

before(async () => {
  if (enabled) browser = await connectE2EBrowser();
});

after(async () => {
  await browser?.close();
});

async function fillByLabel(page, label, value) {
  const control = await page.eval(`(()=>{
    const item=[...document.querySelectorAll('dialog[open] label')].find(node=>node.textContent.trim()===${JSON.stringify(label)});
    const input=item?.control;
    if(!(input instanceof HTMLInputElement || input instanceof HTMLTextAreaElement)) return null;
    input.focus();input.setSelectionRange(0,input.value.length);
    return input.id;
  })()`);
  assert.ok(control, `monitoring source field exists: ${label}`);
  await page.send("Input.insertText", { text: value });
  await page.waitFor(
    `(()=>{const item=[...document.querySelectorAll('dialog[open] label')].find(node=>node.textContent.trim()===${JSON.stringify(label)});return item?.control?.value===${JSON.stringify(value)}})()`,
    { label: `${label} accepts the candidate` },
  );
}

async function verifyPrometheusProbe(page, label) {
  let lastFailure = null;
  for (let attempt = 1; attempt <= 3; attempt += 1) {
    await page.clickByText("测试连接", "dialog[open] button");
    try {
      await page.waitFor(
        `document.querySelector('dialog[open]')?.textContent.includes('reachable · available · supported')`,
        { timeoutMs: 15000, label },
      );
      return;
    } catch (error) {
      lastFailure = await page.eval(`(()=>({
        dialog:document.querySelector('dialog[open]')?.innerText??null,
        alerts:[...document.querySelectorAll('[role="alert"]')].map(item=>item.innerText),
        responses:window.__t07MonitoringProbeResponses??[]
      }))()`);
      const retryableTimeout = lastFailure.dialog?.includes("unreachable · unknown · unknown") &&
        (lastFailure.responses.length === 0 || lastFailure.responses.at(-1)?.body?.result?.failure === "timeout");
      if (!retryableTimeout || attempt === 3) {
        throw new Error(
          `${error instanceof Error ? error.message : error}; attempt=${attempt}; probe=${JSON.stringify(lastFailure)}`,
        );
      }
    }
  }
  throw new Error(`${label}; probe=${JSON.stringify(lastFailure)}`);
}

test(
  "LIVE monitoring source: Edge registration reads real HOST samples",
  { skip: !enabled || !adminPassword || !prometheusEndpoint || !prometheusJob },
  async () => {
    await waitForPrometheusJob(prometheusJob);
    const page = await browser.newPage();
    const origin = new URL(E2E_BASE_URL).origin;
    try {
      await page.clearStorage(origin);
      await page.send("Page.addScriptToEvaluateOnNewDocument", {
        source: `(()=>{
          const nativeFetch=globalThis.fetch.bind(globalThis);
          globalThis.__t07MonitoringProbeResponses=[];
          globalThis.fetch=async(...args)=>{
            const response=await nativeFetch(...args);
            const requestUrl=args[0] instanceof Request?args[0].url:String(args[0]);
            if(requestUrl.includes('/api/v2/monitoring/sources/check') || requestUrl.includes('/host-metrics?')){
              let body=null;
              try{body=await response.clone().json()}catch{}
              globalThis.__t07MonitoringProbeResponses.push({url:requestUrl,status:response.status,body});
            }
            return response;
          };
        })();`,
      });
      await page.goto(`${origin}/#/login?app=all&range=1h`);
      try {
        await page.waitFor(
          `!!document.querySelector('.login-page input[autocomplete="username"]') || !!document.querySelector('.app-shell')`,
          {
            timeoutMs: 15000,
            label: "installed Console resolves login or the existing authenticated shell",
          },
        );
      } catch (error) {
        const state = await page.eval(
          `(()=>({href:location.href,title:document.title,readyState:document.readyState,rootText:document.querySelector('#root')?.innerText.slice(0,240)??'',scripts:[...document.scripts].map(script=>script.src)}))()`,
        );
        throw new Error(
          `${error instanceof Error ? error.message : error}; page=${JSON.stringify(state)}; consoleErrors=${JSON.stringify(page.consoleErrors)}`,
        );
      }
      if (await page.count('.login-page input[autocomplete="username"]')) {
        await page.type('.login-page input[autocomplete="username"]', "admin");
        await page.type('.login-page input[autocomplete="current-password"]', adminPassword);
        await page.clickByText("登录", ".login-page form button");
      }
      await page.waitFor(
        `location.hash.startsWith('#/overview') && !!document.querySelector('.app-shell')`,
        { timeoutMs: 15000, label: "Console confirms the fresh admin session" },
      );

      await page.goto(`${origin}/#/system?view=connections`);
      await page.waitFor(
        `location.hash.startsWith('#/system') && [...document.querySelectorAll('.app-shell .intro h1')].some(node=>node.textContent.trim().length>0) && document.body.textContent.includes('主机监控数据源')`,
        {
          timeoutMs: 15000,
          label: "connections view renders the formal monitoring source registry",
        },
      );
      await page.clickByText("添加监控源", "button");
      await page.waitFor(`!!document.querySelector('dialog[open]')`);

      const runId = randomUUID();
      const displayName = `T07 Prometheus ${runId.slice(0, 8)}`;
      await fillByLabel(page, "名称", displayName);
      await fillByLabel(page, "环境标识", environmentId);
      await fillByLabel(page, "Prometheus 服务地址", prometheusEndpoint);
      await fillByLabel(page, "实例身份标签", prometheusHostLabel);
      await fillByLabel(page, "采集任务标签名", "job");
      await fillByLabel(page, "采集任务标签值", prometheusJob);
      await verifyPrometheusProbe(
        page,
        "real Prometheus API and node-exporter profile probe are supported",
      );
      await page.clickByText("保存登记", "dialog[open] button");
      await page.waitFor(
        `!document.querySelector('dialog[open]') && document.body.textContent.includes('监控源已验证并保存') && [...document.querySelectorAll('[data-monitoring-source-id]')].some(row=>row.textContent.includes(${JSON.stringify(displayName)}))`,
        {
          timeoutMs: 15000,
          label: "verified monitoring source is persisted and shown in the formal registry",
        },
      );

      const evidence = await page.eval(`(async()=>{
        const requestId=crypto.randomUUID();
        const headers={'x-request-id':requestId};
        const directoryResponse=await fetch('/api/v2/monitoring/sources',{headers,cache:'no-store'});
        const directory=await directoryResponse.json();
        const source=directory.items?.find(item=>item.displayName===${JSON.stringify(displayName)});
        if(!source) return {directoryStatus:directoryResponse.status,source:null};
        const end=new Date();
        const start=new Date(end.getTime()-5*60*1000);
        const query=new URLSearchParams({from:start.toISOString(),to:end.toISOString(),stepMs:'15000'});
        const metricsResponse=await fetch('/api/v2/monitoring/sources/'+encodeURIComponent(source.id)+'/host-metrics?'+query,{headers:{'x-request-id':crypto.randomUUID()},cache:'no-store'});
        return {directoryStatus:directoryResponse.status,source,metricsStatus:metricsResponse.status,metrics:await metricsResponse.json()};
      })()`);
      assert.equal(evidence.directoryStatus, 200);
      assert.ok(
        evidence.source,
        "the persisted source is returned by the real SQL-backed directory",
      );
      assert.equal(evidence.source.environmentId, environmentId);
      assert.equal(evidence.source.profile, "node-exporter-v1");
      assert.equal(evidence.source.authenticationMode, "none");
      assert.equal(evidence.source.credentialConfigured, false);
      assert.equal(evidence.metricsStatus, 200);
      assert.ok(
        evidence.metrics.hosts.length > 0,
        "HOST identity is read from real Prometheus samples",
      );
      assert.ok(
        evidence.metrics.hosts.some((host) =>
          host.metrics.some((series) => series.samples.length > 0),
        ),
        "at least one bounded HOST metric series contains real samples",
      );
      assert.ok(
        evidence.metrics.hosts.some((host) =>
          host.identity.some(
            (label) => label.name === prometheusHostLabel && label.value === prometheusHostId,
          ),
        ),
        "the returned stable host identity includes the configured Prometheus label value",
      );
      console.log(`live_monitoring_source_id=${evidence.source.id}`);
      console.log(`live_monitoring_host_count=${evidence.metrics.hosts.length}`);
      console.log(
        `live_monitoring_sample_counts=${JSON.stringify(evidence.metrics.hosts[0].metrics.map((series) => ({ metric: series.metric, count: series.samples.length, quality: series.quality })))}`,
      );

      await page.goto(
        `${origin}/#/realtime?env=${encodeURIComponent(environmentId)}&app=all&range=15m`,
      );
      try {
        await page.waitFor(
          `document.getElementById('host-metrics-title')?.textContent.includes('主机资源趋势')`,
          { timeoutMs: 15000, label: "realtime view mounts its independent HOST metrics section" },
        );
      } catch (error) {
        const diagnostic = await page.eval(`(()=>({
          href:location.href,
          title:document.title,
          rootText:document.querySelector('#root')?.innerText.slice(0,1600)??'',
          hostSection:document.querySelector('section[aria-labelledby="host-metrics-title"]')?.innerText.slice(0,800)??null,
          catalogRequests:performance.getEntriesByType('resource').map(item=>item.name).filter(name=>name.includes('/api/v1/observation/catalog')).slice(-3),
          hostMetricRequests:performance.getEntriesByType('resource').map(item=>item.name).filter(name=>name.includes('/host-metrics?')).slice(-3)
        }))()`);
        throw new Error(
          `${error instanceof Error ? error.message : error}; realtime=${JSON.stringify(diagnostic)}; consoleErrors=${JSON.stringify(page.consoleErrors)}`,
        );
      }
      await new Promise((resolve) => setTimeout(resolve, 1500));
      let chartDiagnostics = await page.eval(`(async()=>{
        const section=document.querySelector('section[aria-labelledby="host-metrics-title"]');
        const catalogResponse=await fetch('/api/v1/observation/catalog',{headers:{'x-request-id':crypto.randomUUID()},cache:'no-store'});
        const catalog=await catalogResponse.json();
        return {
          hash:location.hash,
          catalogStatus:catalogResponse.status,
          catalogEnvironments:catalog.environments?.map(item=>item.id)??null,
          title:section?.querySelector('#host-metrics-title')?.textContent??null,
          text:section?.innerText.slice(0,1000)??null,
          panels:section?.querySelectorAll('[data-panel]').length??null,
          images:section?.querySelectorAll('[role="img"]').length??null,
          svg:section?.querySelectorAll('svg').length??null,
          empty:[...(section?.querySelectorAll('[role="status"]')??[])].map(node=>node.textContent),
          metricReads:performance.getEntriesByType('resource').map(item=>item.name).filter(name=>name.includes('/host-metrics?')).slice(-3),
          hostMetricResponses:window.__t07MonitoringProbeResponses?.filter(item=>item.url.includes('/host-metrics?')).slice(-3)??[]
        };
      })()`);
      if (chartDiagnostics.images !== 4) {
        const chartUrl = `${origin}/#/realtime?env=${encodeURIComponent(environmentId)}&app=all&range=15m`;
        for (let attempt = 0; attempt < 8; attempt += 1) {
          await new Promise((resolve) => setTimeout(resolve, 2500));
          await page.goto(chartUrl);
          await page.waitFor(
            `document.getElementById('host-metrics-title')?.textContent.includes('主机资源趋势')`,
            { timeoutMs: 15000, label: "HOST chart section remains mounted during first scrape" },
          );
          chartDiagnostics = await page.eval(`(()=>{
            const section=document.querySelector('section[aria-labelledby="host-metrics-title"]');
            return {
              text:section?.innerText.slice(0,1000)??null,
              panels:section?.querySelectorAll('[data-panel]').length??null,
              images:section?.querySelectorAll('[role="img"]').length??null,
              svg:section?.querySelectorAll('svg').length??null,
              empty:[...(section?.querySelectorAll('[role="status"]')??[])].map(node=>node.textContent),
              metricReads:performance.getEntriesByType('resource').map(item=>item.name).filter(name=>name.includes('/host-metrics?')).slice(-3),
              hostMetricResponses:window.__t07MonitoringProbeResponses?.filter(item=>item.url.includes('/host-metrics?')).slice(-3)??[]
            };
          })()`);
          if (chartDiagnostics.images === 4) break;
        }
      }
      assert.equal(
        await page.count('section[aria-labelledby="host-metrics-title"] [role="img"]'),
        4,
        `CPU, memory bytes, memory ratio and load each read back into a chart: ${JSON.stringify(chartDiagnostics)}`,
      );
      assert.deepEqual(page.consoleErrors, []);
    } finally {
      await page.close();
    }
  },
);

test(
  "LIVE monitoring source: an unverified empty selector remains an honest empty HOST chart",
  { skip: !enabled || !adminPassword || !prometheusEndpoint },
  async () => {
    const page = await browser.newPage();
    const origin = new URL(E2E_BASE_URL).origin;
    let createdSource = null;
    try {
      await page.clearStorage(origin);
      await page.goto(`${origin}/#/login?app=all&range=1h`);
      try {
        await page.waitFor(
          `!!document.querySelector('.login-page input[autocomplete="username"]') || !!document.querySelector('.app-shell')`,
          {
            timeoutMs: 15000,
            label: "installed Console resolves login or the existing authenticated shell",
          },
        );
      } catch (error) {
        const state = await page.eval(
          `(()=>({href:location.href,title:document.title,readyState:document.readyState,rootText:document.querySelector('#root')?.innerText.slice(0,240)??'',scripts:[...document.scripts].map(script=>script.src)}))()`,
        );
        throw new Error(
          `${error instanceof Error ? error.message : error}; page=${JSON.stringify(state)}; consoleErrors=${JSON.stringify(page.consoleErrors)}`,
        );
      }
      if (await page.count('.login-page input[autocomplete="username"]')) {
        await page.type('.login-page input[autocomplete="username"]', "admin");
        await page.type('.login-page input[autocomplete="current-password"]', adminPassword);
        await page.clickByText("登录", ".login-page form button");
      }
      await page.waitFor(
        `location.hash.startsWith('#/overview') && !!document.querySelector('.app-shell')`,
        { timeoutMs: 15000, label: "Console confirms the fresh admin session" },
      );

      await page.goto(`${origin}/#/system?view=connections`);
      await page.waitFor(
        `location.hash.startsWith('#/system') && document.body.textContent.includes('主机监控数据源')`,
        { timeoutMs: 15000, label: "monitoring source registry is available" },
      );
      await page.clickByText("添加监控源", "button");
      await page.waitFor(`!!document.querySelector('dialog[open]')`);

      const runId = randomUUID();
      const displayName = `T07 Empty HOST ${runId.slice(0, 8)}`;
      const environmentId = `t07-empty-${runId}`;
      const missingJob = `sentinel-no-samples-${runId}`;
      await fillByLabel(page, "名称", displayName);
      await fillByLabel(page, "环境标识", environmentId);
      await fillByLabel(page, "Prometheus 服务地址", prometheusEndpoint);
      await fillByLabel(page, "实例身份标签", prometheusHostLabel);
      await fillByLabel(page, "采集任务标签名", "job");
      await fillByLabel(page, "采集任务标签值", missingJob);
      await page.clickByText("跳过连接检查并保存为未验证", "dialog[open] label");
      await page.clickByText("保存登记", "dialog[open] button");
      await page.waitFor(
        `!document.querySelector('dialog[open]') && document.body.textContent.includes(${JSON.stringify(displayName)})`,
        { timeoutMs: 15000, label: "unverified source is saved without claiming provider health" },
      );

      const directory = await page.eval(`(async()=>{
        const response=await fetch('/api/v2/monitoring/sources',{headers:{'x-request-id':crypto.randomUUID()},cache:'no-store'});
        return {status:response.status,body:await response.json()};
      })()`);
      assert.equal(directory.status, 200);
      createdSource =
        directory.body.items?.find((item) => item.displayName === displayName) ?? null;
      assert.ok(createdSource, "the exact source created by this browser journey is authoritative");
      assert.equal(createdSource.environmentId, environmentId);

      const noSampleRead = await page.eval(`(async()=>{
        const to=new Date(Date.now()-2000);
        const from=new Date(to.getTime()-60000);
        const query=new URLSearchParams({from:from.toISOString(),to:to.toISOString(),stepMs:'5000'});
        const response=await fetch('/api/v2/monitoring/sources/'+encodeURIComponent(${JSON.stringify(createdSource.id)})+'/host-metrics?'+query,{headers:{'x-request-id':crypto.randomUUID()},cache:'no-store'});
        return {status:response.status,body:await response.json()};
      })()`);
      assert.equal(noSampleRead.status, 200);
      assert.equal(
        noSampleRead.body.quality,
        "no_samples",
        `unexpected empty HOST response: ${JSON.stringify(noSampleRead.body)}`,
      );
      assert.equal(noSampleRead.body.reason, "missing_samples");
      assert.deepEqual(noSampleRead.body.hosts, []);

      await page.goto(
        `${origin}/#/realtime?env=${encodeURIComponent(environmentId)}&app=all&range=1h`,
      );
      await page.waitFor(
        `document.getElementById('host-metrics-title')?.textContent.includes('主机资源趋势')`,
        { timeoutMs: 15000, label: "realtime view mounts HOST charts for the empty environment" },
      );
      await page.waitFor(
        `(()=>{const section=document.querySelector('section[aria-labelledby="host-metrics-title"]');return section?.textContent.includes('此时间范围内没有主机样本') && section.querySelectorAll('[role="status"]').length>=4})()`,
        { timeoutMs: 20000, label: "all four HOST charts render explicit empty states" },
      );
      const chartState = await page.eval(`(()=>{
        const section=document.querySelector('section[aria-labelledby="host-metrics-title"]');
        const statuses=[...section.querySelectorAll('[role="status"]')].map(node=>node.textContent.trim());
        return {emptyMessages:statuses.filter(message=>message.includes('此时间范围内没有主机样本')).length,chartImages:section.querySelectorAll('[role="img"]').length,statuses};
      })()`);
      assert.equal(chartState.emptyMessages, 4, JSON.stringify(chartState));
      assert.equal(
        chartState.chartImages,
        0,
        "an empty source must not render a fabricated zero-valued chart",
      );
      assert.deepEqual(page.consoleErrors, []);
    } finally {
      if (createdSource) {
        const cookies = await page.send("Network.getCookies", { urls: [origin] });
        const csrfCookie = cookies.cookies?.find(
          (cookie) => cookie.name === "__Host-sentinel_csrf",
        );
        assert.ok(csrfCookie?.value, "the authenticated browser owns its CSRF cookie");
        const deletion = await page.eval(`(async()=>{
          const requestKey=crypto.randomUUID();
          const response=await fetch('/api/v2/monitoring/sources/commands',{
            method:'POST',
            headers:{'content-type':'application/json','x-request-id':crypto.randomUUID(),'idempotency-key':requestKey,'x-sentinel-csrf':${JSON.stringify(csrfCookie.value)}},
            body:JSON.stringify({kind:'delete',requestKey,sourceId:${JSON.stringify(createdSource.id)},expectedRevision:${JSON.stringify(createdSource.revision)}}),
            cache:'no-store'
          });
          return {status:response.status,body:await response.json()};
        })()`);
        assert.equal(deletion.status, 202, JSON.stringify(deletion));
        assert.equal(deletion.body.status, "completed", JSON.stringify(deletion));
      }
      await page.close();
    }
  },
);

test(
  "LIVE monitoring source: stopped exporter is stale, recovery restores real chart samples",
  {
    skip:
      !enabled ||
      !adminPassword ||
      !prometheusEndpoint ||
      !process.env.SENTINEL_T07_PROMETHEUS_CONTROL_URL ||
      !process.env.SENTINEL_T07_PROMETHEUS_CONTROL_JOB,
  },
  async () => {
    const page = await browser.newPage();
    const origin = new URL(E2E_BASE_URL).origin;
    const controlUrl = process.env.SENTINEL_T07_PROMETHEUS_CONTROL_URL;
    const controlJob = process.env.SENTINEL_T07_PROMETHEUS_CONTROL_JOB;
    let createdSource = null;
    const setExporterAvailability = async (available) => {
      const response = await fetch(controlUrl, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ available }),
        signal: AbortSignal.timeout(3000),
      });
      assert.equal(response.status, 204, `controlled exporter state=${available}`);
    };
    const readMetrics = async () => {
      const response = await page.eval(`(async()=>{
        try {
          const to=new Date();
          // The outage lasts longer than staleAfterSeconds. Keep the previous
          // scrape inside the query window so this checks stale retention, not
          // the separate no-samples state.
          const from=new Date(to.getTime()-90000);
          const query=new URLSearchParams({from:from.toISOString(),to:to.toISOString(),stepMs:'1000'});
          const result=await fetch('/api/v2/monitoring/sources/'+encodeURIComponent(${JSON.stringify(createdSource?.id ?? "")})+'/host-metrics?'+query,{headers:{'x-request-id':crypto.randomUUID()},cache:'no-store'});
          return {status:result.status,body:await result.json()};
        } catch(error) {
          return {status:0,body:null,error:error instanceof Error?error.name:'request_failed'};
        }
      })()`);
      return response;
    };
    try {
      await setExporterAvailability(true);
      await waitForPrometheusJob(controlJob);
      await page.clearStorage(origin);
      await page.goto(`${origin}/#/login?app=all&range=1h`);
      await page.waitFor(
        `!!document.querySelector('.login-page input[autocomplete="username"]') || !!document.querySelector('.app-shell')`,
        { timeoutMs: 15000, label: "Console resolves login before controlled HOST monitoring" },
      );
      if (await page.count('.login-page input[autocomplete="username"]')) {
        await page.type('.login-page input[autocomplete="username"]', "admin");
        await page.type('.login-page input[autocomplete="current-password"]', adminPassword);
        await page.clickByText("登录", ".login-page form button");
      }
      await page.waitFor(
        `location.hash.startsWith('#/overview') && !!document.querySelector('.app-shell')`,
        { timeoutMs: 15000, label: "Console confirms administrator session for HOST monitoring" },
      );

      await page.goto(`${origin}/#/system?view=connections`);
      await page.waitFor(
        `location.hash.startsWith('#/system') && document.body.textContent.includes('主机监控数据源')`,
        { timeoutMs: 15000, label: "monitoring-source registry is ready" },
      );
      await page.clickByText("添加监控源", "button");
      await page.waitFor(`!!document.querySelector('dialog[open]')`);
      const runId = randomUUID();
      const displayName = `T07 controlled HOST ${runId.slice(0, 8)}`;
      const testEnvironment = `t07-host-lifecycle-${runId}`;
      await fillByLabel(page, "名称", displayName);
      await fillByLabel(page, "环境标识", testEnvironment);
      await fillByLabel(page, "Prometheus 服务地址", prometheusEndpoint);
      await fillByLabel(page, "实例身份标签", prometheusHostLabel);
      await fillByLabel(page, "采集任务标签名", "job");
      await fillByLabel(page, "采集任务标签值", controlJob);
      await fillByLabel(page, "采集间隔（秒）", "1");
      await fillByLabel(page, "过期阈值（秒）", "30");
      await verifyPrometheusProbe(
        page,
        "controlled Prometheus target is available before registration",
      );
      await page.clickByText("保存登记", "dialog[open] button");
      await page.waitFor(
        `!document.querySelector('dialog[open]') && document.body.textContent.includes(${JSON.stringify(displayName)})`,
        { timeoutMs: 15000, label: "verified controlled HOST source is persisted" },
      );

      const directory = await page.eval(`(async()=>{
        const response=await fetch('/api/v2/monitoring/sources',{headers:{'x-request-id':crypto.randomUUID()},cache:'no-store'});
        const body=await response.json();
        return {status:response.status,source:body.items?.find(item=>item.displayName===${JSON.stringify(displayName)})??null};
      })()`);
      assert.equal(directory.status, 200);
      createdSource = directory.source;
      assert.ok(createdSource, "controlled HOST source is present in the SQL-backed directory");

      let beforeStop;
      for (let attempt = 0; attempt < 12; attempt += 1) {
        beforeStop = await readMetrics();
        if (
          beforeStop.status === 200 &&
          beforeStop.body.hosts.length === 1 &&
          beforeStop.body.hosts[0].metrics.every(
            (series) => series.samples.length > 0 && series.quality !== "stale",
          )
        )
          break;
        await new Promise((resolve) => setTimeout(resolve, 1000));
      }
      assert.equal(beforeStop.status, 200);
      assert.equal(beforeStop.body.hosts.length, 1);
      assert.ok(
        beforeStop.body.hosts[0].metrics.every((series) => series.samples.length > 0),
        "all supported host metric series have actual scrape samples before outage",
      );

      await setExporterAvailability(false);
      await new Promise((resolve) => setTimeout(resolve, 50000));
      let targetState = null;
      let targetReadFailure = null;
      for (let attempt = 0; attempt < 6; attempt += 1) {
        try {
          const stoppedTarget = await fetch(
            `${prometheusEndpoint}/api/v1/query?query=${encodeURIComponent(`up{job="${controlJob}"}`)}`,
            { signal: AbortSignal.timeout(8000) },
          );
          assert.equal(stoppedTarget.status, 200);
          targetState = await stoppedTarget.json();
          if (
            targetState.status === "success" &&
            targetState.data.result.some((item) => item.value?.[1] === "0")
          )
            break;
        } catch (error) {
          targetReadFailure = error instanceof Error ? error.name : String(error);
        }
        await new Promise((resolve) => setTimeout(resolve, 1000));
      }
      assert.equal(
        targetState?.status,
        "success",
        `Prometheus target read did not succeed: ${targetReadFailure}`,
      );
      assert.ok(
        targetState.data.result.some((item) => item.value?.[1] === "0"),
        `Prometheus confirms the controlled scrape target is down: ${JSON.stringify(targetState)}`,
      );
      let stale;
      for (let attempt = 0; attempt < 12; attempt += 1) {
        stale = await readMetrics();
        if (
          stale.status === 200 &&
          stale.body.hosts.length === 1 &&
          stale.body.hosts[0].metrics.every(
            (series) => series.quality === "stale" && series.samples.length > 0,
          )
        )
          break;
        await new Promise((resolve) => setTimeout(resolve, 1000));
      }
      assert.equal(stale.status, 200);
      assert.equal(
        stale.body.hosts.length,
        1,
        `stale HOST was not returned: ${JSON.stringify(stale)}`,
      );
      assert.ok(
        stale.body.hosts[0].metrics.every(
          (series) => series.quality === "stale" && series.samples.length > 0,
        ),
        `existing samples are retained as stale, not converted to zero: ${JSON.stringify(stale.body.hosts[0].metrics.map(({ metric, quality, samples }) => ({ metric, quality, count: samples.length })))}`,
      );

      await page.goto(
        `${origin}/#/realtime?env=${encodeURIComponent(testEnvironment)}&app=all&range=15m`,
      );
      try {
        await page.waitFor(
          `(()=>{const section=document.querySelector('section[aria-labelledby="host-metrics-title"]');return section && [...section.querySelectorAll('[role="status"]')].some(node=>node.textContent.includes('样本已陈旧')) && section.querySelectorAll('[role="img"]').length===4})()`,
          { timeoutMs: 60000, label: "HOST charts finish rendering four stale sample visualizations" },
        );
      } catch (error) {
        const diagnostic = await page.eval(`(()=>({
          statuses:[...(document.querySelector('section[aria-labelledby="host-metrics-title"]')?.querySelectorAll('[role="status"]')??[])].map(node=>node.textContent),
          images:document.querySelector('section[aria-labelledby="host-metrics-title"]')?.querySelectorAll('[role="img"]').length??0,
          scripts:[...document.scripts].map(item=>item.src),
          resources:performance.getEntriesByType('resource').map(item=>({name:item.name,duration:item.duration,transferSize:item.transferSize})).filter(item=>item.name.includes('nivo')||item.name.includes('assets/')).slice(-20),
          body:document.querySelector('section[aria-labelledby="host-metrics-title"]')?.innerText.slice(-1000)??''
        }))()`);
        throw new Error(`${error instanceof Error ? error.message : error}; chartDiagnostic=${JSON.stringify(diagnostic)}; consoleErrors=${JSON.stringify(page.consoleErrors)}`);
      }
      const staleChart = await page.eval(`(()=>{
        const section=document.querySelector('section[aria-labelledby="host-metrics-title"]');
        return {
          statuses:[...(section?.querySelectorAll('[role="status"]')??[])].map(node=>node.textContent.trim()),
          text:section?.innerText.slice(0,1000)??'',
          charts:section?.querySelectorAll('[role="img"]').length??0
        };
      })()`);
      assert.ok(
        staleChart.statuses.some((message) => message.includes("样本已陈旧")),
        JSON.stringify(staleChart),
      );
      assert.equal(
        staleChart.charts,
        4,
        `stale state keeps its four labeled chart panels mounted: ${JSON.stringify(staleChart)}`,
      );

      await setExporterAvailability(true);
      let recovered;
      for (let attempt = 0; attempt < 40; attempt += 1) {
        await new Promise((resolve) => setTimeout(resolve, 1000));
        recovered = await readMetrics();
        if (
          recovered.status === 200 &&
          recovered.body.hosts.length === 1 &&
          recovered.body.hosts[0].metrics.every(
            (series) => series.samples.length > 0 && series.quality !== "stale",
          )
        )
          break;
      }
      assert.equal(recovered.status, 200);
      assert.ok(
        recovered.body.hosts[0].metrics.every((series) => series.quality !== "stale"),
        "new Prometheus samples restore current values after the outage",
      );
      let recoveredChart;
      for (let attempt = 0; attempt < 12; attempt += 1) {
        await page.goto(
          `${origin}/#/realtime?env=${encodeURIComponent(testEnvironment)}&app=all&range=15m`,
        );
        await page.waitFor(
          `document.getElementById('host-metrics-title')?.textContent.includes('主机资源趋势')`,
          { timeoutMs: 15000, label: "HOST chart section is mounted after scrape recovery" },
        );
        await new Promise((resolve) => setTimeout(resolve, 1000));
        recoveredChart = await page.eval(`(()=>{
          const section=document.querySelector('section[aria-labelledby="host-metrics-title"]');
          return {charts:section?.querySelectorAll('[role="img"]').length??0,message:section?.querySelector('[role="status"]')?.textContent??''};
        })()`);
        if (recoveredChart.charts === 4 && !recoveredChart.message.includes("样本已陈旧")) break;
        await new Promise((resolve) => setTimeout(resolve, 2500));
      }
      assert.equal(recoveredChart.charts, 4);
      assert.ok(!recoveredChart.message.includes("样本已陈旧"));
      assert.deepEqual(page.consoleErrors, []);
      console.log(`live_monitoring_lifecycle_source_id=${createdSource.id}`);
      console.log(`live_monitoring_stale_target_query=up{job="${controlJob}"}=0`);
      console.log(`live_monitoring_recovery_host=${recovered.body.hosts[0].hostId}`);
    } finally {
      await setExporterAvailability(true).catch(() => undefined);
      if (createdSource) {
        const cookies = await page.send("Network.getCookies", { urls: [origin] });
        const csrfCookie = cookies.cookies?.find(
          (cookie) => cookie.name === "__Host-sentinel_csrf",
        );
        assert.ok(csrfCookie?.value, "authenticated browser retains CSRF protection for cleanup");
        const deletion = await page.eval(`(async()=>{
          const requestKey=crypto.randomUUID();
          const response=await fetch('/api/v2/monitoring/sources/commands',{
            method:'POST',headers:{'content-type':'application/json','x-request-id':crypto.randomUUID(),'idempotency-key':requestKey,'x-sentinel-csrf':${JSON.stringify(csrfCookie.value)}},
            body:JSON.stringify({kind:'delete',requestKey,sourceId:${JSON.stringify(createdSource.id)},expectedRevision:${JSON.stringify(createdSource.revision)}}),cache:'no-store'
          });
          return {status:response.status,body:await response.json()};
        })()`);
        assert.equal(deletion.status, 202, JSON.stringify(deletion));
        assert.equal(deletion.body.status, "completed", JSON.stringify(deletion));
      }
      await page.close();
    }
  },
);
