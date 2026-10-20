/* GOLDCHAT feature interface */
let showArchived=false;
let replyTo=null;
const messageCache=new Map();
let refreshGeneration=0;
let refreshTimer=null;
let messageQuery='';
let oldestMessageId=null;
let refreshRunning=false;
let refreshAgain=false;

async function request(path, method='GET', body) {
  const response=await fetch(path, {
    method, headers:{'Authorization':'Bearer '+TOKEN,...(body?{'Content-Type':'application/json'}:{})}, body:body?JSON.stringify(body):undefined
  });
  const data=await response.json();
  if (!response.ok) throw new Error(typeof data.detail==='string'?data.detail:'Please check your entries and try again.');
  return data;
}
function saveDraft() {
  if (ME && activeChatId) localStorage.setItem('gc_draft_'+ME.id+'_'+activeChatId,composerInput.value);
}
composerInput.addEventListener('input',saveDraft);

function conversationIds(cid) {
  const chat=chats.find(c=>c.id===cid);
  return chat?.type==='direct' && chat.peer ? chats.filter(c=>c.type==='direct' && c.peer?.id===chat.peer.id).map(c=>c.id) : [cid];
}
async function conversationMessages(cid,before=null) {
  const pages=await Promise.all(conversationIds(cid).map(id=>request(`/api/v2/chats/${id}/messages?q=${encodeURIComponent(messageQuery)}${before?'&before='+before:''}`)));
  const rows=[...new Map(pages.flat().map(m=>[m.id,m])).values()].sort((a,b)=>a.id-b.id);
  return {rows:rows.slice(-50),hasMore:pages.some(page=>page.length===50)||rows.length>50};
}
async function refreshMessages() {
  if (!activeChatId || !TOKEN) return;
  const cid=activeChatId, generation=++refreshGeneration;
  try {
    const {rows,hasMore}=await conversationMessages(cid);
    if (generation!==refreshGeneration || cid!==activeChatId) return;
    const box=document.getElementById('messages');
    const atBottom=box.scrollHeight-box.scrollTop-box.clientHeight<100;
    const oldScroll=box.scrollTop;
    box.innerHTML=''; box._lastDate=null; messageCache.clear();
    oldestMessageId=rows.length?rows[0].id:null;
    if (hasMore) {
      const older=document.createElement('button'); older.className='feature-btn'; older.textContent='Load older messages';
      older.onclick=()=>loadOlder(); box.appendChild(older);
    }
    rows.forEach(appendMessage);
    if (!rows.length) box.innerHTML='<div class="empty-list">'+(messageQuery?'No matching messages.':'Start the conversation.')+'</div>';
    if (!atBottom) box.scrollTop=oldScroll;
    if (document.visibilityState==='visible' && !messageQuery) await markRead(cid);
  } catch(e) { toast(e.message); }
}
async function loadOlder() {
  const cid=activeChatId;
  if (!oldestMessageId) return;
  try {
    const {rows}=await conversationMessages(cid,oldestMessageId);
    if (cid!==activeChatId) return;
    if (!rows.length) { toast('You have reached the beginning.'); return; }
    const all=[...rows,...messageCache.values()];
    const box=document.getElementById('messages');
    const oldHeight=box.scrollHeight;
    box.innerHTML=''; box._lastDate=null; messageCache.clear();
    const older=document.createElement('button');older.className='feature-btn';older.textContent='Load older messages';older.onclick=loadOlder;box.appendChild(older);
    all.forEach(appendMessage); oldestMessageId=rows[0].id; box.scrollTop=box.scrollHeight-oldHeight;
  } catch(e) { toast(e.message); }
}
async function onChatChanged(cid) {
  if (refreshRunning) { refreshAgain=true; return; }
  refreshRunning=true;
  try {
    const previous=chats.find(c=>c.id===cid)?.last_message?.iso;
    await loadChats();
    const chat=chats.find(c=>c.id===cid);
    if (activeChatId && conversationIds(activeChatId).includes(cid)) { const visibleChat=chats.find(c=>c.id===activeChatId); if(visibleChat) {document.getElementById('hName').textContent=visibleChat.title||visibleChat.peer?.display_name||'Chat'; if(visibleChat.peer)paintAvatar(document.getElementById('hAvatar'),visibleChat.peer); updateHeaderStatus();} await refreshMessages(); }
    await refreshNotifications(true);
  } finally {
    refreshRunning=false;
    if (refreshAgain) { refreshAgain=false; await onChatChanged(activeChatId); }
  }
}
function selectMainSection(section) {
  const names={Chats:['desktopChats','mobileChats'],Updates:['desktopUpdates','mobileUpdates'],Calls:['desktopCalls','mobileCalls'],Channels:['desktopChannels','mobileCommunities'],Settings:['desktopSettings','mobileMore']};
  document.querySelectorAll('.desktop-nav-item,.mobile-nav-item').forEach(button=>button.classList.remove('active'));
  (names[section]||names.Chats).forEach(id=>document.getElementById(id)?.classList.add('active'));
}
function closePanel() {document.getElementById('modalRoot').innerHTML='';selectMainSection('Chats');}
function panel(title, html, layout='dialog') {
  const root=document.getElementById('modalRoot');
  root.innerHTML=`<div class="modal-overlay ${layout==='page'?'page-overlay':''}"><section class="modal feature-panel ${layout==='page'?'feature-page':''}" role="dialog" aria-modal="true" aria-label="${escapeHtml(title)}"><div class="panel-heading"><h3>${escapeHtml(title)}</h3><button class="feature-btn" id="panelClose" aria-label="Close dialog">✕</button></div>${html}<p class="panel-error" id="panelError" role="alert"></p></section></div>`;
  root.querySelector('.modal-overlay').onclick=e=>{if(e.target===e.currentTarget) closePanel();};
  document.getElementById('panelClose').onclick=closePanel;
  root.querySelector('input,textarea,button')?.focus();
  return root;
}
function field(id,label,value='',type='text') {
  return `<div class="field"><label for="${id}">${escapeHtml(label)}</label><input id="${id}" type="${type}" value="${escapeHtml(String(value))}"></div>`;
}
function action(id,label) {return `<button class="feature-btn" id="${id}">${label}</button>`;}
function bind(id,fn) {
  document.getElementById(id).onclick=async e=>{
    const button=e.currentTarget;button.disabled=true;
    try {await fn();} catch(error) {const el=document.getElementById('panelError');if(el) el.textContent=error.message;else toast(error.message);}
    finally {button.disabled=false;}
  };
}
function downloadJSON(data,name) {
  const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));
  const a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),2000);
}

const toolbar=document.createElement('div');toolbar.className='feature-toolbar';
toolbar.innerHTML=action('featuresMenu','☰ Features')+action('archiveToggle','Archived')+action('createGroup','New group');
document.querySelector('.search-wrap').before(toolbar);
const headerTools=document.createElement('div');headerTools.className='header-actions';
headerTools.innerHTML=action('chatTools','⋯');document.querySelector('.chat-header').appendChild(headerTools);
const uploadInput=document.createElement('input');uploadInput.type='file';uploadInput.hidden=true;document.body.appendChild(uploadInput);
const voiceMicSvg='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="9" y="2" width="6" height="13" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v4m-4 0h8"/></svg>';
const voiceBtn=document.createElement('button');voiceBtn.type='button';voiceBtn.className='icon-btn voice-record-btn';voiceBtn.innerHTML=voiceMicSvg;voiceBtn.title='Record voice message';voiceBtn.setAttribute('aria-label','Record voice message');
document.querySelector('.composer').insertBefore(voiceBtn,sendBtn);
const voiceRecordingBar=document.createElement('div');voiceRecordingBar.id='voiceRecordingBar';voiceRecordingBar.className='voice-recording-bar';voiceRecordingBar.hidden=true;voiceRecordingBar.innerHTML='<span class="recording-dot" aria-hidden="true"></span><strong>Recording voice note</strong><time>0:00</time><span>Tap the microphone again to send</span>';
document.querySelector('.composer').before(voiceRecordingBar);
function syncComposerActions(){const typed=!!composerInput.value.trim(),recording=voiceBtn.classList.contains('recording');voiceBtn.hidden=typed&&!recording;sendBtn.hidden=!typed||recording;}
composerInput.addEventListener('input',syncComposerActions);syncComposerActions();

