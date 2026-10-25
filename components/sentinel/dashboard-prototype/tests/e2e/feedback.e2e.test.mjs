import {after,before,test} from 'node:test';
import assert from 'node:assert/strict';
import {mkdirSync,writeFileSync} from 'node:fs';
import {E2E_BASE_URL,connectIabBrowser} from './cdp.mjs';
import {gotoMockAdministrator} from './mock-auth.mjs';
let browser;
before(async()=>{browser=await connectIabBrowser();});after(async()=>{await browser?.close();});
async function withProbe(run){
  const page=await browser.newPage();
  try{
    await page.clearStorage(new URL(E2E_BASE_URL).origin);await gotoMockAdministrator(page, `${E2E_BASE_URL}/#/accounts`);await page.waitFor(`!!document.querySelector('[data-account-management] table')`);
    await page.eval(`(async()=>{const React=(await import('/node_modules/.vite/deps/react.js')).default;const {createRoot}=(await import('/node_modules/.vite/deps/react-dom_client.js')).default;const {FeedbackProbe}=await import('/tests/e2e/probes/FeedbackProbe.tsx');const host=document.createElement('section');host.id='feedback-probe';document.body.prepend(host);const root=createRoot(host);root.render(React.createElement(React.StrictMode,null,React.createElement(FeedbackProbe)));window.__feedbackCleanup=()=>{root.unmount();host.remove();};})()`);
    await page.waitFor(`!!document.querySelector('#feedback-probe output')`);await run(page);await page.eval(`window.__feedbackCleanup()`);assert.deepEqual(page.consoleErrors,[]);
  }finally{await page.close();}
}
test('反馈: 10 类资源状态正确保留或隐藏内容，拒绝/空结果不伪装成成功或零值',async()=>{
  await withProbe(async page=>{
    for(const status of ['idle','loading','refreshing','ready','empty','filtered-empty','partial','stale','error','denied']){
      await page.click(`#feedback-probe [data-query="${status}"]`);
      const retained=['ready','refreshing','partial','stale'].includes(status);
      assert.equal(await page.count('#feedback-probe [data-trusted]'),retained?1:0,status);
      assert.doesNotMatch(await page.text('#feedback-probe'),/SENSITIVE-RAW-ERROR/);
      if(status!=='ready'){
        assert.match(await page.text('#feedback-probe [data-query-probe]'),new RegExp(status));
        assert.equal(await page.count(`#feedback-probe [data-query-probe] [role="${['error','denied','stale','partial'].includes(status)?'alert':'status'}"]`),1,status);
      }
    }
    await page.click('#feedback-probe [data-query="error"]');
    await page.clickByText('重试读取');
    assert.equal(await page.eval(`JSON.parse(document.querySelector('#feedback-probe output').textContent).reads`),1);
  });
});
test('反馈: 429 retryAfterMs 到期前禁用人工读取，等待后恢复且不泄露错误详情',async()=>{
  await withProbe(async page=>{
    await page.click('#feedback-probe [data-query-rate-limited]');
    const retry='#feedback-probe [data-query-probe] button';
    assert.equal(await page.eval(`document.querySelector(${JSON.stringify(retry)}).disabled`),true);
    assert.equal(await page.eval(`JSON.parse(document.querySelector('#feedback-probe output').textContent).reads`),0);
    assert.doesNotMatch(await page.text('#feedback-probe'),/SENSITIVE-RATE-LIMIT-DETAIL/);
    await page.waitFor(`!document.querySelector(${JSON.stringify(retry)}).disabled`);
    await page.click(retry);
    assert.equal(await page.eval(`JSON.parse(document.querySelector('#feedback-probe output').textContent).reads`),1);
  });
});
test('反馈: 命令 unknown/conflict 只检查结果或读取新版本，不自动重放，也不泄露异常',async()=>{
  await withProbe(async page=>{
    for(const status of ['pending','success','error','conflict','result-unknown']){
      await page.click(`#feedback-probe [data-command="${status}"]`);
      assert.match(await page.text('#feedback-probe [data-command-probe]'),new RegExp(status));
      assert.doesNotMatch(await page.text('#feedback-probe'),/SENSITIVE-RAW-ERROR/);
      assert.equal(await page.count(`#feedback-probe [data-command-probe] [role="${['error','conflict','result-unknown'].includes(status)?'alert':'status'}"]`),1);
    }
    await page.clickByText('检查执行结果');
    assert.equal(await page.count('#feedback-probe [data-command-state="result-unknown"]'),1);
    await page.click('#feedback-probe [data-command="conflict"]');await page.clickByText('读取最新版本');
    assert.deepEqual(await page.eval(`JSON.parse(document.querySelector('#feedback-probe output').textContent)`),{reads:1,inspections:1});
    await page.click('#feedback-probe [data-command="idle"]');assert.equal(await page.count('#feedback-probe [data-command-state]'),0);
  });
});
test('反馈: 320px 长说明/动作不溢出，按钮可聚焦、点击目标及标题对比度合格，减少动画偏好生效',async()=>{
  await withProbe(async page=>{
    await page.send('Emulation.setDeviceMetricsOverride',{width:320,height:800,deviceScaleFactor:1,mobile:false});
    await page.send('Emulation.setEmulatedMedia',{features:[{name:'prefers-reduced-motion',value:'reduce'}]});
    await page.click('#feedback-probe [data-query="stale"]');await page.click('#feedback-probe [data-command="result-unknown"]');
    const buttons=await page.eval(`[...document.querySelectorAll('#feedback-probe .feedback button')].map(b=>{const r=b.getBoundingClientRect();return {width:r.width,height:r.height,left:r.left,right:r.right};})`);
    assert.ok(buttons.length===2&&buttons.every(r=>r.width>=24&&r.height>=24&&r.left>=0&&r.right<=321),JSON.stringify(buttons));
    await page.eval(`document.querySelector('#feedback-probe .feedback button').focus()`);
    assert.ok(await page.eval(`document.activeElement===document.querySelector('#feedback-probe .feedback button')`));
    assert.equal(await page.eval(`getComputedStyle(document.documentElement).scrollBehavior`),'auto');
    const colors=await page.eval(`(()=>{const h=document.querySelector('#feedback-probe h2');const layers=[];for(let parent=h;parent;parent=parent.parentElement)layers.unshift(getComputedStyle(parent).backgroundColor);const parse=color=>color.match(/[\\d.]+/g).map(Number);let background=[255,255,255];for(const layer of layers){const [r,g,b,a=1]=parse(layer);background=[r,g,b].map((v,i)=>v*a+background[i]*(1-a));}return {color:parse(getComputedStyle(h).color).slice(0,3),background};})()`);
    const lum=value=>{const [r,g,b]=value.map(v=>{v/=255;return v<=0.04045?v/12.92:((v+0.055)/1.055)**2.4;});return 0.2126*r+0.7152*g+0.0722*b;};
    const fg=lum(colors.color),bg=lum(colors.background),ratio=(Math.max(fg,bg)+0.05)/(Math.min(fg,bg)+0.05);assert.ok(ratio>=4.5,JSON.stringify({colors,ratio}));
    const directory=artifactDirectory('sentinel-f3-feedback-20261007');mkdirSync(directory,{recursive:true});writeFileSync(`${directory}/long-320.png`,await page.screenshot());
  });
});
import {artifactDirectory} from './artifacts.mjs';
