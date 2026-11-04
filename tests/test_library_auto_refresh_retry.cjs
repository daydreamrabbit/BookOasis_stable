const fs=require('fs'),vm=require('vm'),assert=require('assert');
const source=fs.readFileSync(process.argv[2]||'static/js/library_auto_refresh.js','utf8').replace(/^import .*;\r?\n/gm,'').replace(/^export /gm,'');
const trackerCode=fs.readFileSync('static/js/library_revision_tracker.js','utf8').replace(/^export /gm,'');
const calls={home:0,counts:0,list:0},delays=[];
let countsFail=true;
const context={state:{currentLibraryType:'general',currentLibraryId:'home'},
 document:{hidden:false,addEventListener(){},getElementById(){return null},querySelector(){return null}},
 window:{addEventListener(){},dispatchEvent(){},invalidateBookListAfterScan(){calls.list++;return Promise.resolve(true)},invalidateDashboardData(){},async loadDashboardData(){calls.home++},async refreshLibraryCounts(){calls.counts++;if(countsFail)throw Error('count request failure');return true}},
 console:{debug(){}},EventSource:class{addEventListener(){}},setTimeout(fn,delay){delays.push(delay);return 1},clearTimeout(){},Date,Map,Event:class{},getComputedStyle:()=>({display:'none'})};
vm.createContext(context);vm.runInContext(trackerCode+'\n'+source,context);
const observe=n=>vm.runInContext(`tracker.observe({general:'${n}'})`,context);
(async()=>{
 observe(1);observe(2);
 await context.checkLibraryChanges();await context.checkLibraryChanges();
 assert.equal(calls.home,1,'count failure must not refetch already refreshed home');
 assert.deepEqual(delays,[3000,6000]);
 countsFail=false;await context.checkLibraryChanges();
 assert.equal(calls.home,1);assert.equal(calls.counts,3);
 await context.checkLibraryChanges();assert.equal(calls.counts,3,'idle must send no requests');
 observe(3);await context.checkLibraryChanges();assert.equal(calls.home,2,'new change must refresh');
 countsFail=true;observe(4);await context.checkLibraryChanges();
 observe(5);await context.checkLibraryChanges();assert.equal(calls.home,4,'new change during retry must not be suppressed');
 countsFail=false;await context.checkLibraryChanges();assert.equal(calls.home,4);
 context.document.hidden=true;observe(6);const before={...calls};await context.checkLibraryChanges();assert.deepEqual(calls,before);
 context.document.hidden=false;context.state.currentLibraryId='settings';await context.checkLibraryChanges();assert.deepEqual(calls,before);
 context.state.currentLibraryId='home';await context.checkLibraryChanges();assert.equal(calls.home,5);
 console.log('PASS retry deduplication, backoff, recovery, new revisions, idle/hidden/settings and preserved pending changes');
})().catch(e=>{console.error(e);process.exitCode=1});