document.getElementById('featuresMenu').onclick=()=>{
  panel('More',`<div class="feature-grid">${action('profileMenu','Profile & privacy')}${action('contactsMenu','Contacts')}${action('starsMenu','Starred messages')}${action('themesMenu','Chat themes')}${action('settingsMenu','Settings & accessibility')}${action('channelMenu','Create channel')}${action('exportMenu','Export messages & contacts')}${action('blockedMenu','Blocked users')}${action('notificationsMenu','Notifications')}${action('linkedDevicesMenu','Linked devices')}${action('qrMenu','My QR & share')}${action('scanMenu','Scan code')}${action('callsMenu','Call history')}</div>`);
  bind('profileMenu',showProfile);bind('contactsMenu',showContacts);bind('starsMenu',showStars);bind('themesMenu',showChatThemes);bind('settingsMenu',showSettings);bind('channelMenu',()=>showGroup('channel'));bind('blockedMenu',showBlocks);bind('notificationsMenu',showNotificationInbox);bind('linkedDevicesMenu',showDevices);bind('qrMenu',showMyQR);bind('scanMenu',showScanner);bind('callsMenu',showCallHistory);
  bind('exportMenu',async()=>{downloadJSON(await request('/api/export'),'goldchat-export.json');toast('Export downloaded');});
};
document.getElementById('archiveToggle').onclick=()=>{showArchived=!showArchived;document.getElementById('archiveToggle').textContent=showArchived?'Active chats':'Archived';renderChatList();};
document.getElementById('createGroup').onclick=()=>showGroup('group');
document.getElementById('chatTools').onclick=showChatTools;
document.getElementById('mobileChats')?.addEventListener('click',()=>document.getElementById('backBtn')?.click());
document.getElementById('mobileUpdates')?.addEventListener('click',showUpdatesPage);
document.getElementById('mobileCommunities')?.addEventListener('click',()=>showGroup('channel'));
document.getElementById('mobileCalls')?.addEventListener('click',()=>showCallHistory());
document.getElementById('mobileMore')?.addEventListener('click',()=>document.getElementById('featuresMenu')?.click());
document.getElementById('desktopChats')?.addEventListener('click',()=>{closePanel();chatListFilter='all';renderChatList();});
document.getElementById('desktopUpdates')?.addEventListener('click',showUpdatesPage);
document.getElementById('desktopCalls')?.addEventListener('click',()=>showCallHistory());
document.getElementById('desktopChannels')?.addEventListener('click',()=>{closePanel();chatListFilter='channel';renderChatList();selectMainSection('Channels');});
document.getElementById('desktopSettings')?.addEventListener('click',()=>{showSettings();selectMainSection('Settings');});
function chooseChatAttachment(accept,capture=false){
  closePanel();uploadInput.value='';uploadInput.accept=accept;
  if(capture)uploadInput.capture='environment';else uploadInput.removeAttribute('capture');
  uploadInput.click();
}
document.getElementById('attachBtn').onclick=()=>{
  if(!activeChatId)return toast('Open a chat first');
  panel('Attach to chat',`<div class="attachment-options">${action('attachPhoto','▣ Photos')}${action('attachVideo','▶ Videos')}${action('attachAudio','♫ Audio')}${action('attachDocument','▤ Documents')}${action('attachCamera','◎ Camera')}</div>`);
  bind('attachPhoto',()=>chooseChatAttachment('image/*'));
  bind('attachVideo',()=>chooseChatAttachment('video/*'));
  bind('attachAudio',()=>chooseChatAttachment('audio/*'));
  bind('attachDocument',()=>chooseChatAttachment('application/pdf,.doc,.docx,.txt,.zip'));
  bind('attachCamera',()=>chooseChatAttachment('image/*,video/*',true));
};
document.getElementById('cameraBtn').onclick=()=>{if(!activeChatId)return toast('Open a chat first');chooseChatAttachment('image/*,video/*',true);};
document.getElementById('emojiBtn').onclick=()=>{
  panel('Choose an emoji','<div class="emoji-grid">'+['😀','😂','❤️','👍','🙏','🎉','🔥','😎','😢','✨','💛','👋','😊','🥳','🚀','💯'].map((e,i)=>action('emoji'+i,e)).join('')+'</div>');
  document.querySelectorAll('.emoji-grid button').forEach(b=>b.onclick=()=>{composerInput.value+=b.textContent;saveDraft();updateSendBtn();closePanel();composerInput.focus();});
};

