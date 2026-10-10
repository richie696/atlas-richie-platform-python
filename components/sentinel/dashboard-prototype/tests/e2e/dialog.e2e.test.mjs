import {after,before,test} from 'node:test';
import assert from 'node:assert/strict';
import {mkdirSync,writeFileSync} from 'node:fs';
import {E2E_BASE_URL,launchBrowser} from './cdp.mjs';

let browser;
before(async()=>{browser=await launchBrowser();});
after(async()=>{await browser?.close();});

async function withProbe(run) {
  const page=await browser.newPage();
  try {
    await page.clearStorage(new URL(E2E_BASE_URL).origin);
    await page.goto(`${E2E_BASE_URL}/#/accounts`);
    await page.waitFor(`!!document.querySelector('[data-account-management] table')`);
    await page.eval(`(async()=>{
      const React=(await import('/node_modules/.vite/deps/react.js')).default;
      const {createRoot}=(await import('/node_modules/.vite/deps/react-dom_client.js')).default;
      const {DialogProbe}=await import('/tests/e2e/probes/DialogProbe.tsx');
      const host=document.createElement('section');host.id='dialog-probe';document.body.prepend(host);
      const root=createRoot(host);root.render(React.createElement(React.StrictMode,null,React.createElement(DialogProbe)));
      window.__dialogCleanup=()=>{root.unmount();host.remove();};
    })()`);
    await page.waitFor(`!!document.querySelector('#dialog-probe output')`);
    await run(page);
    await page.eval(`window.__dialogCleanup()`);
    assert.deepEqual(page.consoleErrors,[]);
  } finally {await page.close();}
}
async function press(page,key,code,virtual) {
  await page.send('Input.dispatchKeyEvent',{type:'keyDown',key,code,windowsVirtualKeyCode:virtual,...(key==='Enter'?{text:'\r',unmodifiedText:'\r'}:{})});
  await page.send('Input.dispatchKeyEvent',{type:'keyUp',key,code,windowsVirtualKeyCode:virtual});
}
async function opened(page) {
  await page.click('#dialog-probe [data-action="open"]');
  await page.waitFor(`!!document.querySelector('dialog[open]')`);
  await page.eval(`(async()=>{await Promise.all(document.getAnimations().filter(a=>a.playState==='running'&&Number.isFinite(a.effect?.getTiming().iterations)).map(a=>a.finished.catch(()=>{})));})()`);
}
const state=`JSON.parse(document.querySelector('#dialog-probe output').textContent)`;

for(const width of [320,360,768,1280]) test(`DialogFrame ${width}px: 长文案及内容只滚动 body，标题与动作保持可见`,async()=>{
  await withProbe(async page=>{
    await page.send('Emulation.setDeviceMetricsOverride',{width,height:720,deviceScaleFactor:1,mobile:false});
    await page.click('#dialog-probe [data-action="length"]');
    await opened(page);
    const measure=`(()=>{
      const d=document.querySelector('dialog[open]'),b=d.querySelector('.astryx-layout-content'),h=d.querySelector('.astryx-layout-header'),f=d.querySelector('.astryx-layout-footer');
      const rect=element=>{const r=element.getBoundingClientRect();return {top:r.top,bottom:r.bottom,left:r.left,right:r.right,width:r.width,height:r.height};};
      return {dialog:rect(d),body:rect(b),header:rect(h),footer:rect(f),overflow:b.scrollHeight-b.clientHeight,scroll:b.scrollTop};
    })()`;
    const before=await page.eval(measure);
    assert.ok(before.dialog.left>=0&&before.dialog.right<=width+1&&before.dialog.top>=0&&before.dialog.bottom<=720,JSON.stringify(before));
    assert.ok(before.overflow>100,'long content has no independent body scroll');
    assert.ok(before.header.top>=before.dialog.top&&before.footer.bottom<=before.dialog.bottom+1,'frame chrome escaped the surface');
    await page.send('Input.dispatchMouseEvent',{type:'mouseWheel',x:Math.round(before.body.left+before.body.width/2),y:Math.round(before.body.top+before.body.height/2),deltaX:0,deltaY:400});
    await page.waitFor(`document.querySelector('dialog[open] .astryx-layout-content').scrollTop>0`);
    const after=await page.eval(measure);
    assert.ok(Math.abs(before.header.top-after.header.top)<1&&Math.abs(before.footer.top-after.footer.top)<1,'header/footer moved with body');
    const directory=artifactDirectory('sentinel-f3-dialog-20261007');mkdirSync(directory,{recursive:true});writeFileSync(`${directory}/long-${width}.png`,await page.screenshot());
  });
});

