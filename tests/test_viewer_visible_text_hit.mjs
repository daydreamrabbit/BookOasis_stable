import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const source=fs.readFileSync('static/js/viewer/input_controller.js','utf8');
const fn=source.slice(source.indexOf('function isPointOnSelectableText('),source.indexOf('function isViewerRtlFlowActive('));
test('reader margin does not select invisible text from an adjacent column',()=>{
 const c=vm.createContext({document:{elementFromPoint:()=>({closest:()=>null}),caretRangeFromPoint:()=>{throw Error('must not snap to hidden text');}}});
 assert.equal(vm.runInContext(fn+'isPointOnSelectableText(1270,400)',c),false);
});
test('visible text remains selectable',()=>{
 const chunk={};
 const element={closest:()=>chunk};
 const document={elementFromPoint:()=>element,caretRangeFromPoint:()=>({startContainer:{nodeType:3,textContent:'text',parentElement:element}}),
   createRange:()=>({selectNodeContents:()=>{},getClientRects:()=>[{left:10,right:100,top:10,bottom:30}]})};
 const c=vm.createContext({document,Node:{TEXT_NODE:3}});
 assert.equal(vm.runInContext(fn+'isPointOnSelectableText(20,20)',c),true);
});
