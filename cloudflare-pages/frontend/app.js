/* ===== GoldChat client — real backend integration ===== */
// The Pages Worker forwards same-origin API and WebSocket requests to Frankfurt.
const API = "";
let TOKEN = localStorage.getItem("gc_token");
let ME = null;
let chats = [];
let activeChatId = null;
let ws = null;
let wsAlive = false;
let typingTimers = {};   // chat_id -> timeout (clear typing display)
let peerTyping = {};     // chat_id -> bool
let chatListFilter = 'all';
function favoriteChatKey(chat) {
  return chat.type==='direct' && chat.peer ? `user:${chat.peer.id}` : `chat:${chat.id}`;
}
function favoriteChatKeys() {
  if (!ME) return [];
  try { return JSON.parse(localStorage.getItem(`gc_favorites_${ME.id}`)||'[]'); }
  catch { return []; }
}
function isFavoriteChat(chat) { return favoriteChatKeys().includes(favoriteChatKey(chat)); }
function toggleFavoriteChat(chat) {
  const keys=new Set(favoriteChatKeys()),key=favoriteChatKey(chat);
  if(keys.has(key))keys.delete(key);else keys.add(key);
  localStorage.setItem(`gc_favorites_${ME.id}`,JSON.stringify([...keys]));
  renderChatList();
  return keys.has(key);
}

const avatarPalette = [
  ['#d4af37','#8a7028'],['#e8b04b','#a07b22'],['#c9a227','#7a5e15'],
  ['#f0d060','#b8901e'],['#b8941f','#6e5410'],['#dbb94a','#946b1c'],
];
function avatarStyle(seed) {
  let h = 0; for (const ch of String(seed)) h = (h*31 + ch.charCodeAt(0)) >>> 0;
  const [c1,c2] = avatarPalette[h % avatarPalette.length];
  return `linear-gradient(135deg, ${c1}, ${c2})`;
}
function escapeHtml(s){return (s||"").replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));}
function fmtTime(iso){ try { return new Date(iso).toLocaleTimeString([], {hour:'2-digit', minute:'2-digit',hour12:localStorage.getItem('gc_time_format')!=='24'}); } catch(e){ return ""; } }
function toast(msg){ const t=document.getElementById('toast'); t.textContent=msg; t.classList.add('show'); clearTimeout(t._tid); t._tid=setTimeout(()=>t.classList.remove('show'),2400); }

/* ---------- Auth ---------- */
let mode = "login";
const authWrap = document.getElementById('authWrap');
const appEl = document.getElementById('app');
const authForm = document.getElementById('authForm');
const authBtn = document.getElementById('authBtn');
const nameField = document.getElementById('nameField');
const switchBtn = document.getElementById('switchBtn');
const switchText = document.getElementById('switchText');
const authSub = document.getElementById('authSub');
const authErr = document.getElementById('authErr');

function setMode(m){
  mode = m;
  const reg = m === "register";
  nameField.style.display = reg ? '' : 'none';
  authBtn.textContent = reg ? "Create Account" : "Sign In";
  authSub.textContent = reg ? "Create your GoldChat account" : "Sign in to continue";
  switchText.textContent = reg ? "Already have an account?" : "No account?";
  switchBtn.textContent = reg ? "Sign in" : "Create one";
  authErr.classList.remove('show');
}
switchBtn.addEventListener('click', ()=> setMode(mode==='login'?'register':'login'));

