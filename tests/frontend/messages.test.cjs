/* Run the actual client against a synthetic DOM and controllable network. */
const {test}=require('node:test');
const assert=require('node:assert/strict');
const {readFileSync}=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const {webcrypto}=require('node:crypto');
const {parseHTML}=require('linkedom');
const frontend=path.resolve(__dirname,'../../cloudflare-pages/frontend');

function client(){
  const {document}=parseHTML(readFileSync(path.join(frontend,'index.html'),'utf8'));
  const requests=[],timers=new Map(),storage=new Map(),socket=[];
  let timerId=0;
  const context=vm.createContext({
    document,console,crypto:webcrypto,AbortController,URL,
    window:{innerWidth:1200,addEventListener(){}},navigator:{},
    matchMedia:()=>({matches:false}),
    localStorage:{getItem:key=>storage.get(key)??null,setItem:(key,value)=>storage.set(key,String(value)),removeItem:key=>storage.delete(key)},
    setTimeout:(fn,delay)=>{timers.set(++timerId,{fn,delay});return timerId;},
    clearTimeout:id=>timers.delete(id),setInterval:()=>0,clearInterval(){},
    showUpdatesPage(){},showPhonePermissions(){},
    avatarContent:()=>'<span>M</span>',
    fetch:(url,options={})=>{
      if(String(url).endsWith('/read'))return Promise.resolve({ok:true,json:async()=>({ok:true})});
      return new Promise((resolve,reject)=>{
        const item={url,options,body:options.body?JSON.parse(options.body):null,resolve:data=>resolve({ok:true,json:async()=>data}),reject};
        requests.push(item);
        options.signal?.addEventListener('abort',()=>reject(new DOMException('Timed out','AbortError')),{once:true});
      });
    },
    collectSocket:data=>socket.push(JSON.parse(data)),
  });
  for(const name of ['app.js','features.js'])vm.runInContext(readFileSync(path.join(frontend,name),'utf8'),context,{filename:name});
  const run=code=>vm.runInContext(code,context);
  run(`ME={id:1,username:'synthetic',display_name:'Synthetic',avatar_initial:'S'};TOKEN='synthetic-session';activeChatId=10;chatLoadState='ready';chats=[{id:10,type:'group',title:'Synthetic chat',members:[]},{id:20,type:'group',title:'Another synthetic chat',members:[]}];ws={readyState:1,send:collectSocket};`);
  const input=document.getElementById('composerInput');
  const bubbles=()=>[...document.querySelectorAll('#messages .msg')];
  const send=text=>{input.value=text;return run('sendMessage()');};
  const saved=(request,id=100)=>({id,chat_id:10,client_id:request.body.client_id,text:request.body.text,sender:{id:1,display_name:'Synthetic'},mine:true,iso:new Date().toISOString(),read:false,delivered:false});
  return {document,requests,timers,storage,socket,run,input,bubbles,send,saved};
}

test('sending clears the composer and displays a bubble before any response',async()=>{
  const c=client(),sending=c.send('Hello on a slow connection');
  assert.equal(c.input.value,'');
  assert.equal(c.bubbles().length,1);
  assert.match(c.bubbles()[0].textContent,/Hello on a slow connection/);
  assert.match(c.bubbles()[0].textContent,/Sending/);
  assert.equal(c.storage.get('gc_draft_1_10'),'');
  c.input.value='My next draft';
  c.requests[0].resolve(c.saved(c.requests[0]));await sending;
  assert.equal(c.input.value,'My next draft');
  assert.equal(c.bubbles().length,1);
  assert.equal(c.bubbles()[0].dataset.id,'100');
  assert.equal(c.document.querySelector('.send-state'),null);
  assert.equal(c.requests.length,1,'Sending must not wait for a chat/history fetch');
});

test('a refresh keeps pending messages and late acknowledgements visible',async()=>{
  const c=client(),sending=c.send('Keep this visible');
  const refreshing=c.run('refreshMessages(false)');
  c.requests[1].resolve([]);await refreshing;
  assert.equal(c.bubbles().length,1);
  assert.match(c.bubbles()[0].textContent,/Sending/);
  const staleRefresh=c.run('refreshMessages(false)');
  c.requests[0].resolve(c.saved(c.requests[0]));await sending;
  c.requests[2].resolve([]);await staleRefresh;
  assert.equal(c.bubbles().length,1);
  assert.equal(c.bubbles()[0].dataset.id,'100');
  assert.doesNotMatch(c.document.getElementById('messages').textContent,/Start the conversation/);
});

test('socket and HTTP acknowledgements produce one bubble',async()=>{
  const c=client(),sending=c.send('One copy only'),message=c.saved(c.requests[0]);
  c.run(`handleWSEvent(${JSON.stringify({...message,type:'message'})})`);
  assert.equal(c.bubbles().length,1);
  assert.equal(c.bubbles()[0].dataset.id,'100');
  c.run(`handleWSEvent({type:'chat_changed',chat_id:10,message_id:100})`);
  assert.equal(c.requests.length,1,'The compatibility hint must not trigger another fetch');
  c.requests[0].resolve(message);await sending;
  assert.equal(c.bubbles().length,1);
  assert.equal(c.document.querySelector('.send-state'),null);
});