async function showProfile() {
  const data=await request('/api/profile');
  panel('Profile & privacy',field('profileName','Display name',data.display_name)+field('profileBio','About you',data.bio)+`<div class="field"><label for="profilePrivacy">Who can see my status and presence?</label><select id="profilePrivacy"><option value="everyone">Everyone</option><option value="contacts">My contacts</option><option value="nobody">Nobody</option></select></div>`+action('saveProfile','Save profile'));
  document.getElementById('profilePrivacy').value=data.privacy;
  bind('saveProfile',async()=>{
    ME=await request('/api/profile','PATCH',{display_name:document.getElementById('profileName').value,bio:document.getElementById('profileBio').value,privacy:document.getElementById('profilePrivacy').value});
    document.getElementById('meName').textContent=ME.display_name;paintAvatar(document.getElementById('meAvatar'),ME);
    closePanel();toast('Profile updated');
  });
}
async function showGroup(kind) {
  const selected=new Map();
  panel(kind==='channel'?'Create a channel':'Create a group',field('groupTitle','Name')+field('groupSearch','Find members by username')+'<div id="groupResults"></div><div id="selectedMembers" class="helper"></div>'+action('saveGroup','Create'));
  let generation=0;
  document.getElementById('groupSearch').oninput=async e=>{
    const q=e.target.value.trim(),g=++generation;
    if (!q) {document.getElementById('groupResults').innerHTML='';return;}
    try {
      const rows=await request('/api/users/search?q='+encodeURIComponent(q));
      if (g!==generation || !document.getElementById('groupResults')) return;
      const results=document.getElementById('groupResults');results.innerHTML='';
      rows.forEach(u=>{
        const b=document.createElement('button');b.className='feature-btn member-select';b.textContent=(selected.has(u.id)?'✓ ':'+ ')+u.display_name+' (@'+u.username+')';
        b.onclick=()=>{if(selected.has(u.id))selected.delete(u.id);else selected.set(u.id,u);b.textContent=(selected.has(u.id)?'✓ ':'+ ')+u.display_name;document.getElementById('selectedMembers').textContent=[...selected.values()].map(u=>u.display_name).join(', ');};results.appendChild(b);
      });
    } catch(e) {toast(e.message);}
  };
  bind('saveGroup',async()=>{const d=await request('/api/groups','POST',{title:document.getElementById('groupTitle').value,member_ids:[...selected.keys()],kind});closePanel();showArchived=false;await loadChats();await openChat(d.chat_id);});
}
async function showContacts() {
  const contacts=await request('/api/contacts');
  panel('Contacts',field('contactSearch','Find a user to add')+'<div id="contactResults"></div><div id="contactList"></div>'+action('importPhoneContacts','Import phone contacts')+action('backupContacts','Download contact backup'));
  const list=document.getElementById('contactList');
  if(!contacts.length) list.innerHTML='<p class="helper">Add contacts using the search above or from a direct chat.</p>';
  contacts.forEach(u=>{
    const row=document.createElement('div');row.className='feature-row';
    const name=document.createElement('button');name.className='feature-btn';name.textContent=u.display_name+' @'+u.username;
    name.onclick=()=>showUserProfile(u.id);
    const remove=document.createElement('button');remove.className='feature-btn';remove.textContent='Delete contact';remove.onclick=()=>confirmAction('Delete contact','Remove '+u.display_name+' from your saved contacts? Chat messages will be kept.',async()=>{await request('/api/contacts/'+u.id,'DELETE');await showContacts();toast('Contact deleted');});
    row.append(name,remove);list.appendChild(row);
  });
  let generation=0;
  document.getElementById('contactSearch').oninput=async e=>{
    const q=e.target.value.trim(),g=++generation;
    try {
      const rows=q?await request('/api/users/search?q='+encodeURIComponent(q)):[];
      if(g!==generation || !document.getElementById('contactResults'))return;
      const results=document.getElementById('contactResults');results.innerHTML='';
      rows.forEach(u=>{const b=document.createElement('button');b.className='feature-btn member-select';b.textContent='Add '+u.display_name+' @'+u.username;b.onclick=async()=>{try{await request('/api/contacts/'+u.id,'POST');await showContacts();}catch(e){toast(e.message);}};results.appendChild(b);});
    } catch(e){toast(e.message);}
  };
  bind('importPhoneContacts',importPhoneContacts);
  bind('backupContacts',()=>downloadJSON(contacts,'goldchat-contacts.json'));
}
async function showBlocks() {
  const rows=await request('/api/blocks');panel('Blocked users','<div id="blockedList"></div>');
  const list=document.getElementById('blockedList');if(!rows.length)list.innerHTML='<p class="helper">No blocked users.</p>';
  rows.forEach(u=>{const b=document.createElement('button');b.className='feature-btn member-select';b.textContent='Unblock '+u.display_name;b.onclick=async()=>{try{b.disabled=true;await request('/api/blocks/'+u.id,'DELETE');await loadChats();await showBlocks();toast(u.display_name+' unblocked');}catch(e){b.disabled=false;toast(e.message);}};list.appendChild(b);});
}
async function showUpdatesPage(){
  const rows=await request('/api/social/statuses');
  const myLatest=rows.find(s=>s.user_id===ME.id&&s.expires_at*1000>Date.now());
  panel('Updates',`<section class="updates-page"><div class="my-status-row"><button class="my-status feature-btn" id="myStatusFromUpdates"><span class="status-add-avatar">${myLatest?avatarContent(ME):'+'}</span><span><strong>${myLatest?'My status':'Add status'}</strong><small>${myLatest?new Date(myLatest.created_at).toLocaleString():'Disappears after 24 hours'}</small></span></button>${myLatest?'<button type="button" class="status-add-more" id="addStatusFromUpdates" aria-label="Add another status">+</button>':''}</div><div class="status-quick-actions"><button class="feature-btn" id="quickTextStatus">✎ Text</button><button class="feature-btn" id="quickMediaStatus">▣ Photo or video</button></div><h4>Recent updates</h4><div id="updatesList"></div></section>`,'page');selectMainSection('Updates');
  bind('myStatusFromUpdates',myLatest?()=>showStatuses(ME.id):showAddStatusPage);
  if(myLatest)bind('addStatusFromUpdates',showAddStatusPage);
  bind('quickTextStatus',()=>showStatusComposer('text'));
  bind('quickMediaStatus',()=>showStatusComposer('media'));
  const list=document.getElementById('updatesList');
  if(!rows.some(s=>s.user_id!==ME.id&&s.expires_at*1000>Date.now())){list.innerHTML='<p class="helper">No recent updates from other people yet.</p>';return;}
  const newest=new Map();rows.filter(s=>s.expires_at*1000>Date.now()).forEach(s=>{if(!newest.has(s.user_id))newest.set(s.user_id,s);});
  newest.forEach(s=>{if(s.user_id===ME.id)return;const button=document.createElement('button');button.className='status-list-item';button.innerHTML=`<span class="status-ring">${avatarContent(s)}</span><span><strong>${escapeHtml(s.display_name)}</strong><small>${new Date(s.created_at).toLocaleString()}</small></span>`;button.onclick=()=>showStatuses(s.user_id);list.appendChild(button);});
}
function showAddStatusPage(){
  panel('Add status',`<p class="helper">Choose what to share. Your status disappears after 24 hours.</p><div class="status-create-actions">${action('statusTextAction','✎<span>Text</span>')}${action('statusMediaAction','▣<span>Photo / video</span>')}${action('statusAudioAction','♫<span>Audio file</span>')}${action('statusVoiceAction','🎙<span>Voice</span>')}</div>`,'page');selectMainSection('Updates');
  bind('statusTextAction',()=>showStatusComposer('text'));
  bind('statusMediaAction',()=>showStatusComposer('media'));
  bind('statusAudioAction',()=>showStatusComposer('audio'));
  bind('statusVoiceAction',()=>showStatusComposer('voice'));
}
function showChatThemes(){
  const choices=[['midnight','Midnight'],['gold','Gold Classic'],['dots','Gold dots'],['paper','Light paper']];
  panel('Chat theme',`<p class="helper">The chat bubble and wallpaper change together.</p><div class="theme-grid">${choices.map(([id,name])=>`<button class="theme-choice ${localStorage.getItem('gc_wallpaper')===id?'selected':''}" data-theme="${id}"><span class="theme-preview ${id}"><i></i><b></b></span>${name}</button>`).join('')}</div>${action('bubbleTheme','Chat bubble')}${action('wallpaperTheme','Wallpaper')}`);
  document.querySelectorAll('.theme-choice').forEach(button=>button.onclick=()=>{localStorage.setItem('gc_wallpaper',button.dataset.theme);applySettings();closePanel();toast('Chat theme updated');});
  bind('bubbleTheme',showAppearanceSettings);bind('wallpaperTheme',showAppearanceSettings);
}
async function showStatuses() {
  const rows=await request('/api/statuses');
  panel('Status updates','<p class="helper">Updates expire after 24 hours. New posts use your current profile privacy setting unless you choose an audience in Add status.</p>'+field('statusText','Share an update')+action('postStatus','Post status')+'<div id="statusList"></div>');
  bind('postStatus',async()=>{await request('/api/statuses','POST',{text:document.getElementById('statusText').value});await showStatuses();});
  const list=document.getElementById('statusList');if(!rows.length) list.innerHTML='<p class="helper">No updates yet.</p>';
  rows.forEach(s=>{const card=document.createElement('article');card.className='feature-card';card.innerHTML=`<strong>${escapeHtml(s.display_name)}</strong><p>${escapeHtml(s.text)}</p><small>${new Date(s.created_at).toLocaleString()}</small>`;if(s.user_id===ME.id){const b=document.createElement('button');b.className='feature-btn';b.textContent='Delete';b.onclick=async()=>{try{await request('/api/statuses/'+s.id,'DELETE');showStatuses();}catch(e){toast(e.message);}};card.appendChild(b);}list.appendChild(card);});
}
async function showStars() {
  const rows=await request('/api/stars');panel('Starred messages','<div id="starList"></div>');const list=document.getElementById('starList');
  if(!rows.length)list.innerHTML='<p class="helper">Open a message’s ⋯ menu to save it here.</p>';
  rows.forEach(m=>{const b=document.createElement('button');b.className='feature-btn member-select';b.textContent=m.sender.display_name+': '+(m.text || m.attachment?.name || 'Attachment');b.onclick=async()=>{closePanel();showArchived=!!chats.find(c=>c.id===m.chat_id)?.archived;await openChat(m.chat_id);};list.appendChild(b);});
}
function applySettings() {
  const theme=localStorage.getItem('gc_theme')||'dark';
  document.body.classList.toggle('light-theme',theme==='light'||(theme==='system'&&matchMedia('(prefers-color-scheme: light)').matches));
  document.body.classList.toggle('large-text',Number(localStorage.getItem('gc_text_size')||16)>=18);
  document.body.classList.toggle('reduce-motion',localStorage.getItem('gc_reduce_motion')==='on');
  document.body.dataset.wallpaper=localStorage.getItem('gc_wallpaper')||'midnight';
  document.documentElement.style.setProperty('--message-size',(Number(localStorage.getItem('gc_text_size')||16))+'px');
}
function showSettings() {
  panel('Settings',`<p class="helper">Choose what GOLDCHAT looks like, how it alerts you, and who can see your information.</p><div class="settings-list">${action('appearanceSettings','Appearance')}${action('notificationSettings','Notifications & sounds')}${action('storageSettings','Data & storage')}${action('privacySettings','Privacy & security')}${action('devicesSettings','Linked devices')}${action('permissionsMenu','Phone permissions')}${action('shortcutsSettings','Keyboard shortcuts')}${action('accountSettings','Account recovery')}</div>`);
  bind('appearanceSettings',showAppearanceSettings);bind('notificationSettings',showNotificationSettings);bind('storageSettings',showStorageSettings);bind('privacySettings',showPrivacySettings);bind('devicesSettings',showDevices);bind('permissionsMenu',showPhonePermissions);bind('shortcutsSettings',showKeyboardShortcuts);bind('accountSettings',showRecoveryContact);
}
function settingOn(key,fallback=true){const value=localStorage.getItem(key);return value===null?fallback:value==='on';}
function settingsCheckbox(id,label,key,fallback=true){return `<label class="setting-check"><input type="checkbox" id="${id}" ${settingOn(key,fallback)?'checked':''}> ${escapeHtml(label)}</label>`;}
function showAppearanceSettings(){
  panel('Appearance',`<div class="field"><label for="themeSetting">Color theme</label><select id="themeSetting"><option value="dark">Gold dark</option><option value="light">Gold light</option><option value="system">Use device setting</option></select></div><div class="field"><label for="textSize">Message text size: <span id="textSizeValue"></span></label><input id="textSize" type="range" min="14" max="22" step="1"></div><div class="field"><label for="wallpaperSetting">Chat wallpaper</label><select id="wallpaperSetting"><option value="midnight">Midnight</option><option value="gold">Gold glow</option><option value="paper">Light paper</option><option value="dots">Gold dots</option></select></div><div class="field"><label for="timeFormat">Time format</label><select id="timeFormat"><option value="12">12-hour</option><option value="24">24-hour</option></select></div>${settingsCheckbox('reduceMotion','Reduce animation','gc_reduce_motion',false)}${action('saveAppearance','Save appearance')}`);
  const size=document.getElementById('textSize');size.value=localStorage.getItem('gc_text_size')||'16';const output=document.getElementById('textSizeValue');output.textContent=size.value+' px';size.oninput=()=>output.textContent=size.value+' px';
  document.getElementById('themeSetting').value=localStorage.getItem('gc_theme')||'dark';document.getElementById('wallpaperSetting').value=localStorage.getItem('gc_wallpaper')||'midnight';document.getElementById('timeFormat').value=localStorage.getItem('gc_time_format')||'12';
  bind('saveAppearance',()=>{localStorage.setItem('gc_theme',document.getElementById('themeSetting').value);localStorage.setItem('gc_text_size',size.value);localStorage.setItem('gc_wallpaper',document.getElementById('wallpaperSetting').value);localStorage.setItem('gc_time_format',document.getElementById('timeFormat').value);localStorage.setItem('gc_reduce_motion',document.getElementById('reduceMotion').checked?'on':'off');applySettings();if(activeChatId)refreshMessages();renderChatList();closePanel();toast('Appearance saved');});
}
function showNotificationSettings(){
  panel('Notifications & sounds',`${settingsCheckbox('notifications','Phone & desktop notifications','gc_notifications',false)}${settingsCheckbox('notifyDirect','Private chats','gc_notify_direct')}${settingsCheckbox('notifyGroup','Groups','gc_notify_group')}${settingsCheckbox('notifyChannel','Channels','gc_notify_channel')}${settingsCheckbox('notifyStatus','Status updates','gc_notify_status',false)}${settingsCheckbox('notifyPreview','Show message preview','gc_notify_preview')}${settingsCheckbox('notifySound','Play notification sound','gc_notify_sound',false)}<p class="helper">Muted chats always stay silent. Phone notifications need permission from your browser or installed app.</p>${action('saveNotifications','Save notification settings')}`);
  bind('saveNotifications',async()=>{const enabled=document.getElementById('notifications').checked;for(const [id,key] of [['notifyDirect','gc_notify_direct'],['notifyGroup','gc_notify_group'],['notifyChannel','gc_notify_channel'],['notifyStatus','gc_notify_status'],['notifyPreview','gc_notify_preview'],['notifySound','gc_notify_sound']])localStorage.setItem(key,document.getElementById(id).checked?'on':'off');if(enabled&&!settingOn('gc_notifications',false))await enablePhoneNotifications();else if(!enabled&&settingOn('gc_notifications',false))await disablePhoneNotifications();else localStorage.setItem('gc_notifications',enabled?'on':'off');closePanel();toast('Notification settings saved');});
}
function showStorageSettings(){
  panel('Data & storage',`${settingsCheckbox('downloadImages','Auto-load photos','gc_auto_images')}${settingsCheckbox('downloadAudio','Auto-load voice notes','gc_auto_audio')}${settingsCheckbox('downloadVideo','Auto-load videos','gc_auto_video',false)}<p class="helper">Files download only when you tap them. GOLDCHAT does not keep private messages in its offline cache.</p>${action('clearLocalCache','Clear offline cache')}${action('saveStorage','Save data settings')}`);
  bind('clearLocalCache',async()=>{if('caches' in window){const keys=await caches.keys();await Promise.all(keys.filter(key=>key.startsWith('goldchat-')).map(key=>caches.delete(key)));}toast('Offline cache cleared. Your messages and account are safe.');});
  bind('saveStorage',()=>{for(const [id,key] of [['downloadImages','gc_auto_images'],['downloadAudio','gc_auto_audio'],['downloadVideo','gc_auto_video']])localStorage.setItem(key,document.getElementById(id).checked?'on':'off');closePanel();if(activeChatId)refreshMessages();toast('Data settings saved');});
}
async function showPrivacySettings(){
  const profile=await request('/api/profile');
  panel('Privacy & security',`<div class="field"><label for="profilePrivacy">Who can see your status and presence?</label><select id="profilePrivacy"><option value="everyone">Everyone</option><option value="contacts">My contacts</option><option value="nobody">Nobody</option></select></div><p class="helper">Profile photo and bio visibility follow this setting. Control disappearing messages separately for each chat.</p>${action('savePrivacy','Save privacy')}${action('blockedSettings','Blocked users')}${action('linkedDeviceSettings','Linked devices')}${action('recoverySettings','Email for password recovery')}`);
  document.getElementById('profilePrivacy').value=profile.privacy;
  bind('savePrivacy',async()=>{ME=await request('/api/profile','PATCH',{display_name:profile.display_name,bio:profile.bio,privacy:document.getElementById('profilePrivacy').value});closePanel();toast('Privacy saved');});bind('blockedSettings',showBlocks);bind('linkedDeviceSettings',showDevices);bind('recoverySettings',showRecoveryContact);
}
function showKeyboardShortcuts(){panel('Keyboard shortcuts','<div class="shortcut-row"><kbd>Ctrl</kbd><kbd>K</kbd><span>Search chats</span></div><div class="shortcut-row"><kbd>Ctrl</kbd><kbd>N</kbd><span>Start a new chat</span></div><div class="shortcut-row"><kbd>Esc</kbd><span>Close a menu</span></div><div class="shortcut-row"><kbd>Enter</kbd><span>Send a message</span></div><p class="helper">Use Shift + Enter for a new line in a message.</p>');}
async function showChatTools() {
  const c=chats.find(c=>c.id===activeChatId);if(!c)return;
  const blocked=c.type==='direct' && (await request('/api/blocks')).some(u=>u.id===c.peer.id);
  panel('Chat settings',`<p class="helper">Manage ${escapeHtml(c.title||c.peer?.display_name||'this conversation')}.</p><h4 class="settings-section-title">Conversation</h4><div class="feature-grid">${action('favoriteChat',isFavoriteChat(c)?'Remove from Favorites':'Add to Favorites')}${action('pinChat',c.pinned?'Unpin chat':'Pin chat')}${action('archiveChat',c.archived?'Unarchive chat':'Archive chat')}${action('muteChat',c.muted?'Unmute':'Mute notifications')}${action('disappearingChat','Disappearing messages')}</div><h4 class="settings-section-title">Messages</h4><div class="feature-grid">${action('searchMessages','Search messages')}${action('eventsChat','Events')}${action('pollsChat','Polls')}${action('tasksChat','Shared tasks')}${action('pinsChat','Pinned messages')}${action('importChat','Import messages')}${action('exportChat','Export this chat')}</div><h4 class="settings-section-title">People</h4><div class="feature-grid">${c.type==='direct'?action('viewChatProfile','View profile')+action('addChatContact','Add contact')+action('deleteChatContact','Delete contact')+action('previousChats','Previous conversations')+action('blockChatContact',blocked?'Unblock contact':'Block contact'):action('chatMembers','Members')}</div>`);
  bind('favoriteChat',()=>{const added=toggleFavoriteChat(c);closePanel();toast(added?'Added to Favorites':'Removed from Favorites');});
  for(const [id,key] of [['pinChat','pinned'],['archiveChat','archived'],['muteChat','muted']])bind(id,async()=>{const prefs={pinned:!!c.pinned,archived:!!c.archived,muted:!!c.muted};prefs[key]=!prefs[key];await request('/api/chats/'+c.id+'/preferences','POST',prefs);closePanel();await loadChats();toast('Chat settings saved');});
  bind('searchMessages',()=>{panel('Search messages',field('messageSearch','Search this conversation',messageQuery)+action('runMessageSearch','Search')+action('clearMessageSearch','Show all messages'));bind('runMessageSearch',async()=>{messageQuery=document.getElementById('messageSearch').value;closePanel();await refreshMessages();});bind('clearMessageSearch',async()=>{messageQuery='';closePanel();await refreshMessages();});});
  bind('eventsChat',showEvents);bind('pollsChat',showPolls);bind('tasksChat',showTasks);bind('pinsChat',showPins);bind('importChat',importMessages);bind('disappearingChat',showDisappearingSettings);
  bind('exportChat',async()=>{const data=await request('/api/export');downloadJSON(data.chats.find(x=>x.id===c.id),'goldchat-chat-'+c.id+'.json');});
  if(c.type==='direct') {
    bind('viewChatProfile',()=>showUserProfile(c.peer.id));
    bind('deleteChatContact',()=>confirmAction('Delete contact','Remove '+c.peer.display_name+' from your saved contacts? Chat messages will be kept.',async()=>{await request('/api/contacts/'+c.peer.id,'DELETE');closePanel();toast('Contact deleted');}));
    bind('previousChats',()=>{
      const history=chats.filter(x=>x.type==='direct' && x.peer?.id===c.peer.id);
      panel('Previous conversations','<p class="helper">Your earlier messages are kept here.</p><div id="previousChatList"></div>');
      const list=document.getElementById('previousChatList');
      history.forEach(x=>{const button=document.createElement('button');button.className='feature-btn member-select';button.textContent=(x.last_message?.iso?new Date(x.last_message.iso).toLocaleString():'Conversation')+(x.unread?' · '+x.unread+' unread':'');button.onclick=()=>{closePanel();openChat(x.id);};list.appendChild(button);});
    });
    bind('addChatContact',async()=>{await request('/api/contacts/'+c.peer.id,'POST');closePanel();toast('Contact added');});
    bind('blockChatContact',async()=>{const button=document.getElementById('blockChatContact');button.disabled=true;try{await request('/api/blocks/'+c.peer.id,blocked?'DELETE':'POST');await loadChats();await showChatTools();toast(blocked?'Contact unblocked':'Contact blocked');}catch(e){button.disabled=false;throw e;}});
  } else bind('chatMembers',showMembers);
}
async function showMembers() {
  const c=chats.find(c=>c.id===activeChatId);if(!c)return;
  const owner=c.owner_id===ME.id;
  panel('Members','<div id="memberList"></div>'+(owner?field('groupName','Group name',c.title)+action('renameGroup','Rename')+field('addMemberUsername','Username to add')+action('addMember','Add member'):action('leaveGroup','Leave '+c.type)));
  const list=document.getElementById('memberList');
  [ME,...c.members].forEach(u=>{
    const row=document.createElement('div');row.className='feature-card';
    const name=document.createElement('p');name.textContent=u.display_name+' @'+u.username+(c.owner_id===u.id?' · Owner':'');row.appendChild(name);
    const view=document.createElement('button');view.className='feature-btn';view.textContent='View profile';view.onclick=()=>showUserProfile(u.id);row.appendChild(view);
    if(owner && u.id!==ME.id) {
      const remove=document.createElement('button');remove.className='feature-btn';remove.textContent='Remove';
      remove.onclick=()=>confirmAction('Remove member','Remove '+u.display_name+' from this '+c.type+'?',async()=>{await request(`/api/groups/${c.id}/members/${u.id}`,'DELETE');await loadChats();await showMembers();});
      const transfer=document.createElement('button');transfer.className='feature-btn';transfer.textContent='Make owner';
      transfer.onclick=()=>confirmAction('Transfer ownership',u.display_name+' will manage this '+c.type+'. You will remain a member.',async()=>{await request(`/api/groups/${c.id}/owner`,'POST',{user_id:u.id});await loadChats();await showMembers();});
      row.append(remove,transfer);
    }
    list.appendChild(row);
  });
  if(owner) {
    bind('renameGroup',async()=>{await request(`/api/groups/${c.id}`,'PATCH',{title:document.getElementById('groupName').value});await loadChats();document.getElementById('hName').textContent=chats.find(x=>x.id===c.id).title;await showMembers();});
    bind('addMember',async()=>{const username=document.getElementById('addMemberUsername').value.trim();const rows=await request('/api/users/search?q='+encodeURIComponent(username));const u=rows.find(u=>u.username===username);if(!u)throw new Error('Exact username not found');await request(`/api/groups/${c.id}/members/${u.id}`,'POST');await loadChats();await showMembers();});
  } else bind('leaveGroup',async()=>{await request(`/api/groups/${c.id}/leave`,'POST');await handleMembershipRemoved(c.id);});
}
function confirmAction(title,text,fn) {panel(title,'<p>'+escapeHtml(text)+'</p>'+action('confirmAction','Confirm'));bind('confirmAction',fn);}
async function handleMembershipRemoved(cid) {
  if(activeChatId===cid) {
    saveDraft();activeChatId=null;replyTo=null;messageCache.clear();closePanel();
    document.getElementById('chatView').style.display='none';document.getElementById('emptyState').style.display='flex';document.getElementById('sidebar').classList.remove('hidden');
  }
  await loadChats();
}
function voiceAvatarMarkup(user){
  const avatar=user?.avatar_media_id?`<img src="/api/social/media/${encodeURIComponent(user.avatar_media_id)}" alt="" loading="lazy">`:escapeHtml(user?.avatar_initial||user?.display_name?.charAt(0)||'G');
  return `<span class="voice-avatar" aria-hidden="true">${avatar}<span class="voice-avatar-mic">${voiceMicSvg}</span></span>`;
}
const voiceBarHeights=[8,13,19,26,16,11,23,30,18,10,15,25,32,17,12,21,28,15,9,18,26,34,20,13,23,16,29,12,19,25,14,9];
function attachmentMarkup(file,message) {
  if(!file)return '';
  const url='/api/attachments/'+encodeURIComponent(file.id);
  const preview=url+'?inline=true';
  const mime=String(file.mime||'');
  const voice=mime.startsWith('audio/')&&/^voice[-_].+\.(webm|ogg|m4a|mp4|wav|mp3)$/i.test(file.name||'');
  if(voice){
    const bars=voiceBarHeights.map(height=>`<span style="height:${height}px"></span>`).join('');
    return `<div class="voice-note">${voiceAvatarMarkup(message?.sender||ME)}<button class="voice-play" type="button" aria-label="Play voice message"><svg class="voice-play-icon" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M8 5v14l11-7z"/></svg></button><div class="voice-track"><div class="voice-waveform" aria-hidden="true">${bars}</div><span class="voice-duration">0:00</span></div><audio src="${preview}" preload="${settingOn('gc_auto_audio')?'metadata':'none'}" aria-label="Voice message"></audio></div>`;
  }
  if(mime.startsWith('image/')){
    const label=escapeHtml(file.name||'Photo');
    if(settingOn('gc_auto_images'))return `<a class="image-preview-link" href="${preview}" target="_blank" rel="noopener noreferrer" aria-label="Open photo"><img class="media-preview" src="${preview}" alt="${label}" loading="lazy" referrerpolicy="no-referrer"></a>`;
    return `<button class="image-load" type="button" data-src="${preview}" data-name="${label}">View photo</button>`;
  }
  let media='';
  if(mime.startsWith('audio/')&&settingOn('gc_auto_audio'))media=`<audio class="audio-preview" aria-label="Audio attachment" src="${preview}" controls preload="metadata"></audio>`;
  else if(mime.startsWith('video/')&&settingOn('gc_auto_video',false))media=`<video class="media-preview" src="${preview}" controls preload="metadata" playsinline></video>`;
  return media+`<a class="file-link" href="${url}" target="_blank" rel="noopener noreferrer">📎 ${escapeHtml(file.name)} (${Math.ceil(file.size/1024)} KB)</a>`;
}
async function showEvents() {
  const cid=activeChatId;const rows=await request(`/api/chats/${cid}/events`);
  panel('Chat events',field('eventTitle','Title')+field('eventTime','Date & time','','datetime-local')+field('eventDescription','Description')+action('createEvent','Create event')+'<div id="eventList"></div>');
  const list=document.getElementById('eventList');rows.forEach(e=>{const card=document.createElement('article');card.className='feature-card';card.innerHTML=`<strong>${escapeHtml(e.title)}</strong><p>${new Date(e.starts_at).toLocaleString()}</p><p>${escapeHtml(e.description)}</p>`;list.appendChild(card);});
  bind('createEvent',async()=>{const date=new Date(document.getElementById('eventTime').value);if(Number.isNaN(date.getTime()))throw new Error('Choose a date and time');await request(`/api/chats/${cid}/events`,'POST',{title:document.getElementById('eventTitle').value,starts_at:date.toISOString(),description:document.getElementById('eventDescription').value});await showEvents();});
}
function messageActions(m) {
  panel('Message actions',`<div class="feature-grid">${action('replyMessage','Reply')}${action('copyMessage','Copy text')}${action('shareMessage','Share text')}${action('hideMessage','Delete for me')}${action('forwardMessage','Forward')}${action('starMessage',m.starred?'Unstar':'Star')}${action('pinMessage','Pin / unpin in chat')}${m.mine?action('editMessage','Edit')+action('deleteMessage','Delete for everyone'):''}</div><div class="emoji-grid">${['👍','❤️','😂','😮','😢','🙏'].map((e,i)=>action('react'+i,e)).join('')}</div>`);
  bind('copyMessage',()=>copyMessageText(m));bind('shareMessage',()=>shareMessageText(m));
  bind('hideMessage',async()=>{await request(`/api/social/messages/${m.id}/hide`,'POST');closePanel();await refreshMessages();});
  bind('replyMessage',()=>{replyTo=m.id;const bar=document.getElementById('replyBar');bar.hidden=false;bar.textContent='Replying to: '+m.text.slice(0,80)+' ';const cancel=document.createElement('button');cancel.className='feature-btn';cancel.textContent='Cancel';cancel.onclick=()=>{replyTo=null;bar.hidden=true;};bar.appendChild(cancel);closePanel();composerInput.focus();});
  bind('pinMessage',async()=>{const d=await request(`/api/messages/${m.id}/pin`,'POST');closePanel();toast(d.pinned?'Message pinned':'Message unpinned');});
  bind('starMessage',async()=>{await request(`/api/messages/${m.id}/star`,'POST');closePanel();await refreshMessages();});
  bind('forwardMessage',()=>{
    panel('Forward message','<p class="helper">Forward this message and its attachment to a conversation you belong to.</p><div id="forwardTargets"></div>');const list=document.getElementById('forwardTargets');
    chats.forEach(c=>{const b=document.createElement('button');b.className='feature-btn member-select';b.textContent=c.title||c.peer?.display_name||'Chat';b.onclick=async()=>{try{await request(`/api/messages/${m.id}/forward`,'POST',{chat_id:c.id});closePanel();toast('Message forwarded');}catch(e){toast(e.message);}};list.appendChild(b);});
  });
  if(m.mine) {
    bind('editMessage',()=>{panel('Edit message',field('editText','Message',m.text)+action('saveEdit','Save'));bind('saveEdit',async()=>{await request(`/api/messages/${m.id}`,'PATCH',{text:document.getElementById('editText').value});closePanel();await refreshMessages();});});
    bind('deleteMessage',()=>{panel('Delete message','<p>Delete this message for everyone in the conversation?</p>'+action('confirmDelete','Delete message'));bind('confirmDelete',async()=>{await request(`/api/messages/${m.id}`,'DELETE');closePanel();await refreshMessages();});});
  }
  ['👍','❤️','😂','😮','😢','🙏'].forEach((emoji,i)=>bind('react'+i,async()=>{await request(`/api/messages/${m.id}/reaction`,'POST',{emoji});closePanel();await refreshMessages();}));
}
async function sendFile(file,cid) {
  if(file.size>10*1024*1024)throw new Error('Choose a file smaller than 10 MB');
  const base64=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result).split(',')[1]);reader.onerror=()=>reject(new Error('Could not read file'));reader.readAsDataURL(file);});
  toast('Uploading '+file.name+'…');
  const uploaded=await request(`/api/chats/${cid}/uploads`,'POST',{name:file.name,data:base64,mime:file.type});
  await request(`/api/chats/${cid}/messages`,'POST',{text:'',attachment_id:uploaded.id});
  await onChatChanged(cid);toast('File sent');
}
uploadInput.onchange=async()=>{const file=uploadInput.files[0],cid=activeChatId;uploadInput.value='';if(!file||!cid)return;try{await sendFile(file,cid);}catch(e){toast(e.message);}};
let recorder=null,recordStarting=false,voiceRecordingStartedAt=0,voiceRecordingTicker=null;
function resetVoiceRecorderUI(){clearInterval(voiceRecordingTicker);voiceRecordingTicker=null;voiceRecordingBar.hidden=true;voiceBtn.classList.remove('recording');voiceBtn.innerHTML=voiceMicSvg;voiceBtn.title='Record voice message';voiceBtn.setAttribute('aria-label','Record voice message');syncComposerActions();}
function showVoiceRecorderUI(){voiceRecordingStartedAt=Date.now();voiceRecordingBar.hidden=false;voiceBtn.classList.add('recording');voiceBtn.innerHTML='<span aria-hidden="true">■</span>';voiceBtn.title='Stop recording and send';voiceBtn.setAttribute('aria-label','Stop recording and send');syncComposerActions();const timer=voiceRecordingBar.querySelector('time');const render=()=>{const seconds=Math.floor((Date.now()-voiceRecordingStartedAt)/1000);timer.textContent=Math.floor(seconds/60)+':'+String(seconds%60).padStart(2,'0');};render();voiceRecordingTicker=setInterval(render,500);}
function voiceRecordingOptions() {
  const mimeType=['audio/webm;codecs=opus','audio/mp4','audio/ogg;codecs=opus'].find(type=>MediaRecorder.isTypeSupported(type));
  return mimeType?{mimeType}:{};
}
voiceBtn.onclick=async()=>{
  if(recorder?.state==='recording'){recorder.stop();return;}
  if(recordStarting)return;
  if(!activeChatId)return toast('Open a chat first');
  if(!window.MediaRecorder || !navigator.mediaDevices)return toast('Voice recording needs a supported browser on HTTPS.');
  recordStarting=true;
  let stream;
  try {
    const cid=activeChatId;stream=await navigator.mediaDevices.getUserMedia({audio:true});
    const recording=new MediaRecorder(stream,voiceRecordingOptions()),chunks=[];
    recorder=recording;showVoiceRecorderUI();
    recording.ondataavailable=e=>{if(e.data.size)chunks.push(e.data);};
    const timer=setTimeout(()=>{if(recording.state==='recording')recording.stop();},120000);
    recording.onstop=async()=>{
      clearTimeout(timer);stream.getTracks().forEach(t=>t.stop());
      if(recorder===recording){recorder=null;resetVoiceRecorderUI();}
      try {
        const type=recording.mimeType||chunks[0]?.type||'audio/webm';
        const blob=new Blob(chunks,{type});if(!blob.size)throw new Error('Nothing was recorded. Please try again.');
        const ext=type.includes('mp4')?'m4a':type.includes('ogg')?'ogg':'webm';
        await sendFile(new File([blob],'voice-'+Date.now()+'.'+ext,{type}),cid);
      }catch(e){toast(e.message);}
    };
    recording.onerror=()=>{toast('Recording failed. Please try again.');if(recording.state!=='inactive')recording.stop();};
    recording.start();toast('Recording. Tap stop to send.');
  }catch(e){stream?.getTracks().forEach(t=>t.stop());toast('Microphone unavailable: '+e.message);}
  finally {recordStarting=false;}
};
document.addEventListener('keydown',e=>{if(e.key==='Escape')closePanel();if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='k'){e.preventDefault();document.getElementById('searchInput')?.focus();}if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='n'&&!e.target.closest('input,textarea,select')){e.preventDefault();openNewChatModal();}});
document.addEventListener('visibilitychange',()=>{if(!document.hidden && activeChatId)refreshMessages();});
applySettings();

