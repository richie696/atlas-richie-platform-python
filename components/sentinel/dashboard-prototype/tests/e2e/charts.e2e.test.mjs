import {after,before,test} from 'node:test';
import assert from 'node:assert/strict';
import {mkdirSync,writeFileSync} from 'node:fs';
import {E2E_BASE_URL,connectIabBrowser} from './cdp.mjs';
import {gotoMockAdministrator} from './mock-auth.mjs';

let browser;
before(async()=>{browser=await connectIabBrowser();});
after(async()=>{await browser?.close();});
async function withProbe(run) {
  const page=await browser.newPage();
  try {
    await page.clearStorage(new URL(E2E_BASE_URL).origin);
    await gotoMockAdministrator(page, `${E2E_BASE_URL}/#/accounts`);
    await page.waitFor(`!!document.querySelector('[data-account-management] [data-console-table-scroll]')`);
    await page.eval(`(async()=>{
      const React=(await import('/node_modules/.vite/deps/react.js')).default;
      const {createRoot}=(await import('/node_modules/.vite/deps/react-dom_client.js')).default;
      const {ChartProbe}=await import('/tests/e2e/probes/ChartProbe.tsx');
      const host=document.createElement('section');host.id='chart-probe';document.body.prepend(host);
      const original=document.documentElement.getAttribute('style');
      const root=createRoot(host);root.render(React.createElement(React.StrictMode,null,React.createElement(ChartProbe)));
      window.__chartCleanup=()=>{root.unmount();host.remove();if(original===null)document.documentElement.removeAttribute('style');else document.documentElement.setAttribute('style',original);};
    })()`);
    await page.waitFor(`!!document.querySelector('#chart-probe svg[role="img"]')`);
    await run(page);
    await page.eval(`window.__chartCleanup()`);
    assert.deepEqual(page.consoleErrors,[]);
  } finally {await page.close();}
}
const noBadGeometry=`![...document.querySelectorAll('#chart-probe svg *')].some(e=>[...e.attributes].some(a=>/NaN|Infinity/.test(a.value)))`;
async function screenshot(page,name){
  const directory=artifactDirectory('sentinel-f3-charts-20261007');mkdirSync(directory,{recursive:true});writeFileSync(`${directory}/${name}.png`,await page.screenshot());
}

