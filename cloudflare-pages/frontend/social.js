let notificationIds=new Set(),notificationAccount=null,notificationItems=[];
let socialCleanup=null;
let lastStatusRailAt=0;
let statusRailExpiryTimer=null;
const basePanel=panel,baseClosePanel=closePanel;
function cleanSocialPanel(){if(socialCleanup){const fn=socialCleanup;socialCleanup=null;fn();}}
panel=function(title,html,layout){cleanSocialPanel();return basePanel(title,html,layout);};
closePanel=function(){cleanSocialPanel();baseClosePanel();};
function socialMediaURL(id){return '/api/social/media/'+id;}
function avatarContent(user){return user?.avatar_media_id?`<img src="${socialMediaURL(user.avatar_media_id)}" alt="" referrerpolicy="no-referrer">`:escapeHtml(user?.avatar_initial||'G');}
function paintAvatar(el,user){if(el)el.innerHTML=avatarContent(user);}
async function fileData(file){if(file.size>10*1024*1024)throw new Error('Choose a file under 10 MB');return new Promise((resolve,reject)=>{const r=new FileReader();r.onload=()=>resolve(String(r.result).split(',')[1]);r.onerror=()=>reject(new Error('Could not read file'));r.readAsDataURL(file);});}
async function uploadSocialFile(file,purpose){return request('/api/social/media','POST',{name:file.name,mime:file.type,purpose,data:await fileData(file)});}
function socialMediaMarkup(file){
  if(!file)return '';const url=socialMediaURL(file.id);
  if(file.mime.startsWith('image/'))return `<img class="status-media" src="${url}" alt="${escapeHtml(file.name)}" referrerpolicy="no-referrer">`;
  if(file.mime.startsWith('audio/'))return `<audio class="audio-preview" src="${url}" controls preload="none"></audio>`;
  if(file.mime.startsWith('video/'))return `<video class="status-media" src="${url}" controls playsinline preload="metadata"></video>`;
  return '';
}
async function initializeSocial(){
  const response=await fetch('/api/social/session-cookie',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({token:TOKEN})});
  if(!response.ok)throw new Error('Could not establish the private media session');
  paintAvatar(document.getElementById('meAvatar'),ME);
  // Do not hold up the chat list for notification and status data.  These
  // widgets are refreshed just after the main conversation screen appears.
  setTimeout(()=>hydrateSocialWidgets(),0);
}
async function hydrateSocialWidgets(){
  await refreshNotifications(false);
  refreshStatusRail();
  if(localStorage.getItem('gc_notifications')==='on')syncPhonePush().catch(()=>{});
  const params=new URLSearchParams(location.search);
  if(params.get('device_link') && params.get('approval'))await approveDeviceCode(params.get('device_link'),params.get('approval'));
  else if(params.get('contact'))await showScannedContact(params.get('contact'));
  else if(/^\d+$/.test(params.get('chat')||'')){await loadChats();await openChat(Number(params.get('chat')));}
}
async function refreshNotifications(notify=false){
  if(!TOKEN||!ME)return;
  try{
    if(notificationAccount!==ME.id){notificationIds.clear();notificationAccount=ME.id;notify=false;}
    const data=await request('/api/social/notifications');notificationItems=data.items;
    const bell=document.getElementById('notificationBell');if(bell){bell.textContent='🔔'+(data.unread?' '+data.unread:'');bell.setAttribute('aria-label',data.unread+' unread notifications');}
    let newStatus=false;
    for(const n of data.items){const fresh=!notificationIds.has(n.id);notificationIds.add(n.id);if(fresh&&n.kind==='status')newStatus=true;if(!notify||!fresh||n.read_at)continue;
      const chat=chats.find(c=>c.id===n.chat_id);
      const category=chat?.type==='group'?'gc_notify_group':chat?.type==='channel'?'gc_notify_channel':'gc_notify_direct';
      if((n.kind==='status'&&!settingOn('gc_notify_status',false))||(n.kind==='message'&&!settingOn(category))||chat?.muted)continue;
      const body=settingOn('gc_notify_preview')?n.body:'New message';
      if(document.hidden && 'Notification' in window && Notification.permission==='granted' && localStorage.getItem('gc_notifications')==='on'){
        try{const registration=await navigator.serviceWorker.ready;await registration.showNotification(n.title,{body,tag:'goldchat-chat-'+(n.chat_id||n.id),icon:'/static/icons/icon-192.png',data:{url:'/?chat='+(n.chat_id||'')}});if(settingOn('gc_notify_sound',false))playNotificationSound();}catch(e){console.error('Phone notification failed');}
      }else if(n.chat_id!==activeChatId || n.kind!=='message'){toast(n.title+': '+body);if(settingOn('gc_notify_sound',false))playNotificationSound();}
    }
    if(newStatus&&notify)refreshStatusRail();
  }catch(e){console.error('Notification update failed',e);}
}
function playNotificationSound(){try{const audio=new Audio('data:audio/wav;base64,UklGRjIAAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQ4AAAAAAP8AAP8AAP8AAP8AAP8A');audio.volume=.15;audio.play().catch(()=>{});}catch(e){}}
async function openNotification(n){try{await request('/api/social/notifications/'+n.id+'/read','POST');closePanel();await refreshNotifications();if(n.kind==='status')await showStatuses();else if(n.kind==='device')await showDevices();else if(n.kind==='call')await showCallHistory();else if(n.chat_id){await loadChats();await openChat(n.chat_id);}}catch(e){toast(e.message);}}
async function showNotificationInbox(){
  await refreshNotifications();panel('Notifications',action('readNotifications','Mark all read')+'<div id="notificationList"></div>');bind('readNotifications',async()=>{await request('/api/social/notifications/read','POST');await showNotificationInbox();});
  const list=document.getElementById('notificationList');if(!notificationItems.length)list.innerHTML='<p class="helper">No notifications yet.</p>';
  notificationItems.forEach(n=>{const b=document.createElement('button');b.className='feature-btn member-select'+(!n.read_at?' unread-notification':'');b.innerHTML=`<strong>${escapeHtml(n.title)}</strong><span>${escapeHtml(n.body)}</span><small>${new Date(n.created_at).toLocaleString()}</small>`;b.onclick=()=>openNotification(n);list.appendChild(b);});
}
const notificationBell=document.createElement('button');notificationBell.id='notificationBell';notificationBell.className='feature-btn';notificationBell.textContent='🔔';notificationBell.title='Notifications';notificationBell.onclick=showNotificationInbox;toolbar.prepend(notificationBell);
const profileBeforePhotos=showProfile;
showProfile=async function(){
  await profileBeforePhotos();const data=await request('/api/profile');const wrap=document.createElement('div');wrap.className='profile-photo-controls';wrap.innerHTML=`<div class="profile-photo">${avatarContent(data)}</div>${action('chooseProfilePhoto','Choose profile picture')}${data.avatar_media_id?action('removeProfilePhoto','Remove picture'):''}`;document.querySelector('.panel-heading').after(wrap);
  bind('chooseProfilePhoto',()=>{const input=document.createElement('input');input.type='file';input.accept='image/png,image/jpeg,image/webp,image/gif';input.onchange=async()=>{try{const file=input.files[0];if(!file)return;await uploadSocialFile(file,'avatar');ME=await request('/api/profile');paintAvatar(document.getElementById('meAvatar'),ME);await loadChats();await showProfile();toast('Profile picture updated');}catch(e){toast(e.message);}};input.click();});
  if(data.avatar_media_id)bind('removeProfilePhoto',async()=>{await request('/api/social/avatar','DELETE');ME=await request('/api/profile');paintAvatar(document.getElementById('meAvatar'),ME);await showProfile();});
};
async function refreshStatusRail(providedRows=null){
  if(!TOKEN||!ME)return;
  const uid=ME.id;
  try{
    const rows=providedRows||await request('/api/social/statuses');
    if(!ME||ME.id!==uid)return;
    lastStatusRailAt=Date.now();
    const rail=document.getElementById('storyRail');
    if(!rail)return;
    rail.innerHTML='';
    const latest=new Map();
    rows.filter(s=>s.expires_at*1000>Date.now()).forEach(s=>{if(!latest.has(s.user_id))latest.set(s.user_id,s);});
    clearTimeout(statusRailExpiryTimer);
    const nextExpiry=Math.min(...rows.map(s=>s.expires_at*1000).filter(time=>time>Date.now()));
    if(Number.isFinite(nextExpiry))statusRailExpiryTimer=setTimeout(refreshStatusRail,Math.max(1000,nextExpiry-Date.now()+250));
    const own=latest.get(uid);
    const addStory=(s,mine=false)=>{
      const button=document.createElement('button');
      button.type='button';button.className='story-item'+(s?' has-story':'');
      button.setAttribute('aria-label',mine?(s?'View my status':'Add my status'):'View '+s.display_name+' status');
      const avatar=document.createElement('span');avatar.className='story-avatar';
      avatar.innerHTML=avatarContent(mine?ME:s);
      const label=document.createElement('span');label.className='story-label';label.textContent=mine?'My status':s.display_name;
      button.append(avatar,label);
      button.onclick=()=>showStatuses(mine&&!s?null:(mine?uid:s.user_id));
      rail.appendChild(button);
    };
    addStory(own,true);
    for(const [userId,s] of latest)if(userId!==uid)addStory(s);
  }catch(error){console.error('Status updates could not load',error);}
}
document.addEventListener('visibilitychange',()=>{if(!document.hidden&&TOKEN&&Date.now()-lastStatusRailAt>60000)refreshStatusRail();});
showStatuses=async function(focusUserId=null){
  const rows=await request('/api/social/statuses');refreshStatusRail(rows);panel('Status updates','<p class="helper">Post photos, videos, audio or text. Every status disappears 24 hours after posting and follows your profile privacy setting.</p>'+field('statusText','Text or caption')+'<label class="feature-btn file-picker">Choose photo, video or audio<input id="statusFile" type="file" accept="image/png,image/jpeg,image/gif,image/webp,video/mp4,video/webm,audio/*"></label><div id="statusFileName" class="helper"></div>'+action('postStatus','Post status')+action('recordStatusAudio','Record audio status')+'<div id="statusList"></div>','page');selectMainSection('Updates');
  document.getElementById('statusFile').onchange=e=>{document.getElementById('statusFileName').textContent=e.target.files[0]?.name||'';};
  bind('postStatus',async()=>{const file=document.getElementById('statusFile').files[0];const text=document.getElementById('statusText').value;const media=file?await uploadSocialFile(file,'status'):null;await request('/api/social/statuses','POST',{text,media_id:media?.id||null});await showStatuses();});
  let recording=null,stream=null,chunks=[],stopped=false,timeout;
  socialCleanup=()=>{clearTimeout(timeout);stopped=true;if(recording?.state==='recording')recording.stop();stream?.getTracks().forEach(t=>t.stop());};
  document.getElementById('recordStatusAudio').onclick=async()=>{
    if(recording?.state==='recording'){recording.stop();return;}
    try{if(!navigator.mediaDevices||!window.MediaRecorder)throw new Error('Recording requires a supported browser on localhost or HTTPS');stream=await navigator.mediaDevices.getUserMedia({audio:true});if(stopped){stream.getTracks().forEach(t=>t.stop());return;}recording=new MediaRecorder(stream);chunks=[];recording.ondataavailable=e=>{if(e.data.size)chunks.push(e.data);};
      recording.onstop=async()=>{clearTimeout(timeout);stream.getTracks().forEach(t=>t.stop());if(stopped)return;try{const blob=new Blob(chunks,{type:recording.mimeType});const ext=blob.type.includes('mp4')?'m4a':blob.type.includes('ogg')?'ogg':'webm';const media=await uploadSocialFile(new File([blob],'status-audio.'+ext,{type:blob.type}),'status');await request('/api/social/statuses','POST',{text:document.getElementById('statusText')?.value||'',media_id:media.id});await showStatuses();}catch(e){toast(e.message);}};
      recording.start();document.getElementById('recordStatusAudio').textContent='Stop & post audio';timeout=setTimeout(()=>{if(recording?.state==='recording')recording.stop();},120000);
    }catch(e){toast('Microphone unavailable: '+e.message);}
  };
  const list=document.getElementById('statusList');if(!rows.length)list.innerHTML='<p class="helper">No updates yet.</p>';
  rows.forEach(s=>{const card=document.createElement('article');card.className='feature-card status-card';card.dataset.expires=s.expires_at;card.dataset.userId=s.user_id;setTimeout(()=>card.remove(),Math.max(0,s.expires_at*1000-Date.now()));card.innerHTML=`<div class="status-author"><div class="chat-avatar">${avatarContent(s)}</div><strong>${escapeHtml(s.display_name)}</strong></div>${socialMediaMarkup(s.media)}<p>${escapeHtml(s.text)}</p><small>Disappears ${new Date(s.expires_at*1000).toLocaleString()}</small>`;if(s.user_id===ME.id){const b=document.createElement('button');b.className='feature-btn';b.textContent='Delete status';b.onclick=async()=>{try{await request('/api/social/statuses/'+s.id,'DELETE');await showStatuses(ME.id);}catch(e){toast(e.message);}};card.appendChild(b);}list.appendChild(card);});
  if(focusUserId!=null)list.querySelector(`.status-card[data-user-id="${Number(focusUserId)}"]`)?.scrollIntoView({block:'nearest'});
};
async function copyMessageText(m){if(!m.text)throw new Error('No text to copy');if(navigator.clipboard?.writeText){await navigator.clipboard.writeText(m.text);toast('Text copied');closePanel();}else{panel('Copy text','<textarea id="manualCopy" class="manual-copy" readonly>'+escapeHtml(m.text)+'</textarea><p class="helper">Select and copy the text.</p>');document.getElementById('manualCopy').select();}}
async function shareMessageText(m){if(navigator.share)await navigator.share({title:'GOLDCHAT',text:m.text});else await copyMessageText(m);}
async function showDisappearingSettings(){
  const cid=activeChatId,data=await request(`/api/social/chats/${cid}/disappearing`);panel('Disappearing messages','<p class="helper">Applies to new messages. Existing messages keep their timers. Turning it off affects only future messages. Forwarded or downloaded copies may remain.</p><div class="field"><label for="disappearingTimer">Disappear after</label><select id="disappearingTimer"><option value="0">Off</option><option value="86400">24 hours</option><option value="604800">7 days</option><option value="7776000">90 days</option></select></div>'+action('saveDisappearing','Save setting'));document.getElementById('disappearingTimer').value=data.seconds;bind('saveDisappearing',async()=>{await request(`/api/social/chats/${cid}/disappearing`,'POST',{seconds:Number(document.getElementById('disappearingTimer').value)});closePanel();await loadChats();toast('Timer saved');});
}
async function showCallHistory(){
  const rows=await request('/api/social/calls');
  panel('Calls',`<div class="calls-toolbar"><input id="callSearch" type="search" placeholder="Search calls" aria-label="Search calls"><button class="feature-btn" id="newCallFromHistory">New call</button></div><h4 class="settings-section-title">Recent</h4><div id="callHistoryList"></div>`,'page');
  selectMainSection('Calls');
  const list=document.getElementById('callHistoryList');
  function renderCalls(){
    const query=document.getElementById('callSearch').value.trim().toLowerCase();list.innerHTML='';
    const matches=rows.filter(c=>(c.peer?.display_name||'').toLowerCase().includes(query));
    if(!matches.length){list.innerHTML='<p class="helper">'+(query?'No calls match your search.':'No calls yet. Start a call from a conversation.')+'</p>';return;}
    matches.forEach(c=>{
      const card=document.createElement('article');card.className='feature-card call-history-card';
      card.innerHTML=`<span class="call-direction" aria-hidden="true">${c.status==='missed'?'↙':c.direction==='outgoing'?'↗':'↙'}</span><div><strong>${escapeHtml(c.peer?.display_name||'Unknown contact')}</strong><p>${escapeHtml(c.direction)} ${c.video?'video':'voice'} · ${escapeHtml(c.status)}${c.duration?' · '+Math.floor(c.duration/60)+'m '+c.duration%60+'s':''}</p><small>${new Date(c.created_at*1000).toLocaleString()}</small></div>`;
      const open=document.createElement('button');open.className='feature-btn';open.textContent='Open chat';open.onclick=async()=>{closePanel();await loadChats();await openChat(c.chat_id);};card.appendChild(open);
      const again=document.createElement('button');again.className='feature-btn';again.textContent=c.video?'Video call':'Voice call';again.onclick=async()=>{closePanel();await loadChats();await openChat(c.chat_id);await startCall(!!c.video);};card.appendChild(again);list.appendChild(card);
    });
  }
  document.getElementById('callSearch').oninput=renderCalls;
  document.getElementById('newCallFromHistory').onclick=()=>{closePanel();document.getElementById('newChatBtn').click();};
  renderCalls();
}
showDevices=async function(){const rows=await request('/api/devices');panel('Linked devices',action('scanDeviceLink','Scan a device QR')+'<p class="helper">On another browser choose “Link device with QR” on its sign-in screen, then approve that code here. Both devices must reach this GOLDCHAT server.</p><div id="deviceList"></div>');bind('scanDeviceLink',showScanner);rows.forEach(r=>{const card=document.createElement('article');card.className='feature-card';card.innerHTML=`<strong>${escapeHtml(r.label||'Browser')}${r.current?' · This device':''}</strong><p>Expires ${new Date(r.expires_at*1000).toLocaleString()}</p>`;if(!r.current){const b=document.createElement('button');b.className='feature-btn';b.textContent='Unlink device';b.onclick=async()=>{try{await request('/api/devices/'+r.id,'DELETE');await showDevices();}catch(e){toast(e.message);}};card.appendChild(b);}document.getElementById('deviceList').appendChild(card);});};
async function showMyQR(){
  const url=location.origin+'/?contact='+encodeURIComponent(ME.username);panel('My QR & share',`<img class="qr-code" src="/api/social/contact-qr" alt="Your GOLDCHAT contact QR"><p class="helper">Scan to open your profile on this GOLDCHAT server.</p>${field('profileLink','Profile link',url)}${action('copyProfileLink','Copy link')}${action('shareProfileLink','Share')}${action('scanProfileCode','Scan code')}`);bind('copyProfileLink',async()=>{await navigator.clipboard.writeText(url);toast('Profile link copied');});bind('shareProfileLink',async()=>{if(navigator.share)await navigator.share({title:ME.display_name+' on GOLDCHAT',url});else{await navigator.clipboard.writeText(url);toast('Link copied');}});bind('scanProfileCode',showScanner);
}
async function showScannedContact(username){if(!/^[A-Za-z0-9_]{3,32}$/.test(username))throw new Error('Invalid contact code');const user=await request('/api/social/contact/'+encodeURIComponent(username));panel('GOLDCHAT contact',`<div class="profile-photo">${avatarContent(user)}</div><h3>${escapeHtml(user.display_name)}</h3><p>@${escapeHtml(user.username)}</p>${user.id!==ME.id?action('scannedAdd','Add contact')+action('scannedChat','Message'):''}`);if(user.id!==ME.id){bind('scannedAdd',async()=>{await request('/api/contacts/'+user.id,'POST');toast('Contact added');});bind('scannedChat',async()=>{const result=await request('/api/chats/direct/'+user.id,'POST');closePanel();await loadChats();await openChat(result.chat_id);});}if(location.search)history.replaceState(null,'',location.pathname);}
async function approveDeviceCode(id,challenge){const info=await request('/api/social/device-links/preview','POST',{id,challenge});panel('Approve linked device',`<p>Link <strong>${escapeHtml(info.label)}</strong> to your account?</p><p class="helper">Approve only a code displayed on a device you control. It will be able to read and send your messages until unlinked. Expires ${new Date(info.expires_at*1000).toLocaleTimeString()}.</p>${action('approveLink','Approve device')}${action('rejectLink','Cancel')}`);bind('approveLink',async()=>{await request('/api/social/device-links/approve','POST',{id,challenge});closePanel();history.replaceState(null,'',location.pathname);toast('Device approved');await showDevices();});bind('rejectLink',()=>{closePanel();history.replaceState(null,'',location.pathname);});}
async function handleScannedCode(text){let url;try{url=new URL(text,location.origin);}catch(e){throw new Error('Not a GOLDCHAT code');}if(url.searchParams.get('device_link')&&url.searchParams.get('approval'))await approveDeviceCode(url.searchParams.get('device_link'),url.searchParams.get('approval'));else if(url.searchParams.get('contact'))await showScannedContact(url.searchParams.get('contact'));else throw new Error('Choose a GOLDCHAT contact or device-link QR code');}
async function decodeQR(source){if('BarcodeDetector' in window){try{const found=await new BarcodeDetector({formats:['qr_code']}).detect(source);if(found.length)return found[0].rawValue;}catch(e){}}if(typeof jsQR!=='function')throw new Error('QR scanner unavailable');const canvas=document.createElement('canvas');const width=source.videoWidth||source.width,height=source.videoHeight||source.height;if(!width||!height)return null;const ratio=Math.min(1,1400/Math.max(width,height));canvas.width=Math.round(width*ratio);canvas.height=Math.round(height*ratio);const ctx=canvas.getContext('2d',{willReadFrequently:true});ctx.drawImage(source,0,0,canvas.width,canvas.height);const pixels=ctx.getImageData(0,0,canvas.width,canvas.height);return jsQR(pixels.data,pixels.width,pixels.height,{inversionAttempts:'attemptBoth'})?.data||null;}
function showScanner(){
  panel('Scan a GOLDCHAT code',`<video id="scanVideo" hidden autoplay playsinline muted class="scan-video"></video>${action('startScan','Use camera')}<label class="feature-btn file-picker">Scan QR image<input id="scanImage" type="file" accept="image/*"></label>${field('pasteCode','Or paste the GOLDCHAT link')}${action('usePastedCode','Open code')}`);let stream=null,active=true,timer;socialCleanup=()=>{active=false;clearTimeout(timer);stream?.getTracks().forEach(t=>t.stop());};bind('usePastedCode',()=>handleScannedCode(document.getElementById('pasteCode').value.trim()));
  document.getElementById('scanImage').onchange=async e=>{try{const file=e.target.files[0];if(!file)return;if(file.size>15*1024*1024)throw new Error('Choose a QR image under 15 MB');const image=await createImageBitmap(file),code=await decodeQR(image);image.close();if(!code)throw new Error('No QR found');await handleScannedCode(code);}catch(e){toast(e.message);}};
  bind('startScan',async()=>{if(!navigator.mediaDevices)throw new Error('Camera scanning requires localhost or HTTPS');stream=await navigator.mediaDevices.getUserMedia({video:{facingMode:'environment'}});if(!active){stream.getTracks().forEach(t=>t.stop());return;}const video=document.getElementById('scanVideo');video.hidden=false;video.srcObject=stream;await video.play();async function scan(){if(!active)return;try{const code=await decodeQR(video);if(code){await handleScannedCode(code);return;}}catch(e){toast(e.message);}timer=setTimeout(scan,300);}scan();});
}
async function showLinkDeviceQR(){panel('Link this device',field('newDeviceLabel','Device name','Linked browser')+action('generateLinkCode','Generate QR'));bind('generateLinkCode',async()=>{
  const label=document.getElementById('newDeviceLabel').value,response=await fetch('/api/social/device-links',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({label})}),data=await response.json();if(!response.ok)throw new Error(data.detail||'Could not create link');
  panel('Scan from your signed-in device',`<img class="qr-code" src="/api/social/device-links/${data.id}/qr?approval=${encodeURIComponent(data.challenge)}" alt="One-time device-link QR"><p class="helper">On your signed-in device choose Linked devices → Scan a device QR and approve. This code expires in five minutes.</p>${field('deviceApprovalLink','Approval link',data.url)}<p id="linkProgress" class="helper">Waiting for approval…</p>`);
  let active=true,claimed=false,timer;socialCleanup=()=>{active=false;clearTimeout(timer);if(!claimed)fetch('/api/social/device-links/'+data.id+'/cancel',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({poll_secret:data.poll_secret})}).catch(()=>{});};
  async function poll(){if(!active)return;try{const response=await fetch('/api/social/device-links/'+data.id+'/claim',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({poll_secret:data.poll_secret})}),result=await response.json();if(!response.ok)throw new Error(result.detail||'Link failed');if(!result.pending){claimed=true;TOKEN=result.token;ME=result.user;localStorage.setItem('gc_token',TOKEN);localStorage.setItem('gc_me',JSON.stringify(ME));closePanel();await enterApp();toast('Device linked');return;}timer=setTimeout(poll,2000);}catch(e){if(active&&document.getElementById('linkProgress'))document.getElementById('linkProgress').textContent=e.message;}}poll();
});}
const linkLogin=document.createElement('button');linkLogin.className='feature-btn link-login';linkLogin.textContent='Link device with QR';linkLogin.type='button';linkLogin.onclick=showLinkDeviceQR;document.getElementById('authForm').after(linkLogin);
setInterval(()=>{const now=Date.now()/1000;document.querySelectorAll('.status-card[data-expires]').forEach(el=>{if(Number(el.dataset.expires)<=now)el.remove();});let removed=false;document.querySelectorAll('.msg[data-expires]').forEach(el=>{if(Number(el.dataset.expires)<=now){messageCache.delete(Number(el.dataset.id));el.remove();removed=true;}});if(removed&&TOKEN)loadChats();if(TOKEN&&ME)refreshNotifications(true);},15000);

async function syncOwnProfile(){if(!TOKEN)return;try{ME=await request('/api/profile');paintAvatar(document.getElementById('meAvatar'),ME);document.getElementById('meName').textContent=ME.display_name;}catch(e){console.error(e);}}
