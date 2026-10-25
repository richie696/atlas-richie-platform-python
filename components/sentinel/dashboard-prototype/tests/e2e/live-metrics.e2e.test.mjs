import { after, before, test } from "node:test";
import assert from "node:assert/strict";
import { E2E_BASE_URL, connectE2EBrowser } from "./cdp.mjs";

const enabled = process.env.SENTINEL_E2E_LIVE_METRICS === "1";
const adminPassword = process.env.SENTINEL_LIVE_E2E_PASSWORD;
const workers = [
  {
    language: "Java",
    baseUrl: process.env.SENTINEL_T07_JAVA_DEMO_URL,
    environmentId: process.env.SENTINEL_T07_JAVA_ENVIRONMENT_ID,
    appId: process.env.SENTINEL_T07_JAVA_APP_ID ?? "sentinel-java-demo",
  },
  {
    language: "Go",
    baseUrl: process.env.SENTINEL_T07_GO_DEMO_URL,
    environmentId: process.env.SENTINEL_T07_GO_ENVIRONMENT_ID,
    appId: process.env.SENTINEL_T07_GO_APP_ID ?? "sentinel-go-demo",
  },
];
let browser;

before(async () => {
  if (enabled) browser = await connectE2EBrowser();
});

after(async () => {
  await browser?.close();
});