authForm.addEventListener('submit', async (e)=>{
  e.preventDefault();
  const username = document.getElementById('username').value.trim();
  const password = document.getElementById('password').value;
  const display_name = document.getElementById('displayName').value.trim();
  authErr.classList.remove('show');
  authBtn.disabled = true; authBtn.textContent = "Please wait…";
  try {
    const body = mode==='register' ? {username, password, display_name} : {username, password};
    const res = await fetch(`${API}/api/${mode}`, {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify(body)
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Failed");
    TOKEN = data.token; ME = data.user;
    localStorage.setItem('gc_token', TOKEN);
    localStorage.setItem('gc_me', JSON.stringify(ME));
    enterApp();
  } catch(err){
    authErr.textContent = err.message; authErr.classList.add('show');
  } finally {
    authBtn.disabled = false; authBtn.textContent=mode==='register'?'Create Account':'Sign In';
  }
});

/* ---------- Enter app ---------- */
async function enterApp(){
  document.getElementById('meAvatar').textContent = ME.avatar_initial;
  document.getElementById('meAvatar').style.background = avatarStyle(ME.username);
  document.getElementById('meName').textContent = ME.display_name;
  document.getElementById('meStatus').textContent = "Online";
  document.getElementById('meStatus').className = "me-status online";
  authWrap.style.display = 'none';
  appEl.style.display = 'flex';
  // Conversations are the first thing people expect to see.  Start their
  // request immediately instead of waiting for the optional social widgets.
  const chatsReady = loadChats();
  try {
    // This establishes the private-media cookie used by the WebSocket and
    // uploaded media.  It can run while the conversation list is loading.
    await initializeSocial();
    connectWS();
  } catch (error) {
    console.error('Social session setup failed', error);
    toast('Some updates are still connecting. Your conversations are available.');
  }
  await chatsReady;
}

/* ---------- WebSocket ---------- */
function connectWS(){
  const apiUrl = new URL(API || location.origin);
  const proto = apiUrl.protocol === 'https:' ? 'wss' : 'ws';
  ws = new WebSocket(`${proto}://${apiUrl.host}/ws`);
  ws.onopen = ()=>{
    wsAlive = true;
    document.getElementById('meStatus').textContent = 'Connected';
    if (activeChatId) { wsSend({type:'subscribe',chat_id:activeChatId}); refreshMessages(); }
    loadChats();
  };
  ws.onmessage = (ev)=>{
    const data = JSON.parse(ev.data);
    handleWSEvent(data);
  };
  ws.onclose = (ev)=>{
    wsAlive = false;
    document.getElementById('meStatus').textContent = 'Disconnected';
    if (ev.code === 4401) { TOKEN=null; localStorage.removeItem('gc_token'); appEl.style.display='none'; authWrap.style.display='flex'; return; }
    setTimeout(()=>{ if (TOKEN) connectWS(); }, 1500);
  };
  ws.onerror = ()=>{ try{ ws.close(); }catch(e){} };
}

function handleWSEvent(d){
  if (d.type === 'profile_changed') { syncOwnProfile(); return; }
  if (d.type === 'notifications_changed') { refreshNotifications(true); return; }
  if (d.type === 'membership_removed') { handleMembershipRemoved(d.chat_id); return; }
  if (d.type === 'call_signal') { handleCallSignal(d); return; }
  if (d.type === 'error') { toast(d.message); return; }
  if (d.type === 'chat_changed') { onChatChanged(d.chat_id); return; }
  if (d.type === 'message'){
    // upsert message
    const chat = chats.find(c=>c.id===d.chat_id);
    if (chat){
      chat.last_message = { text:d.text, sender_id:d.sender.id, time:d.time, iso:d.iso };
      // update unread if not active
      if (d.chat_id !== activeChatId){
        chat.unread = (chat.unread||0)+1;
      }
    }
    if (d.chat_id === activeChatId){
      appendMessage({id:d.id, sender:d.sender, text:d.text, time:d.time, iso:d.iso, mine: d.sender.id===ME.id, read:false});
      // mark read immediately (we just received it)
      if (d.sender.id !== ME.id && !document.hidden) markRead(activeChatId);
    }
    // bump unread for chats not currently open
    renderChatList();
  }
  else if (d.type === 'typing'){
    if (d.chat_id === activeChatId){
      peerTyping[d.chat_id] = d.typing;
      updateHeaderStatus();
      if (d.typing){
        showTypingBubble();
        clearTimeout(typingTimers[d.chat_id]);
        typingTimers[d.chat_id] = setTimeout(()=>{ peerTyping[d.chat_id]=false; updateHeaderStatus(); removeTypingBubble(); }, 4000);
      } else {
        removeTypingBubble();
      }
    }
    if (d.chat_id !== activeChatId && d.typing){
      const chat = chats.find(c=>c.id===d.chat_id);
      if (chat) chat._typingPreview = true;
    }
    renderChatList();
  }
  else if (d.type === 'read'){
    loadChats();
    if (d.chat_id === activeChatId && d.user_id !== ME.id) refreshMessages();
  }
  else if (d.type === 'presence'){
    const chat = chats.find(c=> c.peer && c.peer.id===d.user_id);
    if (chat){ chat.peer_online = d.online; chat.peer_last_seen = d.online ? null : d.last_seen; renderChatList(); if (d.user_id === getPeerId(activeChatId)) updateHeaderStatus(); }
  }
  else if (d.type === 'pong'){
    // keepalive
  }
}

setInterval(()=>{ if (wsAlive && ws && ws.readyState===1) ws.send(JSON.stringify({type:'ping'})); }, 25000);

/* ---------- Chats ---------- */
let chatLoadState='idle',chatLoadPromise=null;
async function loadChats(){
  if(chatLoadPromise)return chatLoadPromise;
  chatLoadState='loading';renderChatList();
  chatLoadPromise=(async()=>{
    try {
      const res=await fetch(`${API}/api/v2/chats`,{headers:{Authorization:"Bearer "+TOKEN}});
      if(!res.ok)throw new Error('Could not load chats');
      const rows=await res.json();if(!Array.isArray(rows))throw new Error('Invalid chat response');
      chats=rows;chatLoadState='ready';
    } catch(e){chatLoadState='error';console.error(e);}
    finally {chatLoadPromise=null;renderChatList();}
  })();return chatLoadPromise;
}

function uniqueHomeChats(rows) {
  const peers=new Map(),result=[];
  for(const c of rows){
    const key=c.type==='direct' && c.peer ? c.peer.id : null;
    if(key===null){result.push({...c});continue;}
    const current=peers.get(key);
    if(!current){const item={...c};peers.set(key,item);result.push(item);}
    else {current.unread=(current.unread||0)+(c.unread||0);current.pinned=current.pinned||c.pinned;}
  }
  return result;
}
function renderChatList(){
  const list = document.getElementById('chatList');
  if(!chats.length && chatLoadState!=='ready'){
    list.innerHTML='';const message=document.createElement('div');message.className='empty-list';
    message.textContent=chatLoadState==='error'?'Could not load conversations. Please try again.':'Loading conversations…';list.appendChild(message);
    if(chatLoadState==='error'){const retry=document.createElement('button');retry.className='feature-btn';retry.textContent='Retry';retry.onclick=loadChats;list.appendChild(retry);}return;
  }
  const q = document.getElementById('searchInput').value.trim().toLowerCase();
  const visible = uniqueHomeChats(chats.filter(c=>Boolean(c.archived) === showArchived));
  const filtered = visible.filter(c=>{
    if (chatListFilter==='unread' && !c.unread) return false;
    if (chatListFilter==='favorites' && !isFavoriteChat(c)) return false;
    if (['direct','group','channel'].includes(chatListFilter) && c.type!==chatListFilter) return false;
    if (!q) return true;
    const name = c.type==='direct' && c.peer ? c.peer.display_name : (c.title||"");
    return name.toLowerCase().includes(q);
  });
  const filterLabels={all:'All',unread:'Unread',favorites:'Favorites',direct:'People',group:'Groups',channel:'Channels'};
  document.querySelectorAll('.chat-filter').forEach(button=>{
    const selected=button.dataset.filter===chatListFilter;
    button.classList.toggle('active',selected);
    button.setAttribute('aria-selected',String(selected));
    const count=button.dataset.filter==='unread' ? visible.filter(c=>c.unread).length : 0;
    button.textContent=button.dataset.filter==='unread' && count ? `Unread ${count}` : filterLabels[button.dataset.filter];
  });
  list.innerHTML = '';
  if (!filtered.length){
    list.innerHTML = `<div class="empty-list">${q? 'No chats match your search.' : chatListFilter!=='all' ? 'No chats in this filter.' : showArchived ? 'No archived chats.' : 'No conversations yet. Tap + to start one.'}</div>`;
    return;
  }
  for (const c of filtered){
    const el = document.createElement('div');
    el.className = 'chat-item' + (c.id===activeChatId ? ' active' : '');
    const last = c.last_message || {};
    const preview = last.sender_id === ME.id ? receiptMarkup(last.read)+' <span class="you-prefix">You: </span>' : '';
    const typingTag = c._typingPreview ? `<span style="color:var(--green)">typing…</span>` : `${preview}${escapeHtml(last.text||'')}`;
    const timeTag = last.iso ? fmtTime(last.iso) : (last.time || '');
    el.innerHTML = `
      <div class="chat-avatar ${c.peer_online?'online':''}" style="background:${avatarStyle(c.peer?c.peer.username:c.id)}">${c.peer?avatarContent(c.peer):'G'}</div>
      <div class="chat-meta">
        <div class="chat-top">
          <div class="chat-name">${c.pinned?'📌 ':''}${escapeHtml(c.peer?c.peer.display_name:(c.title||'Group'))}${isFavoriteChat(c)?' <span class="favorite-mark" aria-label="Favorite chat">★</span>':''}${c.muted?' 🔕':''}</div>
          <div class="chat-time">${timeTag}</div>
        </div>
        <div class="chat-bottom">
          <div class="chat-preview">${typingTag}</div>
          ${c.unread ? `<div class="unread-badge">${c.unread}</div>` : ''}
        </div>
      </div>`;
    el.addEventListener('click', ()=> openChat(c.id));
    list.appendChild(el);
  }
}

/* ---------- Open chat ---------- */
async function openChat(chatId){
  if (!chats.some(c=>c.id===chatId)) return;
  saveDraft();
  activeChatId = chatId;
  replyTo = null;
  messageQuery = '';
  document.getElementById('replyBar').hidden = true;
  composerInput.value = localStorage.getItem('gc_draft_'+ME.id+'_'+chatId) || '';
  updateSendBtn();
  document.getElementById('emptyState').style.display = 'none';
  document.getElementById('chatView').style.display = 'flex';
  const c = chats.find(x=>x.id===chatId);
  // reset unread
  c.unread = 0; c._typingPreview = false;
  // header
  const av = document.getElementById('hAvatar');
  av.style.background = avatarStyle(c.peer?c.peer.username:c.id);
  if(c.peer)paintAvatar(av,c.peer);else av.textContent='G';
  document.getElementById('hName').textContent = c.peer ? c.peer.display_name : (c.title||'Group');
  updateHeaderStatus();
  await refreshMessages();
  // subscribe via WS
  wsSend({type:'subscribe', chat_id: chatId});
  if (!document.hidden) markRead(chatId);
  renderChatList();
  if (window.innerWidth <= 760) document.getElementById('sidebar').classList.add('hidden');
  document.getElementById('composerInput').focus();
}

function getPeerId(chatId){
  const c = chats.find(x=>x.id===chatId);
  return c && c.peer ? c.peer.id : null;
}

function updateHeaderStatus(){
  const el = document.getElementById('hStatus');
  const c = chats.find(x=>x.id===activeChatId);
  if (!c){ return; }
  if (peerTyping[activeChatId]){
    el.textContent = 'typing…'; el.className = 'header-status typing'; return;
  }
  if (c.type !== 'direct') { el.textContent = c.type + ' · ' + (c.members.length+1) + ' members'; el.className='header-status'; return; }
  if (c.peer_online){
    el.textContent = 'online'; el.className = 'header-status online';
  } else {
    const seen=c.peer_last_seen ? new Date(c.peer_last_seen) : null;
    el.textContent = seen && !Number.isNaN(seen.getTime()) ? 'last seen '+seen.toLocaleString(undefined,{dateStyle:'medium',timeStyle:'short'}) : '';
    el.className = 'header-status';
  }
}

/* ---------- Messages rendering ---------- */
function appendMessage(m){
  const box = document.getElementById('messages');
  if (box.querySelector('[data-id="'+m.id+'"]')) return;
  messageCache.set(m.id,m);
  // date separator
  const today = new Date().toDateString();
  let showDate = false;
  if (m.iso && !box._lastDate){
    showDate = true; box._lastDate = new Date(m.iso).toDateString();
  } else if (m.iso){
    const d = new Date(m.iso).toDateString();
    if (d !== box._lastDate){ showDate = true; box._lastDate = d; }
  }
  if (showDate){
    const sep = document.createElement('div');
    sep.className = 'date-sep';
    const d = new Date(m.iso);
    const isToday = d.toDateString() === today;
    sep.textContent = isToday ? 'Today' : d.toLocaleDateString();
    box.appendChild(sep);
  }
  const wrap = document.createElement('div');
  wrap.className = 'msg ' + (m.mine ? 'sent' : 'recv');
  wrap.dataset.id = m.id || '';
  if(m.expires_at){wrap.dataset.expires=m.expires_at;wrap.title='Disappears '+new Date(m.expires_at*1000).toLocaleString();}
  const checks = m.mine ? receiptMarkup(m.read) : '';
  const who = (!m.mine && chats.find(c=>c.id===activeChatId)?.type !== 'direct') ? '<strong class="sender-name">'+escapeHtml(m.sender.display_name)+'</strong>' : ''; 
  const reply = m.reply ? `<div class="reply-preview">↪ ${escapeHtml(m.reply.text.slice(0,100))}</div>` : '';
  const file = attachmentMarkup(m.attachment,m);
  const reactions = (m.reactions||[]).map(r=>`${escapeHtml(r.emoji)} ${r.count}`).join('  ');
  wrap.innerHTML = `<div class="bubble">${who}${m.forwarded?'<small class="forward-label">↪ Forwarded</small>':''}${reply}${file}<span class="message-text">${escapeHtml(m.text)}</span><span class="meta">${m.expires_at?'⏳ ':''}${m.starred?'★ ':''}${m.edited?'edited ':''}${escapeHtml(m.iso?fmtTime(m.iso):(m.time||''))} ${checks}</span><div class="reactions">${reactions}</div></div>`;
  if(wrap.querySelector('.voice-note')){wrap.classList.add('voice-message');setupVoiceNote(wrap.querySelector('.voice-note'));}
  const imageLoad=wrap.querySelector('.image-load');
  if(imageLoad)imageLoad.addEventListener('click',()=>{
    const link=document.createElement('a');link.className='image-preview-link';link.href=imageLoad.dataset.src;link.target='_blank';link.rel='noopener noreferrer';link.setAttribute('aria-label','Open photo');
    const image=document.createElement('img');image.className='media-preview';image.src=imageLoad.dataset.src;image.alt=imageLoad.dataset.name||'Photo';image.referrerPolicy='no-referrer';
    link.appendChild(image);imageLoad.replaceWith(link);
  });
  if (!m.deleted) {
    const more=document.createElement('button'); more.className='message-more'; more.textContent='⋯'; more.title='Message actions'; more.setAttribute('aria-label','Message actions');
    more.addEventListener('click',()=>messageActions(m)); wrap.appendChild(more);
  }
  // remove typing bubble if present (place before it)
  const tb = box.querySelector('.typing-bubble');
  if (tb) box.insertBefore(wrap, tb); else box.appendChild(wrap);
  box.scrollTop = box.scrollHeight;
}

function voiceTime(seconds){
  if(!Number.isFinite(seconds)||seconds<0)return '0:00';
  const rounded=Math.floor(seconds);
  return Math.floor(rounded/60)+':'+String(rounded%60).padStart(2,'0');
}
function setupVoiceNote(note){
  const audio=note.querySelector('audio'),button=note.querySelector('.voice-play');
  const duration=note.querySelector('.voice-duration'),bars=[...note.querySelectorAll('.voice-waveform span')];
  const update=()=>{
    const length=Number.isFinite(audio.duration)?audio.duration:0;
    duration.textContent=voiceTime(audio.paused&&audio.currentTime===0?length:audio.currentTime);
    const progress=length?audio.currentTime/length:0;
    bars.forEach((bar,index)=>bar.classList.toggle('played',index<Math.round(progress*bars.length)));
    const playing=!audio.paused&&!audio.ended;
    button.classList.toggle('playing',playing);
    button.setAttribute('aria-label',playing?'Pause voice message':'Play voice message');
    button.querySelector('path').setAttribute('d',playing?'M7 5h4v14H7zm6 0h4v14h-4z':'M8 5v14l11-7z');
  };
  for(const event of ['loadedmetadata','durationchange','timeupdate','play','pause','ended'])audio.addEventListener(event,update);
  audio.addEventListener('error',()=>{duration.textContent='Audio unavailable';button.disabled=true;});
  button.addEventListener('click',async()=>{
    if(!audio.paused){audio.pause();return;}
    document.querySelectorAll('.voice-note audio').forEach(other=>{if(other!==audio)other.pause();});
    try{await audio.play();}catch(e){toast('Could not play this voice message');}
  });
  update();
}

function showTypingBubble(){
  const box = document.getElementById('messages');
  if (box.querySelector('.typing-bubble')) return;
  const el = document.createElement('div');
  el.className = 'typing-bubble';
  el.innerHTML = '<span></span><span></span><span></span>';
  box.appendChild(el); box.scrollTop = box.scrollHeight;
}
function removeTypingBubble(){
  const box = document.getElementById('messages');
  const tb = box.querySelector('.typing-bubble');
  if (tb) tb.remove();
}

function receiptMarkup(read){return `<span class="check${read?' read-receipt':''}" title="${read?'Read':'Sent'}" aria-label="${read?'Read':'Sent'}">&#10003;&#10003;</span>`;}
function markSentMessagesRead(){
  document.querySelectorAll('.msg.sent .meta .check').forEach(c=>{ c.textContent='✓✓'; });
}

/* ---------- Send message ---------- */
const composerInput = document.getElementById('composerInput');
const sendBtn = document.getElementById('sendBtn');

function wsSend(obj){
  if (ws && ws.readyState===1){ ws.send(JSON.stringify(obj)); }
}

function updateSendBtn(){
  sendBtn.classList.toggle('active',composerInput.value.trim().length>0);
  if(typeof syncComposerActions==='function')syncComposerActions();
}
composerInput.addEventListener('input', ()=>{
  composerInput.style.height='auto';
  composerInput.style.height=Math.min(composerInput.scrollHeight,120)+'px';
  updateSendBtn();
  // typing indicator
  if (activeChatId){
    wsSend({type:'typing', chat_id: activeChatId, typing: true});
    clearTimeout(typingTimers['self_'+activeChatId]);
    typingTimers['self_'+activeChatId] = setTimeout(()=> wsSend({type:'typing', chat_id: activeChatId, typing:false}), 1500);
  }
});
composerInput.addEventListener('keydown', e=>{ if(e.key==='Enter' && !e.shiftKey){ e.preventDefault(); sendMessage(); } });
sendBtn.addEventListener('click', sendMessage);

async function sendMessage(){
  const text = composerInput.value.trim();
  if (!text || activeChatId==null || sendBtn.disabled) return;
  if (text.length > 10000) { toast('Please keep messages under 10000 characters.'); return; }
  const visibleChatId=activeChatId;
  const cid=replyTo?(messageCache.get(replyTo)?.chat_id||activeChatId):activeChatId;
  sendBtn.disabled=true;
  try {
    await request(`/api/chats/${cid}/messages`, 'POST', {text,reply_to:replyTo});
    if (activeChatId===visibleChatId && composerInput.value.trim()===text) {
      composerInput.value=''; composerInput.style.height='auto'; replyTo=null; document.getElementById('replyBar').hidden=true;
      saveDraft(); updateSendBtn();
    }
    wsSend({type:'typing', chat_id: cid, typing:false});
    await onChatChanged(cid);
  } catch(e) { toast(e.message); }
  finally { sendBtn.disabled=false; }
}

async function markRead(chatId){
  try { await Promise.all(conversationIds(chatId).map(id=>fetch(`${API}/api/chats/${id}/read`, {method:'POST',headers:{Authorization:"Bearer "+TOKEN}}))); } catch(e){}
}

/* ---------- New chat modal ---------- */
document.getElementById('newChatBtn').addEventListener('click', openNewChatModal);

function openNewChatModal(){
  const root = document.getElementById('modalRoot');
  root.innerHTML = `
    <div class="modal-overlay" id="modalOverlay">
      <div class="modal" onclick="event.stopPropagation()">
        <h3>Start a new chat</h3>
        <div class="field">
          <label>Search by username or name</label>
          <input type="text" id="userSearch" placeholder="Type a name…" autocomplete="off">
        </div>
        <div class="search-results" id="searchResults">
          <div class="empty-list" style="padding:16px">Start typing to find users.</div>
        </div>
        <button class="modal-close" id="modalClose">Cancel</button>
      </div>
    </div>`;
  document.getElementById('modalOverlay').addEventListener('click', ()=> root.innerHTML='');
  document.getElementById('modalClose').addEventListener('click', ()=> root.innerHTML='');
  const inp = document.getElementById('userSearch');
  const results = document.getElementById('searchResults');
  let to;
  inp.addEventListener('input', ()=>{
    clearTimeout(to);
    const q = inp.value.trim();
    if (!q){ results.innerHTML = `<div class="empty-list" style="padding:16px">Start typing to find users.</div>`; return; }
    to = setTimeout(async ()=>{
      try {
        const res = await fetch(`${API}/api/users/search?q=${encodeURIComponent(q)}`,{headers:{Authorization:"Bearer "+TOKEN}});
        const users = await res.json();
        if (!users.length){ results.innerHTML = `<div class="empty-list" style="padding:16px">No users found.</div>`; return; }
        results.innerHTML = '';
        for (const u of users){
          const el = document.createElement('div');
          el.className = 'user-result';
          el.innerHTML = `
            <div class="chat-avatar ${u.online?'online':''}" style="background:${avatarStyle(u.username)}">${avatarContent(u)}</div>
            <div>
              <div class="ur-name">${escapeHtml(u.display_name)}</div>
              <div class="ur-sub">@${escapeHtml(u.username)} · ${u.online?'online':'offline'}</div>
            </div>`;
          el.addEventListener('click', async ()=>{
            try {
              const r = await fetch(`${API}/api/chats/direct/${u.id}`, {method:'POST',headers:{Authorization:"Bearer "+TOKEN}});
              const d = await r.json();
              root.innerHTML = '';
              await loadChats();
              openChat(d.chat_id);
              toast(`Started chat with ${u.display_name}`);
            } catch(e){ toast("Could not start chat"); }
          });
          results.appendChild(el);
        }
      } catch(e){}
    }, 250);
  });
  inp.focus();
}

/* ---------- Misc ---------- */
document.getElementById('searchInput').addEventListener('input', renderChatList);
document.querySelectorAll('.chat-filter').forEach(button=>button.addEventListener('click',()=>{
  chatListFilter=button.dataset.filter;
  renderChatList();
}));
document.getElementById('backBtn').addEventListener('click', ()=>{
  document.getElementById('sidebar').classList.remove('hidden');
});
document.getElementById('logoutBtn').addEventListener('click', async ()=>{
  saveDraft();
  try { await request('/api/logout','POST'); } catch(e) { toast(e.message); return; }
  localStorage.removeItem('gc_token');
  localStorage.removeItem('gc_me');
  TOKEN = null; ME = null;
  if (ws) ws.close();
  appEl.style.display = 'none';
  authWrap.style.display = 'flex';
  setMode('login');
});

/* ---------- Bootstrap ---------- */
async function bootstrap(){
  if (TOKEN){
    try {
      const res = await fetch(`${API}/api/me`,{headers:{Authorization:"Bearer "+TOKEN}});
      if (res.ok){
        ME = await res.json();
        enterApp();
        return;
      } else { localStorage.removeItem('gc_token'); TOKEN=null; }
    } catch(e){ localStorage.removeItem('gc_token'); TOKEN=null; }
  }
  setMode('login');
}
window.addEventListener('DOMContentLoaded',bootstrap,{once:true});