/* Voice/video: peer-to-peer on localhost/HTTPS; no external relay configured. */
let call=null;
let pendingICE=[];
const videoBtn=document.getElementById('videoCallBtn');
const voiceCallBtn=document.getElementById('voiceCallBtn');
voiceCallBtn?.classList.add('call-header-btn');
voiceCallBtn.onclick=()=>startCall(false);
videoBtn.onclick=()=>startCall(true);
function signalCall(signal) {if(call)wsSend({type:'call_signal',chat_id:call.cid,signal:{...signal,call_id:call.id}});}
function callScreen(title,incoming=false) {
  document.getElementById('callOverlay')?.remove();
  const overlay=document.createElement('section');overlay.id='callOverlay';overlay.className='call-overlay';overlay.setAttribute('role','dialog');overlay.setAttribute('aria-label','Call');
  overlay.innerHTML=`<h2 id="callStatus">${escapeHtml(title)}</h2><p class="helper">Local-network call · Internet relay is not configured</p><video id="remoteVideo" autoplay playsinline></video><video id="localVideo" autoplay playsinline muted></video><div class="call-controls">${incoming?action('acceptCall','Accept')+action('declineCall','Decline'):action('muteCall','Mute microphone')+action('endCall','End call')}</div>`;
  document.body.appendChild(overlay);
  if(incoming){document.getElementById('acceptCall').onclick=acceptCall;document.getElementById('declineCall').onclick=()=>endCall(true);}
  else {
    document.getElementById('endCall').onclick=()=>endCall(true);
    document.getElementById('muteCall').onclick=e=>{if(!call?.stream)return;const tracks=call.stream.getAudioTracks();tracks.forEach(t=>t.enabled=!t.enabled);e.target.textContent=tracks[0]?.enabled?'Mute microphone':'Unmute microphone';};
  }
}
async function makePeer(video) {
  if(!navigator.mediaDevices?.getUserMedia || !window.RTCPeerConnection)throw new Error('Calls need a supported browser on localhost or HTTPS.');
  const state=call;
  const stream=await navigator.mediaDevices.getUserMedia({audio:true,video});
  if(call!==state){stream.getTracks().forEach(t=>t.stop());throw new Error('Call ended');}
  state.stream=stream;
  state.pc=new RTCPeerConnection({iceServers:[]});
  document.getElementById('localVideo').srcObject=stream;
  stream.getTracks().forEach(t=>state.pc.addTrack(t,stream));
  state.pc.ontrack=e=>{if(call===state)document.getElementById('remoteVideo').srcObject=e.streams[0];};
  state.pc.onicecandidate=e=>{if(e.candidate && call===state)signalCall({kind:'ice',candidate:e.candidate.toJSON()});};
  state.pc.onconnectionstatechange=()=>{
    if(call!==state)return;
    if(state.pc.connectionState==='connected' && !state.loggedConnected){state.loggedConnected=true;request('/api/social/calls/'+state.id,'POST',{action:'connected'}).catch(()=>{});}
    const status=document.getElementById('callStatus');if(status)status.textContent=state.pc.connectionState==='connected'?'Connected':state.pc.connectionState;
    if(['failed','closed'].includes(state.pc.connectionState)){toast('Call ended. Internet calls may need a TURN relay.');endCall(true);}
  };
}
async function startCall(video) {
  const c=chats.find(c=>c.id===activeChatId);
  if(!c || c.type!=='direct')return toast('Open a direct chat to call.');
  if(call)return toast('Finish the current call first.');
  if(!wsAlive)return toast('Reconnect before starting a call.');
  try {
    const logged=await request('/api/social/calls','POST',{chat_id:c.id,video});call={cid:c.id,id:logged.id,video};pendingICE=[];callScreen('Calling '+c.peer.display_name+'…');
    await makePeer(video);const offer=await call.pc.createOffer();await call.pc.setLocalDescription(offer);
    signalCall({kind:'offer',sdp:offer.sdp,video});
    call.timeout=setTimeout(()=>{toast('No answer.');endCall(true);},45000);
  } catch(e){toast(e.message);endCall(true);}
}
async function acceptCall() {
  if(!call?.offer)return;
  try {
    const offer=call.offer,video=call.video;
    callScreen('Connecting…');await makePeer(video);
    await call.pc.setRemoteDescription({type:'offer',sdp:offer});
    for(const candidate of pendingICE)await call.pc.addIceCandidate(candidate);pendingICE=[];
    const answer=await call.pc.createAnswer();await call.pc.setLocalDescription(answer);signalCall({kind:'answer',sdp:answer.sdp});
    clearTimeout(call.timeout);
  } catch(e){toast(e.message);endCall(true);}
}
async function handleCallSignal(d) {
  const s=d.signal;
  try {
    if(s.kind==='offer') {
      if(call){wsSend({type:'call_signal',chat_id:d.chat_id,signal:{kind:'busy'}});return;}
      call={cid:d.chat_id,id:s.call_id,offer:s.sdp,video:!!s.video};pendingICE=[];
      const c=chats.find(c=>c.id===d.chat_id);callScreen('Incoming '+(s.video?'video':'voice')+' call from '+(c?.peer?.display_name||'a contact'),true);
      call.timeout=setTimeout(()=>endCall(true),45000);return;
    }
    if(!call || call.cid!==d.chat_id)return;
    if(s.kind==='answer') {await call.pc.setRemoteDescription({type:'answer',sdp:s.sdp});for(const candidate of pendingICE)await call.pc.addIceCandidate(candidate);pendingICE=[];clearTimeout(call.timeout);}
    else if(s.kind==='ice') {if(call.pc?.remoteDescription)await call.pc.addIceCandidate(s.candidate);else pendingICE.push(s.candidate);}
    else if(['hangup','busy','unavailable'].includes(s.kind)){toast(s.kind==='busy'?'Contact is busy':s.kind==='unavailable'?'Contact is offline':'Call ended');endCall(false);}
  } catch(e){toast('Call error: '+e.message);endCall(true);}
}
function endCall(notify=false) {
  if(notify)signalCall({kind:'hangup'});
  if(call?.id && TOKEN)request('/api/social/calls/'+call.id,'POST',{action:'hangup'}).then(()=>refreshNotifications(true)).catch(()=>{});
  if(call){clearTimeout(call.timeout);call.pc?.close();call.stream?.getTracks().forEach(t=>t.stop());}
  call=null;pendingICE=[];document.getElementById('callOverlay')?.remove();
}
window.addEventListener('beforeunload',()=>{saveDraft();endCall(true);});
document.getElementById('logoutBtn').addEventListener('click',()=>endCall(true));