test(
  "LIVE OBS-01: Java and Go Metrics V2 facts match the realtime charts",
  {
    skip:
      !enabled ||
      !adminPassword ||
      workers.some((worker) => !worker.baseUrl || !worker.environmentId),
  },
  async () => {
    const page = await browser.newPage();
    const origin = new URL(E2E_BASE_URL).origin;
    const metrics = ["http_qps", "tps", "rt_p95", "blocked_ratio", "cpu_ratio", "memory_ratio"];
    try {
      for (const worker of workers) {
        for (let request = 0; request < 12; request += 1) {
          const response = await fetch(`${worker.baseUrl}/api/delay?ms=120`, {
            signal: AbortSignal.timeout(4000),
          });
          assert.ok(
            response.status === 200 || response.status === 429,
            `${worker.language} demo returned a bounded business response (${response.status})`,
          );
          await response.arrayBuffer();
        }
      }

      await page.goto(`${origin}/#/login?app=all&range=1h`);
      await page.waitFor(`!!document.querySelector('.login-page input[autocomplete="username"]')`);
      await page.type('.login-page input[autocomplete="username"]', "admin");
      await page.type('.login-page input[autocomplete="current-password"]', adminPassword);
      await page.clickByText("登录", ".login-page form button");
      try {
        await page.waitFor(`!!document.querySelector('.app-shell')`, {
          timeoutMs: 15000,
          label: "live Console mounts the authenticated application shell",
        });
      } catch (error) {
        const diagnostics = await page.eval(`(async()=>{
          const response=await fetch('/api/v1/auth/me',{headers:{'x-request-id':crypto.randomUUID()},cache:'no-store'});
          return {href:location.href,identityStatus:response.status,identity:await response.json(),body:document.body?.innerText?.slice(0,1200)??"",loginFeedback:[...document.querySelectorAll('[role=alert],[data-login-feedback]')].map(node=>node.textContent.trim()).filter(Boolean)};
        })()`);
        throw new Error(
          `${error instanceof Error ? error.message : error}; authentication diagnostics=${JSON.stringify(diagnostics)}`,
        );
      }
      const identity = await page.eval(`(async()=>{
        const response=await fetch('/api/v1/auth/me',{headers:{'x-request-id':crypto.randomUUID()},cache:'no-store'});
        return {status:response.status,body:await response.json()};
      })()`);
      assert.equal(identity.status, 200);
      assert.equal(identity.body.roleId, "admin");

      for (const worker of workers) {
        await page.send("Page.addScriptToEvaluateOnNewDocument", {
          source: `(()=>{
          const original=window.fetch.bind(window);window.__liveObservationResponses=[];
          window.fetch=async (...args)=>{
            const response=await original(...args);
            const request=args[0] instanceof Request ? args[0].url : String(args[0]);
            const path=new URL(request,location.href).pathname;
            if(path==='/api/v1/metrics/query'||path==='/api/v1/fleet/overview'||/^\\/api\\/v1\\/instances\\/[^/]+$/.test(path)){
              const clone=response.clone();
              let body=null;
              try{body=await clone.json()}catch{}
              window.__liveObservationResponses.push({path,status:response.status,requestId:response.headers.get('x-request-id'),body});
            }
            return response;
          };
        })();`,
        });

        // The fleet summary must be a live, application-scoped response too;
        // it must not inherit the all-applications scope from the login URL.
        await page.goto(
          `${origin}/#/overview?env=${encodeURIComponent(worker.environmentId)}&app=${encodeURIComponent(worker.appId)}&range=1h`,
        );
        await page.waitFor(
          `(()=>{const responses=window.__liveObservationResponses??[];return responses.some(item=>item.path==='/api/v1/fleet/overview'&&item.status===200&&item.body?.query?.context?.environmentId===${JSON.stringify(worker.environmentId)}&&item.body?.query?.context?.appId===${JSON.stringify(worker.appId)})&&!!document.querySelector('[data-metric-card="http_qps"]')})()`,
          { timeoutMs: 20000, label: `${worker.language} live overview reads app-scoped metrics` },
        );
        const overview = await page.eval(
          `(()=>[...(window.__liveObservationResponses??[])].reverse().find(item=>item.path==='/api/v1/fleet/overview'&&item.status===200&&item.body?.query?.context?.environmentId===${JSON.stringify(worker.environmentId)}&&item.body?.query?.context?.appId===${JSON.stringify(worker.appId)}))()`,
        );
        assert.equal(overview.body.query.context.environmentId, worker.environmentId);
        assert.equal(overview.body.query.context.appId, worker.appId);
        const overviewQualities = new Map(
          overview.body.metrics.summary.map((reading) => [reading.metric, reading.quality]),
        );
        for (const metric of [
          "http_qps",
          "tps",
          "rt_p95",
          "blocked_ratio",
          "cpu_ratio",
          "memory_ratio",
        ])
          assert.ok(
            overviewQualities.has(metric),
            `${worker.language} overview includes ${metric}`,
          );
        assert.equal(
          await page.eval(
            `document.querySelector('[data-metric-card="http_qps"]')?.dataset.quality`,
          ),
          overviewQualities.get("http_qps"),
          `${worker.language} overview card quality matches live fleet response`,
        );

        // The instance directory is separately scoped and its explicit process
        // detail must preserve incarnation identity before rendering metrics.
        await page.goto(
          `${origin}/#/applications?env=${encodeURIComponent(worker.environmentId)}&app=${encodeURIComponent(worker.appId)}&range=1h`,
        );
        await page.waitFor(`!!document.querySelector('[data-observed-instance] button')`, {
          timeoutMs: 20000,
          label: `${worker.language} live instance directory loads`,
        });
        const instanceId = await page.eval(
          `document.querySelector('[data-observed-instance]')?.dataset.observedInstance ?? null`,
        );
        const processEpoch = await page.eval(
          `document.querySelector('[data-observed-instance] td:nth-child(2) small')?.textContent?.trim() ?? null`,
        );
        assert.ok(instanceId, `${worker.language} directory returns a live instance identity`);
        assert.ok(processEpoch, `${worker.language} directory returns a process incarnation`);
        await page.click(`[data-observed-instance="${instanceId}"] button`);
        await page.waitFor(
          `(()=>{const responses=window.__liveObservationResponses??[];return responses.some(item=>item.path.startsWith('/api/v1/instances/')&&item.status===200&&item.body?.instance?.instanceId===${JSON.stringify(instanceId)}&&item.body?.query?.context?.environmentId===${JSON.stringify(worker.environmentId)}&&item.body?.query?.context?.appId===${JSON.stringify(worker.appId)})&&!!document.querySelector('[data-instance-receipt]')})()`,
          {
            timeoutMs: 20000,
            label: `${worker.language} live process detail matches selected instance`,
          },
        );
        const processObservation = await page.eval(
          `(()=>[...(window.__liveObservationResponses??[])].reverse().find(item=>item.path.startsWith('/api/v1/instances/')&&item.status===200&&item.body?.instance?.instanceId===${JSON.stringify(instanceId)}))()`,
        );
        assert.equal(processObservation.body.instance.processEpoch, processEpoch);
        assert.equal(processObservation.body.query.context.instanceId, instanceId);
        assert.equal(processObservation.body.query.processEpoch, processEpoch);
        assert.ok(
          processObservation.body.metrics === null ||
            processObservation.body.metrics.summary.every(
              (reading) => reading.value === null || Number.isFinite(reading.value),
            ),
          `${worker.language} process metrics are finite or explicitly unavailable`,
        );

        await page.goto(
          `${origin}/#/realtime?env=${encodeURIComponent(worker.environmentId)}&app=${encodeURIComponent(worker.appId)}&range=1h`,
        );
        await page.waitFor(
          `location.hash.startsWith('#/realtime') && !!document.querySelector('.app-shell')`,
          { timeoutMs: 10000, label: `${worker.language} live realtime route is mounted` },
        );
        let observed;
        try {
          observed = await page.waitFor(
            `(()=>{
            const response=[...(window.__liveObservationResponses??[])].reverse().find(item=>{
              if(item.path!=='/api/v1/metrics/query'||item.status!==200||item.body?.query?.context?.environmentId!==${JSON.stringify(worker.environmentId)}||item.body?.query?.context?.appId!==${JSON.stringify(worker.appId)})return false;
              return ['http_qps','tps','rt_p95'].every(metric=>item.body.series.find(series=>series.metric===metric)?.samples.some(sample=>Number.isFinite(sample.value)));
            });
            const cards=[...document.querySelectorAll('[data-metric-card]')];
            const charts=document.querySelectorAll('[role="img"]').length;
            return response&&cards.some(card=>card.dataset.metricCard==='http_qps')&&charts>0&&{response,cards:cards.map(card=>({metric:card.dataset.metricCard,quality:card.dataset.quality})),charts};
          })()`,
            {
              // A fresh reporter needs two snapshots before counter and
              // histogram deltas become durable rollups. Keep observing the
              // real dashboard poll until persisted samples arrive instead
              // of accepting the first (valid but empty) query response.
              timeoutMs: 60000,
              label: `${worker.language} live query reaches the app-scoped chart with persisted samples`,
            },
          );
        } catch (error) {
          const diagnostics = await page.eval(`({
            href:location.href,
            body:document.body?.innerText?.slice(0,1600)??"",
            queries:window.__liveObservationResponses??[],
            cards:[...document.querySelectorAll('[data-metric-card]')].map(card=>({metric:card.dataset.metricCard,quality:card.dataset.quality})),
            chartCount:document.querySelectorAll('[role="img"]').length
          })`);
          throw new Error(
            `${error instanceof Error ? error.message : error}; live metrics diagnostics=${JSON.stringify(diagnostics)}`,
          );
        }
        assert.equal(observed.response.status, 200);
        assert.equal(observed.response.body.query.context.environmentId, worker.environmentId);
        assert.equal(observed.response.body.query.context.appId, worker.appId);
        assert.deepEqual(observed.response.body.query.metrics, metrics);
        assert.ok(
          observed.charts >= 1,
          `${worker.language} realtime route renders an accessible chart`,
        );

        const byMetric = new Map(
          observed.response.body.summary.map((reading) => [reading.metric, reading]),
        );
        for (const metric of ["http_qps", "tps", "rt_p95", "blocked_ratio"]) {
          const reading = byMetric.get(metric);
          assert.ok(reading, `${worker.language} response includes ${metric}`);
          assert.ok(
            reading.value === null || Number.isFinite(reading.value),
            `${worker.language} ${metric} is a finite value or explicitly unavailable`,
          );
        }
        for (const metric of ["http_qps", "tps", "rt_p95"]) {
          const series = observed.response.body.series.find((item) => item.metric === metric);
          assert.ok(
            series?.samples.some((sample) => Number.isFinite(sample.value)),
            `${worker.language} ${metric} has a real persisted time-series sample`,
          );
        }
        const uiQualities = new Map(observed.cards.map((card) => [card.metric, card.quality]));
        for (const reading of observed.response.body.summary) {
          assert.equal(
            uiQualities.get(reading.metric),
            reading.quality,
            `${worker.language} chart card quality matches the exact API response`,
          );
        }
        const memory = byMetric.get("memory_ratio");
        if (memory && ["unavailable", "not_integrated"].includes(memory.quality)) {
          assert.equal(
            memory.value,
            null,
            `${worker.language} missing memory is not plotted as a fabricated zero`,
          );
          const memorySeries = observed.response.body.series.find(
            (series) => series.metric === "memory_ratio",
          );
          assert.ok(
            memorySeries?.samples.every((sample) => sample.value === null),
            `${worker.language} missing memory has no fabricated chart samples`,
          );
        }
        console.log(
          `live_metrics_${worker.language.toLowerCase()}_request_id=${observed.response.requestId}`,
        );
        console.log(
          `live_metrics_${worker.language.toLowerCase()}_as_of=${observed.response.body.asOf}`,
        );
        console.log(
          `live_metrics_${worker.language.toLowerCase()}_qualities=${JSON.stringify(observed.response.body.summary.map(({ metric, quality, value }) => ({ metric, quality, value })))}`,
        );
      }

      // Pages that are not metric dashboards remain useful in live mode even
      // when their own datasets are empty; they must not inherit a global
      // monitoring-read failure state from unrelated observation endpoints.
      for (const [route, query] of [
        [
          "faults",
          `env=${encodeURIComponent(workers[0].environmentId)}&app=${encodeURIComponent(workers[0].appId)}&range=1h`,
        ],
        ["system", "view=connections"],
      ]) {
        await page.goto(`${origin}/#/${route}?${query}`);
        const pageState = await page.waitFor(
          `(()=>{const title=document.querySelector('main h1');return !!document.querySelector('.app-shell')&&!!title?.textContent?.trim()&&{title:title.textContent.trim(),body:document.querySelector('main')?.innerText??''}})()`,
          { timeoutMs: 15000, label: `live ${route} page remains available` },
        );
        assert.doesNotMatch(
          pageState.body,
          /读取失败；未得到可确认数据|failed to read; no confirmed data/i,
          `${route} must not be replaced by a global metrics failure screen`,
        );
      }

      // A valid but unobserved application exercises live missing-coverage
      // semantics: identity remains visible, nulls stay null, and the page is
      // not replaced by an all-page error.
      const missingWorker = workers[0];
      const missingAppId = `sentinel-unobserved-${Date.now()}`;
      await page.send("Page.addScriptToEvaluateOnNewDocument", {
        source: `(()=>{
          const original=window.fetch.bind(window);window.__missingMetricResponses=[];
          window.fetch=async (...args)=>{
            const response=await original(...args);
            const request=args[0] instanceof Request ? args[0].url : String(args[0]);
            if(new URL(request,location.href).pathname==='/api/v1/metrics/query'){
              const clone=response.clone();let body=null;try{body=await clone.json()}catch{}
              window.__missingMetricResponses.push({status:response.status,body});
            }
            return response;
          };
        })();`,
      });
      await page.goto(
        `${origin}/#/realtime?env=${encodeURIComponent(missingWorker.environmentId)}&app=${encodeURIComponent(missingAppId)}&range=1h`,
      );
      const missing = await page.waitFor(
        `(()=>{const response=[...(window.__missingMetricResponses??[])].reverse().find(item=>item.status===200&&item.body?.query?.context?.environmentId===${JSON.stringify(missingWorker.environmentId)}&&item.body?.query?.context?.appId===${JSON.stringify(missingAppId)});return response&&document.querySelectorAll('[data-metric-card]').length>=6&&{response,cards:[...document.querySelectorAll('[data-metric-card]')].map(card=>({metric:card.dataset.metricCard,quality:card.dataset.quality})),body:document.querySelector('main')?.innerText??''}})()`,
        { timeoutMs: 20000, label: "live unobserved application renders explicit missing metrics" },
      );
      assert.equal(missing.response.body.query.context.appId, missingAppId);
      assert.ok(
        missing.response.body.summary.every((reading) => reading.value === null),
        "unobserved application summaries remain null rather than fabricated zeroes",
      );
      assert.ok(
        missing.response.body.series.every((series) =>
          series.samples.every((sample) => sample.value === null),
        ),
        "unobserved application charts have no fabricated samples",
      );
      assert.ok(missing.cards.every((card) => card.quality !== "available"));
      assert.match(missing.body, /实时监控|Live monitoring/i);
      assert.deepEqual(page.consoleErrors, []);
    } finally {
      await page.close();
    }
  },
);