test('Nivo: 缺测不归零、双轴原始单位、文本摘要和实际发布标记',async()=>{
  await withProbe(async page=>{
    assert.ok(await page.eval(noBadGeometry));
    const svgText=await page.eval(`document.querySelector('#chart-probe svg').textContent`);
    assert.match(svgText,/Deployment-42/);assert.doesNotMatch(svgText,/Ignored-outside/);
    assert.ok(await page.eval(`(()=>{const s=document.querySelector('#chart-probe svg'),id=s.getAttribute('aria-describedby');return !!id&&document.getElementById(id)?.tagName==='SUMMARY';})()`));
    await page.click('#chart-probe summary');
    const rows=await page.eval(`[...document.querySelectorAll('#chart-probe tbody tr')].map(r=>r.textContent)`);
    assert.equal(rows.length,5);assert.match(rows[2],/缺测.*缺测/);
    assert.match(rows[4],/250.*12%/);
    assert.ok(await page.eval(`[...document.querySelectorAll('#chart-probe svg path')].some(p=>(p.getAttribute('d')?.match(/M/g)||[]).length>1)`),'missing observations must break the line');
    await screenshot(page,'gaps-table');
  });
});
test('Nivo: 空序列、单点零值及重复时间不会产生伪造曲线或无效坐标',async()=>{
  await withProbe(async page=>{
    await page.click('#chart-probe [data-mode="empty"]');
    await page.waitFor(`!!document.querySelector('#chart-probe [role="status"]')`);
    assert.match(await page.eval(`document.querySelector('#chart-probe [role="status"]').textContent`),/没有观测/);
    assert.equal(await page.count('#chart-probe svg'),0);
    await page.click('#chart-probe [data-mode="constant"]');
    await page.waitFor(`!!document.querySelector('#chart-probe svg[role="img"]')`);
    assert.ok(await page.eval(noBadGeometry));
    assert.ok(await page.count('#chart-probe svg circle')>0,'a single valid point must remain visible');
    await page.click('#chart-probe [data-mode="invalid"]');
    await page.waitFor(`!!document.querySelector('#chart-probe [role="status"]')`);
    assert.match(await page.eval(`document.querySelector('#chart-probe [role="status"]').textContent`),/无效/);
    assert.equal(await page.count('#chart-probe svg'),0);
  });
});
test('Nivo: 双轴悬浮提示显示原始百分比而非归一化坐标',async()=>{
  await withProbe(async page=>{
    const target=await page.eval(`(()=>{const r=[...document.querySelectorAll('#chart-probe svg rect[data-ref]')].at(-1).getBoundingClientRect();return {x:r.left+r.width/2,y:r.top+r.height/2};})()`);
    await page.send('Input.dispatchMouseEvent',{type:'mouseMoved',x:target.x,y:target.y});
    await page.waitFor(`!!document.querySelector('#chart-probe .chart-tooltip')`);
    const text=await page.eval(`document.querySelector('#chart-probe .chart-tooltip').textContent`);
    assert.match(text,/14:04/);assert.match(text,/HTTP QPS: 250/);assert.match(text,/请求拦截率: 12%/);
    await screenshot(page,'dual-axis-tooltip');
  });
});
test('Nivo: 安装新皮肤后 revision 刷新已挂载图表，不复用首屏永久缓存',async()=>{
  await withProbe(async page=>{
    await page.click('#chart-probe [data-theme]');
    await page.waitFor(`[...document.querySelectorAll('#chart-probe svg path')].some(p=>p.getAttribute('stroke')==='#ff00ff')`);
    assert.ok(await page.eval(`[...document.querySelectorAll('#chart-probe svg text')].some(p=>p.getAttribute('fill')==='#00ffaa'||p.style.fill==='rgb(0, 255, 170)')`));
    assert.ok(await page.eval(noBadGeometry));
  });
});
for(const width of [320,1280]) test(`Nivo ${width}px: 时间戳跨天、同钟点独立身份与容器缩放`,async()=>{
  await withProbe(async page=>{
    await page.send('Emulation.setDeviceMetricsOverride',{width,height:800,deviceScaleFactor:1,mobile:false});
    await page.click('#chart-probe [data-mode="timestamp"]');
    await page.waitFor(`document.querySelector('#chart-probe svg[role="img"]')?.getBoundingClientRect().width<=${width}`);
    await page.click('#chart-probe summary');
    const times=await page.eval(`[...document.querySelectorAll('#chart-probe tbody th')].map(r=>r.textContent)`);
    assert.equal(times.length,3);assert.notEqual(times[0],times[2],'repeated wall clock labels need date context');
    const ticks=await page.eval(`[...document.querySelectorAll('#chart-probe svg g')].filter(g=>g.querySelector(':scope > text')?.textContent?.includes('10/')).map(g=>g.getAttribute('transform')).filter(Boolean)`);
    const positions=ticks.map(value=>Number(value.match(/translate\(([^,]+)/)?.[1])).filter(Number.isFinite);
    assert.equal(positions.length,width===320?2:3,JSON.stringify(ticks));
    if(width!==320) assert.ok(Math.abs((positions[1]-positions[0])/(positions[2]-positions[0])-0.25)<0.02,'irregular sampling must use elapsed time, not equal category spacing');
    assert.ok(await page.eval(noBadGeometry));
    const rect=await page.eval(`(()=>{const r=document.querySelector('#chart-probe svg').getBoundingClientRect();return {left:r.left,right:r.right,width:r.width};})()`);
    assert.ok(rect.left>=0&&rect.right<=width+1,JSON.stringify(rect));
    await screenshot(page,`timestamp-${width}`);
  });
});
import {artifactDirectory} from './artifacts.mjs';