test('DialogFrame: 原生 Enter 只提交一次，pending 禁止 dismiss，完成后返回触发器',async()=>{
  await withProbe(async page=>{
    await page.send('Emulation.setDeviceMetricsOverride',{width:320,height:720,deviceScaleFactor:1,mobile:false});
    await opened(page);
    assert.ok(await page.eval(`document.querySelector('dialog[open]').contains(document.activeElement)`),'initial focus is outside modal');
    await page.type('dialog[open] input','sample-resource');
    await press(page,'Enter','Enter',13);
    await page.waitFor(`${state}.isBusy&&${state}.submits===1`);
    assert.equal(await page.eval(`document.querySelector('dialog[open]').getAttribute('aria-busy')`),'true');
    assert.equal(await page.count('dialog[open] .astryx-layout-header button[aria-label]'),0,'busy close icon must be absent');
    assert.ok(await page.eval(`document.querySelector('dialog[open] [data-action="cancel"]').disabled`));
    assert.ok(await page.eval(`(()=>{const d=document.querySelector('dialog[open]').getBoundingClientRect();return [...document.querySelectorAll('dialog[open] .dialog-frame-actions button')].every(b=>{const r=b.getBoundingClientRect();return r.left>=d.left&&r.right<=d.right&&r.bottom<=d.bottom;});})()`),'busy actions overflow narrow surface');
    await press(page,'Escape','Escape',27);
    assert.equal(await page.count('dialog[open]'),1);
    await press(page,'Enter','Enter',13);
    assert.equal(await page.eval(`${state}.submits`),1);
    await page.click('dialog[open] [data-action="finish"]');
    await page.waitFor(`!document.querySelector('dialog[open]')`);
    assert.equal(await page.eval(`document.activeElement?.getAttribute('data-action')`),'open');
  });
});

test('DialogFrame: Tab/Shift+Tab 不进入弹窗后方的页面',async()=>{
  await withProbe(async page=>{
    await opened(page);
    for(const modifiers of [0,8]) {
      for(let index=0;index<8;index++) {
        await page.send('Input.dispatchKeyEvent',{type:'keyDown',key:'Tab',code:'Tab',windowsVirtualKeyCode:9,modifiers});
        await page.send('Input.dispatchKeyEvent',{type:'keyUp',key:'Tab',code:'Tab',windowsVirtualKeyCode:9,modifiers});
        assert.ok(await page.eval(`document.querySelector('dialog[open]').contains(document.activeElement)`),`focus escaped modal: modifiers=${modifiers}, step=${index}`);
      }
    }
  });
});

test('DialogFrame: form backdrop 不关闭，Escape 关闭后恢复焦点并保留调用方草稿',async()=>{
  await withProbe(async page=>{
    await opened(page);
    await page.type('dialog[open] input','kept-draft');
    await page.send('Input.dispatchMouseEvent',{type:'mousePressed',x:5,y:5,button:'left',clickCount:1});
    await page.send('Input.dispatchMouseEvent',{type:'mouseReleased',x:5,y:5,button:'left',clickCount:1});
    assert.equal(await page.count('dialog[open]'),1);
    await press(page,'Escape','Escape',27);
    await page.waitFor(`!document.querySelector('dialog[open]')`);
    assert.equal(await page.eval(`document.activeElement?.getAttribute('data-action')`),'open');
    await opened(page);
    assert.equal(await page.value('dialog[open] input'),'kept-draft');
  });
});

test('Astryx locale: 官方关闭标签随同一 i18next 切换，打开的 Dialog 不丢字段、URL 或提交状态',async()=>{
  await withProbe(async page=>{
    await opened(page);
    await page.type('dialog[open] input','kept-while-translating');
    const hash=await page.eval('location.hash');
    for(const [locale,label] of [['zh-CN','关闭'],['en-US','Close'],['ja-JP','閉じる'],['zh-CN','关闭']]) {
      await page.eval(`(async()=>{const {default:i18n}=await import('/src/app/i18n/config.ts');await i18n.changeLanguage(${JSON.stringify(locale)});})()`);
      await page.waitFor(`document.querySelector('dialog[open] .astryx-layout-header button')?.getAttribute('aria-label')===${JSON.stringify(label)}`);
      assert.equal(await page.value('dialog[open] input'),'kept-while-translating');
      assert.equal(await page.eval('location.hash'),hash);
      assert.equal(await page.eval(`${state}.submits`),0);
      assert.equal(await page.count('dialog[open]'),1);
    }
    await page.click('dialog[open] .astryx-layout-header button');
    await page.waitFor(`!document.querySelector('dialog[open]')`);
    assert.equal(await page.eval(`document.activeElement?.getAttribute('data-action')`),'open');
  });
});

test('账号弹窗: Selector 内的 Escape 只关闭下拉，第二次 Escape 关闭 Dialog',async()=>{
  const page=await browser.newPage();
  try {
    await page.clearStorage(new URL(E2E_BASE_URL).origin);
    await page.goto(`${E2E_BASE_URL}/#/accounts`);
    await page.waitFor(`!!document.querySelector('[data-account-management] table')`);
    await page.clickByText('新增账号');
    await page.waitFor(`!!document.querySelector('dialog[open]')`);
    await page.click('dialog[open] button[role="combobox"]');
    await page.waitFor(`[...document.querySelectorAll('[role="option"]')].some(o=>o.offsetParent)`);
    await press(page,'Escape','Escape',27);
    await page.waitFor(`![...document.querySelectorAll('[role="option"]')].some(o=>o.offsetParent)`);
    assert.equal(await page.count('dialog[open]'),1,'nested dismissal closed two layers');
    assert.ok(await page.eval(`document.querySelector('dialog[open]').contains(document.activeElement)`));
    await press(page,'Escape','Escape',27);
    await page.waitFor(`!document.querySelector('dialog[open]')`);
    assert.deepEqual(page.consoleErrors,[]);
  } finally {await page.close();}
});
import {artifactDirectory} from './artifacts.mjs';
