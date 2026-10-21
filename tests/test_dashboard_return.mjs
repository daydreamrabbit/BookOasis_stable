import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';

const dashboard = readFileSync(new URL('../static/js/dashboard.js', import.meta.url), 'utf8');
const detail = readFileSync(new URL('../static/js/detail/index.js', import.meta.url), 'utf8');
test('empty rows cannot reuse ready flags or skip rendering', () => {
  const code = dashboard.slice(dashboard.indexOf('function hasDashboardContent'), dashboard.indexOf('function showDashboardErrorIfEmpty'));
  const ctx = vm.createContext({});
  vm.runInContext(code, ctx);
  const row = {__dashboardReady:true,childElementCount:0,querySelector:()=>null,__dashboardSignature:'general:[]'};
  assert.equal(ctx.hasDashboardContent(row),false);
  let renders=0;
  ctx.renderDashboardRowIfChanged(row,'general',[],()=>renders++);
  assert.equal(renders,1);
});
test('detail return resumes home requests even without a category change', () => {
  const code = detail.slice(detail.indexOf('export function goBackToList')).replace('export function','function');
  let loads=0;
  const ctx=vm.createContext({detailRequestSerial:0,history:{},state:{currentLibraryId:'home'},
    document:{querySelector:()=>null,getElementById:()=>null,documentElement:{},body:{}},
    window:{matchMedia:()=>({matches:false}),loadDashboardData:()=>loads++,scrollTo:()=>{},location:{hash:''}},
    updateCurrentCategoryIndicator:()=>{},switchActiveView:()=>{},console,
    requestAnimationFrame:fn=>fn(),setTimeout:fn=>fn()});
  vm.runInContext(code,ctx);
  ctx.goBackToList(false);
  assert.equal(loads,1);
});
