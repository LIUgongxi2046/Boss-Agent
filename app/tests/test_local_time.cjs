const assert=require('node:assert/strict');
const {test}=require('node:test');
const path=require('node:path');
const Module=require('node:module');
const root=path.resolve(__dirname,'../..');
const dependencies=path.join(root,'.work/product/nanobot/webui/node_modules');
const {buildSync}=require(path.join(dependencies,'esbuild'));
const compiled=buildSync({entryPoints:[path.join(root,'app/webui/local-time.ts')],bundle:true,write:false,platform:'node',format:'cjs',nodePaths:[dependencies]});
const loaded=new Module(path.join(root,'app/webui/local-time.cjs'));
loaded.filename=path.join(root,'app/webui/local-time.cjs');
loaded._compile(compiled.outputFiles[0].text,loaded.filename);
const {checkLocalTime,initialLocalTime}=loaded.exports;
const clock='2026-01-01T00:00:00Z';

test('所选地点与本人时区分别换算，保留跨日及完整UTC时差',()=>{
  const result=checkLocalTime('2026-10-26','08:30','Asia/Shanghai','',clock,'America/New_York');
  assert.equal(result.issue,'');assert.equal(result.value,'2026-10-26T08:30:00+08:00');
  assert.equal(result.utc,'2026-10-26T00:30:00.000Z');assert.equal(result.crossDay,true);assert.equal(result.daylight,false);
  const half=checkLocalTime('2026-10-26','08:30','Asia/Kolkata','',clock,'Asia/Shanghai');
  assert.equal(half.offset,'+05:30');assert.equal(half.utc,'2026-10-26T03:00:00.000Z');
});

test('夏令时开始时不存在的当地时间无法确认',()=>{
  const result=checkLocalTime('2026-03-08','02:30','America/New_York','',clock,'Asia/Shanghai');
  assert.equal(result.value,undefined);assert.match(result.issue,/不存在/);
  const adjacent=checkLocalTime('2026-03-08','03:30','America/New_York','',clock,'Asia/Shanghai');
  assert.equal(adjacent.value,'2026-03-08T03:30:00-04:00');assert.equal(adjacent.daylight,true);
});

test('夏令时结束时明确选择两次出现的当地时间',()=>{
  const result=checkLocalTime('2026-11-01','01:30','America/New_York','',clock,'Asia/Shanghai');
  assert.equal(result.value,undefined);assert.equal(result.choices.length,2);assert.match(result.issue,/两个UTC时差/);
  const choices=result.choices.map(choice=>checkLocalTime('2026-11-01','01:30','America/New_York',choice.value,clock,'Asia/Shanghai'));
  assert.deepEqual(new Set(choices.map(choice=>choice.offset)),new Set(['-04:00','-05:00']));
  assert.equal(Math.abs(Date.parse(choices[0].utc)-Date.parse(choices[1].utc)),3600000);
  const mismatched=checkLocalTime('2026-11-01','01:30','America/New_York','2026-11-01T01:31:00-04:00',clock,'Asia/Shanghai');
  assert.equal(mismatched.value,undefined);
});

test('半小时调整与跨越整日的时区变更采用实际时区规则',()=>{
  const overlap=checkLocalTime('2026-04-05','01:45','Australia/Lord_Howe','',clock,'Asia/Shanghai');
  assert.equal(overlap.choices.length,2);
  assert.equal(Math.abs(Date.parse(overlap.choices[0].value)-Date.parse(overlap.choices[1].value)),1800000);
  const skipped=checkLocalTime('2011-12-30','12:00','Pacific/Apia','','2011-01-01T00:00:00Z','Asia/Shanghai');
  assert.equal(skipped.value,undefined);assert.match(skipped.issue,/不存在/);
});

test('无效日期、时区、业务时钟及过期时间保留明确提示',()=>{
  for(const args of [
    ['2026-02-30','12:00','Asia/Shanghai','',clock,'Asia/Shanghai'],
    ['2026-10-26','12:00','Invalid/Zone','',clock,'Asia/Shanghai'],
    ['2026-10-26','12:00','Asia/Shanghai','',undefined,'Asia/Shanghai'],
    ['2026-10-26','12:00','Asia/Shanghai','','2026-01-01','Asia/Shanghai'],
    ['2025-10-26','12:00','Asia/Shanghai','',clock,'Asia/Shanghai'],
  ]){const result=checkLocalTime(...args);assert.equal(result.value,undefined);assert.ok(result.issue);}
});

test('已有完整期限保持同一时刻及夏令时选择，取消无需改写原值',()=>{
  const original='2026-11-01T01:30:00-05:00';
  const initial=initialLocalTime(original,'America/New_York');
  assert.equal(initial.issue,'');assert.equal(initial.date,'2026-11-01');assert.equal(initial.time,'01:30:00');
  const restored=checkLocalTime(initial.date,initial.time,'America/New_York',initial.occurrence,clock,'Asia/Shanghai');
  assert.equal(restored.value,original);
  assert.match(initialLocalTime('2026-10-26T12:00:00','Asia/Shanghai').issue,/无效/);
  const precise=initialLocalTime('2026-10-26T12:00:00.123+08:00','Asia/Shanghai');
  assert.equal(checkLocalTime(precise.date,precise.time,'Asia/Shanghai',precise.occurrence,clock,'Asia/Shanghai').value,'2026-10-26T12:00:00.123+08:00');
});
