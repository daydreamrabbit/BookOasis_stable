const fs=require('fs'),path=require('path'),vm=require('vm'),assert=require('assert');
const root=process.argv[2]||path.resolve(__dirname,'..');
const api=fs.readFileSync(path.join(root,'static/js/api.js'),'utf8');
const code=api.slice(api.indexOf('let userSettingsRequest'),api.indexOf('// 홈 화면 플러그인 배치 모드')).replace(/^export /gm,'');
let now=1000,calls=[],mode='ok',blocked,setting='first';
const ctx={Date:{now:()=>now},FormData,fetch:async(url,options={})=>{
 calls.push(options.method||'GET');
 if(options.method==='POST')return {json:async()=>({success:true})};
 if(mode==='fail')throw Error('offline');
 if(mode==='block')return new Promise(resolve=>{blocked=resolve});
 return {json:async()=>({success:true,settings:{VALUE:setting}})};
}};vm.createContext(ctx);vm.runInContext(code,ctx);
(async()=>{
 const [a,b]=await Promise.all([ctx.fetchUserSettings(),ctx.fetchUserSettings()]);assert.equal(calls.length,1);a.settings.VALUE='mutated';assert.equal(b.settings.VALUE,'first');
 now+=500;assert.equal((await ctx.fetchUserSettings()).settings.VALUE,'first');assert.equal(calls.length,1);
 now+=1100;setting='second';assert.equal((await ctx.fetchUserSettings()).settings.VALUE,'second');assert.equal(calls.length,2);
 await ctx.updateUserSetting('VALUE','third');setting='third';assert.equal((await ctx.fetchUserSettings()).settings.VALUE,'third');assert.deepEqual(calls,['GET','GET','POST','GET']);
 ctx.invalidateUserSettingsCache();mode='block';const old=ctx.fetchUserSettings();await Promise.resolve();mode='ok';await ctx.updateUserSetting('VALUE','fourth');setting='fourth';blocked({json:async()=>({success:true,settings:{VALUE:'stale'}})});await old;assert.equal((await ctx.fetchUserSettings()).settings.VALUE,'fourth','pre-save request must not repopulate cache');
 ctx.invalidateUserSettingsCache();mode='fail';await assert.rejects(ctx.fetchUserSettings());mode='ok';assert.equal((await ctx.fetchUserSettings()).settings.VALUE,'fourth');
 const insights=fs.readFileSync(path.join(root,'static/js/dashboard_insights.js'),'utf8');const start=insights.indexOf('export async function loadDashboardInsights');const end=insights.indexOf('\nfunction ',start);
 let requests=0,activities=0;
 const scope={state:{currentLibraryId:'all'},window:{},document:{querySelector:()=>null},localStorage:{getItem:()=>null},loadDashboardActivity:()=>activities++,fetch:async()=>{requests++;return {ok:true,json:async()=>({success:false})}},console};vm.createContext(scope);vm.runInContext(insights.slice(start,end).replace('export ',''),scope);
 await scope.loadDashboardInsights();assert.equal(requests,0);assert.equal(activities,0);
 scope.state.currentLibraryId='home';await scope.loadDashboardInsights();assert.equal(requests,1);assert.equal(activities,1);
 console.log('PASS settings concurrent sharing, independent data, TTL, write invalidation, stale race, failure recovery and home-only insights');
})().catch(e=>{console.error(e);process.exitCode=1});
