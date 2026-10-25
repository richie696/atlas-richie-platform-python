import assert from "node:assert/strict";
import {test} from "node:test";
import {buildTrendPlot, formatTrendTime, formatTrendValue, trendDisplayUnit, trendTickValues} from "../../src/shared/ui/charts/trendPlot.ts";
import {createChartThemeStore} from "../../src/shared/ui/charts/chartThemeStore.ts";
import {FALLBACK_CHART_TOKENS, buildChartTheme, annotationStyle} from "../../src/shared/ui/charts/chartTheme.ts";

test("F3 charts: empty and missing series have finite nondegenerate domains, not fabricated zeros",()=>{
  const empty=buildTrendPlot([],"qps");
  assert.deepEqual(empty.domain,[0,1]); assert.equal(empty.problem,null);
  const missing=buildTrendPlot([{time:"a",qps:null},{time:"b"},{time:"c",qps:NaN},{time:"d",qps:Infinity}],"qps");
  assert.deepEqual(missing.points.map(p=>p.primary),[null,null,null,null]);
  assert.deepEqual(missing.domain,[0,1]);
});
test("F3 charts: frozen input, zero/constant/single observations and bounded tick density",()=>{
  const input=Object.freeze(Array.from({length:100},(_,i)=>Object.freeze({time:String(i),qps:0})));
  const result=buildTrendPlot(input,"qps");
  assert.deepEqual(result.domain,[-1,1]); assert.ok(result.ticks.length<=8);
  assert.equal(result.ticks[0],"0");assert.equal(result.ticks.at(-1),"99");
  assert.deepEqual(buildTrendPlot([{time:"a",qps:20}],"qps").domain,[19,21]);
  assert.equal(input[0].qps,0);
});
test("F3 charts: a common axis includes both series; the second axis preserves raw units and gaps",()=>{
  const data=[{time:"a",qps:100,blocked:1},{time:"b",qps:200,blocked:null},{time:"c",qps:150,blocked:10}];
  assert.deepEqual(buildTrendPlot(data,"qps","blocked").domain,[1,200]);
  const result=buildTrendPlot(data,"qps","blocked",true);
  assert.deepEqual(result.domain,[100,200]);
  assert.deepEqual(result.secondaryDomain,[1,10]);
  assert.deepEqual(result.points.map(p=>[p.secondary,p.secondaryY]),[[1,100],[null,null],[10,200]]);
  assert.deepEqual(buildTrendPlot(data,"qps","blocked",false,[0,100]).domain,[0,100]);
});
test("F3 charts: timestamps distinguish repeated clock labels, while duplicate/invalid/mixed/unsorted identity is rejected",()=>{
  const first=Date.UTC(2026,9,7,1,30);
  const second=first+24*60*60*1000;
  const plot=buildTrendPlot([{time:"01:30",timestampMs:first,qps:1},{time:"01:30",timestampMs:second,qps:2}],"qps");
  assert.equal(plot.problem,null);assert.notEqual(plot.points[0].id,plot.points[1].id);
  assert.deepEqual(plot.xDomain,[first,second]);
  assert.deepEqual(buildTrendPlot([{timestampMs:first,qps:0}],"qps").xDomain,[first-30000,first+30000]);
  for(const data of [[{time:""}], [{timestampMs:NaN}],[{timestampMs:8.65e15}],[{timestampMs:first},{time:"a"}],[{timestampMs:second},{timestampMs:first}]]) assert.equal(buildTrendPlot(data,"qps").problem,"invalid_time");
  assert.equal(buildTrendPlot([{time:"a"},{time:"a"}],"qps").problem,"ambiguous_time");
  assert.equal(buildTrendPlot([{timestampMs:first},{timestampMs:first}],"qps").problem,"ambiguous_time");
});
test("F3 charts: invalid domains and duplicate metric identities fail explicitly rather than emitting NaN/Infinity",()=>{
  for(const domain of [[1,1],[2,1],[0,Infinity],[NaN,1],[-Number.MAX_VALUE,Number.MAX_VALUE]]) assert.equal(buildTrendPlot([{time:"a",qps:1}],"qps",undefined,false,domain).problem,"invalid_domain");
  assert.equal(buildTrendPlot([{time:"a",qps:-Number.MAX_VALUE},{time:"b",qps:Number.MAX_VALUE}],"qps").problem,"invalid_domain");
  assert.equal(buildTrendPlot([{time:"a",qps:1}],"qps","qps").problem,"invalid_metric");
});
test("F3 charts: locale formatting does not change identity or invent TPS",()=>{
  assert.equal(formatTrendValue(1234.5,"en-US"," ms"),"1,234.5 ms");
  assert.equal(formatTrendTime("14:02","ja-JP"),"14:02");
  for(const locale of ["en-US","zh-CN","ja-JP"]) {
    assert.ok(formatTrendTime(Date.UTC(2026,9,7,1,30),locale,true).length>5);
    assert.ok(formatTrendValue(50,locale,"%",true).endsWith("%"));
  }
});
test("F3 charts: byte observations share a readable decimal-scaled unit without changing source data",()=>{
  assert.deepEqual(trendDisplayUnit("B",[null,900]),{unit:"B",divisor:1});
  assert.deepEqual(trendDisplayUnit("B",[1000]),{unit:"KB",divisor:1000});
  assert.deepEqual(trendDisplayUnit("B",[1000 ** 2]),{unit:"MB",divisor:1000 ** 2});
  const bytes=4_000_000_000;
  const display=trendDisplayUnit("B",[bytes]);
  assert.deepEqual(display,{unit:"GB",divisor:1000 ** 3});
  assert.equal(formatTrendValue(bytes/display.divisor,"en-US",display.unit),"4 GB");
  const localizedCapacityLabel=formatTrendValue(bytes/display.divisor,"zh-CN",display.unit,true);
  assert.equal(localizedCapacityLabel,"4 GB","capacity labels must use readable units, not locale compact notation");
  assert.doesNotMatch(localizedCapacityLabel,/亿|万/);
  const screenshotValue=40_000_000_000;
  const screenshotUnit=trendDisplayUnit("bytes",[screenshotValue]);
  const screenshotAxisLabel=formatTrendValue(screenshotValue/screenshotUnit.divisor,"zh-CN",screenshotUnit.unit,true);
  assert.equal(screenshotAxisLabel,"40 GB","large host-memory ticks must not render as 亿B");
  assert.deepEqual(trendDisplayUnit("bytes",[bytes]),display,"Console wire byte unit scales too");
  assert.deepEqual(trendDisplayUnit(" byte ",[bytes]),display,"unit whitespace is normalized");
  assert.deepEqual(trendDisplayUnit("%",[bytes]),{unit:"%",divisor:1});
});
test("F3 chart theme: immutable snapshots update once per effective skin change and unsubscribe on cleanup",()=>{
  let current=FALLBACK_CHART_TOKENS,calls=0;
  const store=createChartThemeStore(()=>current);
  const unsubscribe=store.subscribe(()=>calls++);
  assert.strictEqual(store.getServerSnapshot(),FALLBACK_CHART_TOKENS);
  const initial=store.getSnapshot();store.refresh();assert.equal(calls,0);
  current={...current,series:{...current.series,primary:"#ff00ff"},annotationLine:"#ffaa00"};
  store.refresh();assert.equal(calls,1);assert.notStrictEqual(store.getSnapshot(),initial);
  assert.equal(store.getSnapshot().series.primary,"#ff00ff");
  assert.equal(annotationStyle(store.getSnapshot()).stroke,"#ffaa00");
  assert.equal(buildChartTheme(store.getSnapshot()).axis.ticks.text.fill,current.axisText);
  current={...current,series:{...current.series}};store.refresh();assert.equal(calls,1);
  unsubscribe();current={...current,axisText:"#aabbcc"};store.refresh();assert.equal(calls,1);
  assert.strictEqual(createChartThemeStore().getSnapshot(),initial,"new provider must not inherit another provider's skin");
});
test("F3 chart ticks: container width and actual elapsed time determine label density",()=>{
  const plot=buildTrendPlot(Array.from({length:61},(_,index)=>({time:String(index),qps:index})),"qps");
  const narrow=trendTickValues(plot,180,60),wide=trendTickValues(plot,600,60);
  assert.deepEqual(narrow,["0","20","40","60"]);assert.ok(wide.length>narrow.length);
  assert.deepEqual(trendTickValues(plot,0,60),["0","60"]);
  const irregular=buildTrendPlot([{timestampMs:1000},{timestampMs:1001},{timestampMs:2000}],"qps");
  assert.deepEqual(trendTickValues(irregular,500,100),["1000","2000"]);
});