/* Device sessions and contact restore */
const originalSettings=showSettings;
showSettings=function() {
  originalSettings();
  const b=document.createElement('button');b.className='feature-btn';b.textContent='Manage signed-in devices';b.onclick=showDevices;document.querySelector('.feature-panel').appendChild(b);
};
async function showDevices() {
  const rows=await request('/api/devices');panel('Signed-in devices','<p class="helper">Sessions expire after 30 days. Revoking a session signs that device out.</p><div id="deviceList"></div>');
  rows.forEach((r,i)=>{const row=document.createElement('div');row.className='feature-card';row.textContent=(r.current?'This device':'Session '+(i+1))+' · expires '+new Date(r.expires_at*1000).toLocaleString();if(!r.current){const b=document.createElement('button');b.className='feature-btn';b.textContent='Sign out';b.onclick=async()=>{try{await request('/api/devices/'+r.id,'DELETE');await showDevices();}catch(e){toast(e.message);}};row.appendChild(b);}document.getElementById('deviceList').appendChild(row);});
}
const originalContacts=showContacts;
showContacts=async function() {
  await originalContacts();
  const b=document.createElement('button');b.className='feature-btn';b.textContent='Restore contact backup';document.querySelector('.feature-panel').appendChild(b);
  b.onclick=()=>{const input=document.createElement('input');input.type='file';input.accept='.json';input.onchange=async()=>{try{const file=input.files[0];if(!file)return;if(file.size>1024*1024)throw new Error('Backup must be smaller than 1 MB');const data=JSON.parse(await file.text());const rows=Array.isArray(data)?data:data.contacts;if(!Array.isArray(rows))throw new Error('Choose a GOLDCHAT contact backup');const result=await request('/api/contact-backup/import','POST',rows);await showContacts();toast(result.imported+' contacts restored');}catch(e){toast(e.message);}};input.click();};
};