test('a failed send remains visible and retries with the same reference',async()=>{
  const c=client(),sending=c.send('Keep this after failure');
  c.requests[0].reject(new Error('Synthetic connection failure'));await sending;
  assert.equal(c.bubbles().length,1);
  assert.match(c.bubbles()[0].textContent,/Not confirmed/);
  assert.equal(c.document.querySelector('.message-retry').textContent,'Retry');
  c.input.value='Do not erase this draft';
  const retry=c.run(`retryOutgoingMessage(${JSON.stringify(c.requests[0].body.client_id)})`);
  assert.equal(c.requests[1].body.client_id,c.requests[0].body.client_id);
  c.requests[1].resolve(c.saved(c.requests[1]));await retry;
  assert.equal(c.input.value,'Do not erase this draft');
  assert.equal(c.bubbles().length,1);
  assert.equal(c.document.querySelector('.message-retry'),null);
});

test('identical consecutive messages keep separate send references',async()=>{
  const c=client(),first=c.send('Same text'),second=c.send('Same text');
  assert.equal(c.bubbles().length,2);
  assert.notEqual(c.requests[0].body.client_id,c.requests[1].body.client_id);
  c.requests[1].resolve(c.saved(c.requests[1],101));await second;
  c.requests[0].resolve(c.saved(c.requests[0],100));await first;
  assert.equal(c.bubbles().length,2);
  assert.deepEqual(c.bubbles().map(el=>el.dataset.id),['100','101']);
});

test('an acknowledgement does not change a different open chat or its draft',async()=>{
  const c=client(),sending=c.send('For the first chat');
  c.run(`activeChatId=20;messageCache.clear();document.getElementById('messages').replaceChildren();`);
  c.input.value='Draft for the second chat';
  c.requests[0].resolve(c.saved(c.requests[0]));await sending;
  assert.equal(c.bubbles().length,0);
  assert.equal(c.input.value,'Draft for the second chat');
  c.run('activeChatId=10');
  const refresh=c.run('refreshMessages(false)');c.requests[1].resolve([c.saved(c.requests[0])]);await refresh;
  assert.equal(c.bubbles().length,1);
});

test('incoming messages arriving during a stale history fetch do not disappear',async()=>{
  const c=client(),refresh=c.run('refreshMessages(false)');
  c.run(`handleWSEvent(${JSON.stringify({id:99,chat_id:10,type:'message',text:'A new incoming message',iso:new Date().toISOString(),sender:{id:2,display_name:'Peer'}})})`);
  assert.equal(c.bubbles().length,1);
  c.requests[0].resolve([]);await refresh;
  assert.equal(c.bubbles().length,1);
  assert.match(c.bubbles()[0].textContent,/A new incoming message/);
});

test('typing sends one leading event for a burst and captures the correct chat',()=>{
  const c=client();
  for(let i=0;i<15;i++)c.run('sendTyping(10,true)');
  assert.equal(c.socket.filter(event=>event.typing===true).length,1);
  c.run('activeChatId=20');
  const trailing=[...c.timers.values()].find(timer=>timer.delay===1500);trailing.fn();
  assert.deepEqual(c.socket.at(-1),{type:'typing',chat_id:10,typing:false});
});

test('a timeout exposes a retry without losing the message',async()=>{
  const c=client(),sending=c.send('Wait for confirmation');
  [...c.timers.values()].find(timer=>timer.delay===30000).fn();await sending;
  assert.match(c.bubbles()[0].textContent,/Wait for confirmation/);
  assert.match(c.bubbles()[0].textContent,/Not confirmed/);
  assert.ok(c.document.querySelector('.message-retry'));
});

test('signing out clears pending content and ignores its late response',async()=>{
  const c=client(),sending=c.send('Only for this account');
  c.run('clearSignedInState()');await sending;
  assert.equal(c.bubbles().length,0);
  assert.equal(c.input.value,'');
  assert.equal(c.run('outgoingMessages.size'),0);
  assert.equal(c.run('ME'),null);
});

test('a late POST acknowledgement preserves receipts already observed',async()=>{
  const c=client(),sending=c.send('Already read'),message=c.saved(c.requests[0]);
  const refresh=c.run('refreshMessages(false)');c.requests[1].resolve([{...message,read:true,delivered:true}]);await refresh;
  c.requests[0].resolve(message);await sending;
  assert.ok(c.document.querySelector('.read-receipt'));
  assert.equal(c.bubbles().length,1);
  // A subsequent authoritative privacy update may still hide blue marks.
  const privacyRefresh=c.run('refreshMessages(false)');c.requests[2].resolve([{...message,read:false,delivered:true}]);await privacyRefresh;
  assert.equal(c.document.querySelector('.read-receipt'),null);
});

test('clearing a chat discards its pending content and ignores a late response',async()=>{
  const c=client(),sending=c.send('Clear this pending message');
  c.run(`discardOutgoingForChats([10]);document.getElementById('messages').replaceChildren();messageCache.clear();`);await sending;
  assert.equal(c.bubbles().length,0);
  assert.equal(c.run('outgoingMessages.size'),0);
});
