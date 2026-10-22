/* Permissions are requested only from a user button press. */
function pushKeyBytes(key){const text=atob(key.replace(/-/g,'+').replace(/_/g,'/')+'='.repeat((4-key.length%4)%4));return Uint8Array.from(text,c=>c.charCodeAt(0));}
async function syncPhonePush(){
  if(!('serviceWorker' in navigator)||!('PushManager' in window)||Notification.permission!=='granted')return false;
  const config=await request('/api/push/config');if(!config.enabled)return false;
  const registration=await navigator.serviceWorker.ready;
  let subscription=await registration.pushManager.getSubscription();
  if(!subscription)subscription=await registration.pushManager.subscribe({userVisibleOnly:true,applicationServerKey:pushKeyBytes(config.public_key)});
  await request('/api/push/subscribe','POST',subscription.toJSON());return true;
}
async function enablePhoneNotifications(){
  if(!('Notification' in window))throw new Error('Install GOLDCHAT on your home screen or use a browser that supports notifications.');
  const permission=await Notification.requestPermission();
  localStorage.setItem('gc_notifications',permission==='granted'?'on':'off');
  if(permission!=='granted')throw new Error('Allow notifications in Android Settings → Apps → GOLDCHAT → Notifications, and in browser site settings if needed.');
  const push=await syncPhonePush();
  toast(push?'Phone notifications enabled':'Notifications enabled while GOLDCHAT is open');
}
async function disablePhoneNotifications(){
  if('serviceWorker' in navigator){const registration=await navigator.serviceWorker.ready;const subscription=await registration.pushManager.getSubscription();if(subscription){await request('/api/push/unsubscribe','POST',{endpoint:subscription.endpoint});await subscription.unsubscribe();}}
  localStorage.setItem('gc_notifications','off');
}
async function showPhonePermissions(){
  let mic='Ask when needed',camera='Ask when needed';
  if(navigator.permissions){for(const name of ['microphone','camera']){try{const permission=await navigator.permissions.query({name});if(name==='microphone')mic=permission.state;else camera=permission.state;}catch(e){}}}
  const notifications='Notification' in window?Notification.permission:'Unavailable';
  const state=value=>value==='granted'?'Allowed':value==='denied'?'Blocked':value==='prompt'||value==='default'?'Ask when needed':value;
  panel('Phone permissions',`<div class="permission-panel"><p class="helper">Control what GOLDCHAT can use on this device.</p><div class="permission-status"><div><span>Notifications</span><strong>${escapeHtml(state(notifications))}</strong></div><div><span>Microphone</span><strong>${escapeHtml(state(mic))}</strong></div><div><span>Camera</span><strong>${escapeHtml(state(camera))}</strong></div></div><div class="permission-actions">${action('allowPhoneNotifications','Enable notifications')}${action('allowPhoneMic','Allow microphone')}${action('allowPhoneCamera','Allow camera')}${action('choosePhoneContacts','Import contacts')}</div><a class="permission-download" href="/static/downloads/goldchat-1.0.1.apk" download>Download Android app update <span>1.0.1</span></a><p class="permission-note">To change a blocked permission, open Android App info or your browser's site settings for <strong>${escapeHtml(location.host)}</strong>. Contact import shares only the contacts you select.</p></div>`);
  bind('allowPhoneNotifications',async()=>{await enablePhoneNotifications();await showPhonePermissions();});
  for(const [id,constraints] of [['allowPhoneMic',{audio:true}],['allowPhoneCamera',{video:true}]])bind(id,async()=>{if(!navigator.mediaDevices)throw new Error('Camera and microphone need HTTPS and a supported browser.');const stream=await navigator.mediaDevices.getUserMedia(constraints);stream.getTracks().forEach(t=>t.stop());await showPhonePermissions();toast('Permission granted');});
  bind('choosePhoneContacts',importPhoneContacts);
}
async function importPhoneContacts(){
  if(!navigator.contacts?.select)throw new Error('Phone contact picking is unavailable here. Open GOLDCHAT in Chrome on Android, or use Contacts search to add people by username.');
  const supported=await navigator.contacts.getProperties();const properties=['name','email','tel'].filter(x=>supported.includes(x));
  const selected=await navigator.contacts.select(properties,{multiple:true});if(!selected.length)return;
  const emails=[...new Set(selected.flatMap(c=>c.email||[]))].slice(0,100);
  const phones=[...new Set(selected.flatMap(c=>c.tel||[]))].slice(0,100);
  const matches=await request('/api/contacts/match-phone','POST',{emails,phones});
  panel('Review phone contacts','<p class="helper">Only contacts with a matching verified GOLDCHAT email or phone appear. Select Add to save each contact.</p><div id="phoneContactMatches"></div>');
  const list=document.getElementById('phoneContactMatches');if(!matches.length){list.textContent='No matching accounts. Try searching by GOLDCHAT username.';return;}
  matches.forEach(user=>{const button=document.createElement('button');button.className='feature-btn member-select';button.textContent='Add '+user.display_name+' @'+user.username;button.onclick=async()=>{button.disabled=true;try{await request('/api/contacts/'+user.id,'POST');button.textContent=user.display_name+' added';}catch(e){button.disabled=false;toast(e.message);}};list.appendChild(button);});
}