async function showPolls() {
  const cid=activeChatId;const rows=await request(`/api/chats/${cid}/polls`);
  panel('Polls',field('pollQuestion','Question')+'<div class="field"><label for="pollOptions">Options, one per line (2–10)</label><textarea id="pollOptions" rows="4"></textarea></div>'+action('createPoll','Create poll')+'<div id="pollList"></div>');
  bind('createPoll',async()=>{await request(`/api/chats/${cid}/polls`,'POST',{question:document.getElementById('pollQuestion').value,options:document.getElementById('pollOptions').value.split('\n').filter(x=>x.trim())});await showPolls();});
  const list=document.getElementById('pollList');
  rows.forEach(p=>{const card=document.createElement('article');card.className='feature-card';const title=document.createElement('strong');title.textContent=p.question;card.appendChild(title);p.options.forEach((option,i)=>{const b=document.createElement('button');b.className='feature-btn member-select';b.textContent=(p.my_vote===i?'✓ ':'')+option+' · '+p.counts[i]+' votes';b.onclick=async()=>{try{await request(`/api/polls/${p.id}/vote`,'POST',{option_index:i});await showPolls();}catch(e){toast(e.message);}};card.appendChild(b);});list.appendChild(card);});
}
async function showTasks() {
  const cid=activeChatId;const rows=await request(`/api/chats/${cid}/tasks`);
  panel('Shared tasks',field('taskTitle','New task')+action('createTask','Add task')+'<div id="taskList"></div>');
  bind('createTask',async()=>{await request(`/api/chats/${cid}/tasks`,'POST',{title:document.getElementById('taskTitle').value});await showTasks();});
  rows.forEach(t=>{const b=document.createElement('button');b.className='feature-btn member-select';b.textContent=(t.completed?'✓ ':'☐ ')+t.title;b.onclick=async()=>{try{await request(`/api/tasks/${t.id}`,'PATCH',{completed:!t.completed});await showTasks();}catch(e){toast(e.message);}};document.getElementById('taskList').appendChild(b);});
}
async function showPins() {
  const rows=await request(`/api/chats/${activeChatId}/pins`);panel('Pinned messages','<div id="pinList"></div>');const list=document.getElementById('pinList');
  if(!rows.length)list.innerHTML='<p class="helper">Pin a message from its ⋯ menu.</p>';
  rows.forEach(m=>{const b=document.createElement('button');b.className='feature-btn member-select';b.textContent=m.sender.display_name+': '+(m.text||m.attachment?.name||'Attachment');b.onclick=()=>messageActions(m);list.appendChild(b);});
}
function importMessages() {
  const cid=activeChatId;
  panel('Import messages','<p class="helper">Imported text will be posted by your account and labelled with the original sender’s name. Files and original timestamps are not imported. This adds messages to the current chat.</p>'+action('chooseImport','Choose a GOLDCHAT chat export'));
  bind('chooseImport',()=>{const input=document.createElement('input');input.type='file';input.accept='.json';input.onchange=async()=>{try{const file=input.files[0];if(!file)return;if(file.size>5*1024*1024)throw new Error('Choose an export under 5 MB');const data=JSON.parse(await file.text());if(!Array.isArray(data.messages))throw new Error('Choose a single-chat export from the chat menu');const result=await request(`/api/chats/${cid}/import`,'POST',{messages:data.messages});closePanel();await onChatChanged(cid);toast(result.imported+' messages imported');}catch(e){toast(e.message);}};input.click();});
}
