import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const source=fs.readFileSync('static/js/viewer/inline_tts.js','utf8');
const fn=source.slice(source.indexOf('function isRangeVisible('),source.indexOf('async function applyTtsPosition('));
for(const [name,rect,expected] of [
 ['next page remains clipped',{left:800,right:1000,top:10,bottom:30,width:200,height:20},false],
 ['text is below image viewport',{left:10,right:100,top:600,bottom:620,width:90,height:20},false],
 ['text is visible',{left:10,right:100,top:20,bottom:40,width:90,height:20},true],
]) test(name,()=>{
 const context=vm.createContext({range:{getClientRects:()=>[rect]},wrapper:{getBoundingClientRect:()=>({left:0,right:800,top:0,bottom:600})}});
 assert.equal(vm.runInContext(fn+'isRangeVisible(range,wrapper)',context),expected);
});
