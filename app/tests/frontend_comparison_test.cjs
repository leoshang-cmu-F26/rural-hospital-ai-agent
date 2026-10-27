const fs = require('fs'), vm = require('vm'), assert = require('assert');
class Element {
    constructor(tag) { this.tagName=tag; this.children=[]; this.attributes={}; this._text=''; this.value=''; this.disabled=false; this.hidden=false; this.className=''; this.classList={add:(name)=>{this.className+=' '+name}}; }
    appendChild(child) { this.children.push(child); return child; }
    insertBefore(child, before) { const index=this.children.indexOf(before); if(index<0) return this.appendChild(child); this.children.splice(index,0,child); return child; }
    append(...children) { children.forEach(c=>this.appendChild(c)); }
    set textContent(value) { this._text=String(value); this.children=[]; }
    get textContent() { return this._text+this.children.map(c=>c.textContent).join(''); }
    set innerHTML(value) { if(value!=='') throw Error('Unsafe HTML interpolation'); this.children=[]; this._text=''; }
    setAttribute(k,v) { this.attributes[k]=v; }
    addEventListener() {} focus() {} remove() {}
    querySelector(selector) { return find(this,n=>n.className.includes(selector.slice(1)))[0] || null; }
}
function find(root,predicate) {return [root,...root.children.flatMap(c=>find(c,predicate))].filter(predicate);}
const nodes={}, requests=[];
const context={document:{createElement:tag=>new Element(tag),createTextNode:text=>{let n=new Element('#text');n.textContent=text;return n},getElementById:id=>nodes[id]??=new Element('div')},
    window:{addEventListener(){}},console,URL,TextDecoder,Date,setInterval,clearInterval,
    fetch:async(url,options)=>{
        requests.push(JSON.parse(options.body));
        const pair = [{facility_name:'Mile Bluff',facility_id:'520109'},
                      {facility_name:'Reedsburg',facility_id:'521351'}];
        const message = JSON.parse(options.body).message;
        const events = message === 'Select a single hospital'
            ? [{type:'context',current_facility:pair[1]}, {type:'result',response:'Selected Reedsburg'}]
            : message === 'Fresh chat' ? [{type:'result',response:'Which hospitals?'}]
            : [{type:'comparison_context',comparison_facilities:pair},
               {type:'warnings',warnings:[{code:'non_rural_hospital',facility_id:'521351',facility_name:'Reedsburg',message:'CMS classifies this hospital as urban in 2024. <script>unsafe</script>',action:'Continue analysis; do not call it rural.'}]},
               {type:'evidence',sections:[
                  {key:'520109:financials',label:'Mile Bluff — Financials',status:'available',source:'CMS'},
                  {key:'521351:financials',label:'Reedsburg — Financials',status:'available',source:'CMS'}]},
               {type:'result',response:'## Comparison\n\n| Hospital | Year |\n| --- | --- |\n| Mile Bluff | 2024 |\n| Reedsburg | 2024 |'}];
        let done=false;
        return {ok:true,body:{getReader(){return {read:async()=>done?{done:true}:(done=true,{done:false,value:Buffer.from(events.map(JSON.stringify).join('\n')+'\n')}),cancel:async()=>{},releaseLock(){}}}}};
    }};
vm.createContext(context);
vm.runInContext(fs.readFileSync(process.argv[2]+'/markdown.js','utf8'),context);
vm.runInContext(fs.readFileSync(process.argv[2]+'/app.js','utf8'),context);
context.output=new Element('div');
vm.runInContext('renderMarkdown("## Title\\n\\n**Bold** and `code`\\n\\n[Bad](javascript:alert) <img src=x onerror=alert(1)>\\n\\n| A | B |\\n| --- | --- |\\n| 1 | 2 |",output)',context);
assert.equal(find(context.output,n=>n.tagName==='h3').length,1);
assert.equal(find(context.output,n=>n.tagName==='strong').length,1);
assert.equal(find(context.output,n=>n.tagName==='table').length,1);
assert.equal(find(context.output,n=>n.tagName==='img'||n.tagName==='script'||n.tagName==='a').length,0);
assert(context.output.textContent.includes('<img'));
(async()=>{
    nodes['message-input'].value='Compare both hospitals';
    await vm.runInContext('sendMessage()',context);
    assert(nodes['current-facility'].textContent.includes('Mile Bluff'));
    assert(nodes['current-facility'].textContent.includes('Reedsburg'));
    assert(nodes['chat-box'].textContent.includes('CMS classifies this hospital as urban'));
    assert.equal(find(nodes['chat-box'],n=>n.tagName==='script').length,0);
    for(let i=0;i<4;i++) {
        nodes['message-input'].value='Compare their financial trends';
        await vm.runInContext('sendMessage()',context);
    }
    assert.equal(requests[4].comparison_facilities.length,2);
    assert.equal(requests[4].current_facility,null);
    assert.equal(requests[4].history.length,6);
    assert.equal(requests[4].comparison_facilities[0].facility_id,'520109');
    assert.equal(requests[4].comparison_facilities[1].facility_id,'521351');
    nodes['message-input'].value='Select a single hospital';
    await vm.runInContext('sendMessage()',context);
    nodes['message-input'].value='Analyze its financial distress';
    await vm.runInContext('sendMessage()',context);
    assert.equal(requests[6].comparison_facilities.length,0);
    assert.equal(requests[6].current_facility.facility_id,'521351');
    vm.runInContext('clearChat()',context);
    nodes['message-input'].value='Fresh chat';
    await vm.runInContext('sendMessage()',context);
    assert.equal(requests[7].comparison_facilities.length,0);
    assert.equal(requests[7].history.length,0);
    assert.equal(requests[7].current_facility,null);
    assert.equal(nodes['current-facility'].hidden,true);
    assert.equal(nodes['send-button'].disabled,false);
    console.log('Frontend comparison passed: pair identity, follow-ups past history limit, single target switch, clear chat and tables');
})().catch(error=>{console.error(error);process.exitCode=1;});
