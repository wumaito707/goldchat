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

test('mobile navigation remains outside the disappearing chat sidebar',()=>{
  const c=client();
  const nav=c.document.querySelector('#app > nav.mobile-nav');
  assert.ok(nav,'navigation should belong to the app rather than the sidebar');
  assert.equal(nav.closest('.sidebar'),null);
  for(const id of ['mobileChats','mobileUpdates','mobileCommunities','mobileCalls'])
    assert.ok(nav.querySelector('#'+id),'missing tab '+id);
  c.document.getElementById('sidebar').classList.add('hidden');
  assert.ok(c.document.querySelector('#app > nav.mobile-nav'));
  assert.match(readFileSync(path.join(frontend,'styles.css'),'utf8'),/\.mobile-nav\s*\{[^}]*z-index:220/);
});

test('bottom tabs appear on the four root pages and disappear on detail screens',()=>{
  const c=client(),visible=()=>c.document.body.classList.contains('main-tabs-visible');
  c.run('syncMobileTabsVisibility()');assert.equal(visible(),true,'chat list');
  c.run(`document.getElementById('sidebar').classList.add('hidden');syncMobileTabsVisibility()`);
  assert.equal(visible(),false,'individual chat');
  for(const page of ['Updates','Communities','Calls']){
    c.run(`panel('${page}','','page')`);assert.equal(visible(),true,page);
  }
  for(const detail of ['Status viewer','Add status','Settings','Create a group']){
    c.run(`panel('${detail}','','page')`);assert.equal(visible(),false,detail);
  }
  c.run('openChatsTab()');assert.equal(visible(),true,'back to chats');
  assert.match(readFileSync(path.join(frontend,'experience.css'),'utf8'),/body:not\(\.main-tabs-visible\) #app > \.mobile-nav/);
});

test('voice and video calls use STUN, show the right mode and can be ended',async()=>{
  for(const video of [false,true]){
    const c=client();
    c.run(`wsAlive=true;activeChatId=20;chats=[{id:20,type:'direct',peer:{id:2,display_name:'Peer'}}];
      navigator.mediaDevices={getUserMedia:async opts=>{window.mediaOptions=opts;return {getTracks:()=>[{stop(){},enabled:true}],getAudioTracks:()=>[{enabled:true}]};}};
      window.RTCPeerConnection=RTCPeerConnection=class {
        constructor(config){window.iceConfig=config;this.connectionState='new';}
        addTrack(){};async createOffer(){return {sdp:'offer-sdp'};};async setLocalDescription(){};close(){};
      };`);
    const pending=c.run(`startCall(${video})`);
    assert.equal(c.requests.length,1);
    c.requests[0].resolve({id:'call-1'});await pending;
    assert.equal(c.run('window.mediaOptions.video'),video);
    assert.equal(c.run('window.mediaOptions.audio'),true);
    assert.match(c.run('window.iceConfig.iceServers[0].urls[0]'),/^stun:/);
    assert.equal(c.document.getElementById('callOverlay').classList.contains('voice-call'),!video);
    assert.equal(c.document.body.classList.contains('main-tabs-visible'),false,'in-call is a detail screen');
    assert.equal(c.socket.at(-1).signal.kind,'offer');
    c.run('endCall(true)');
    assert.equal(c.document.getElementById('callOverlay'),null);
    assert.equal(c.socket.at(-1).signal.kind,'hangup');
  }
});

test('an unanswered incoming call is recorded as missed',async()=>{
  const c=client();
  c.run(`activeChatId=20;chats=[{id:20,type:'direct',peer:{display_name:'Peer'}}];`);
  await c.run(`handleCallSignal({chat_id:20,signal:{kind:'offer',call_id:'call-2',sdp:'offer',video:false}})`);
  assert.ok(c.document.getElementById('acceptCall'));
  const timeout=[...c.timers.values()].find(timer=>timer.delay===45000);
  assert.ok(timeout);
  timeout.fn();
  assert.equal(c.socket.at(-1).signal.reason,'missed');
  assert.equal(c.requests.at(-1).body.action,'missed');
});

test('delivery and read receipt bursts share a single refresh timer',()=>{
  const c=client();
  c.run("handleWSEvent({type:'read',chat_id:10,user_id:2});handleWSEvent({type:'delivery',chat_ids:[10]});handleWSEvent({type:'read',chat_id:10,user_id:3});");
  const receipts=[...c.timers.values()].filter(x=>x.delay===220);
  assert.equal(receipts.length,1);
  assert.equal(c.requests.length,0,'no immediate full chat fetch for each receipt');
});

test('incoming message popups are safe and open their selected conversation',()=>{
  const c=client();
  const social=readFileSync(path.join(frontend,'social.js'),'utf8');
  const start=social.indexOf('function showIncomingMessagePopup(');
  const end=social.indexOf('async function refreshNotifications(',start);
  assert.ok(start>=0&&end>start);
  c.run(social.slice(start,end));
  c.run("function openNotification(n){window.lastOpened=n.id;}");
  c.run("showIncomingMessagePopup({id:47,title:'<script>alert(1)</script>',chat_id:20},{id:20,title:'Group chat'},'Tap to open')");
  const popup=c.document.querySelector('.incoming-message-popup');
  assert.ok(popup);
  assert.equal(popup.querySelector('script'),null);
  assert.match(popup.textContent,/Tap to open/);
  popup.querySelector('.incoming-message-open').onclick();
  assert.equal(c.run('window.lastOpened'),47);
  assert.equal(c.document.querySelector('.incoming-message-popup'),null);
});

test('socket retries slow down after repeated disconnects',()=>{
  const c=client();
  c.run("location={origin:'https://goldchat.example'};window.created=[];class FakeWebSocket{static CONNECTING=0;static OPEN=1;constructor(url){this.url=url;this.readyState=0;window.created.push(this);}close(){this.readyState=3;}};WebSocket=FakeWebSocket;ws=null;connectWS();window.created[0].onclose({code:1006});");
  const first=[...c.timers.values()].at(-1);
  assert.ok(first.delay>=1000&&first.delay<1250);
  first.fn();
  c.run('window.created[1].onclose({code:1006})');
  const second=[...c.timers.values()].at(-1);
  assert.ok(second.delay>=2000&&second.delay<2250);
  assert.equal(c.run('window.created.length'),2);
});
