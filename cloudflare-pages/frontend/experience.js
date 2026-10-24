/* Responsive GOLDCHAT navigation, personal chat management and settings. */
const oldUIIcon=uiIcon;
uiIcon=function(name){
  const paths={back:'<path d="M20 12H4m7-7-7 7 7 7"/>',search:'<circle cx="10" cy="10" r="7"/><path d="m15 15 6 6"/>',camera:'<path d="M3 7h4l2-3h6l2 3h4v14H3Z"/><circle cx="12" cy="13" r="4"/>',check:'<path d="m5 12 4 4L20 5"/>',logout:'<path d="M9 3H3v18h6m6-14 5 5-5 5M8 12h12"/>',trash:'<path d="M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7m4-7v7"/>',pencil:'<path d="m16 3 5 5L9 20l-6 1 1-6ZM13 6l5 5"/>',mute:'<path d="M4 9h4l5-5v16l-5-5H4ZM17 9l5 6m0-6-5 6"/>',volume:'<path d="M3 9h4l5-5v16l-5-5H3ZM16 8a6 6 0 0 1 0 8m3-11a10 10 0 0 1 0 14"/>',play:'<path d="m8 4 12 8-12 8Z"/>',pause:'<path d="M8 4v16M16 4v16"/>',heart:'<path d="M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.7l-1.1-1.1a5.5 5.5 0 0 0-7.8 7.8L12 21l8.8-8.6a5.5 5.5 0 0 0 0-7.8Z"/>',send:'<path d="m3 3 19 9-19 9 4-9Zm4 9h15"/>',eye:'<path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/>',info:'<circle cx="12" cy="12" r="9"/><path d="M12 11v6m0-10h.01"/>',link:'<path d="m9 15 6-6m-7 9-2 2a4 4 0 0 1-6-6l5-5a4 4 0 0 1 6 0m2-3 2-2a4 4 0 0 1 6 6l-5 5a4 4 0 0 1-6 0"/>',keyboard:'<rect x="2" y="5" width="20" height="14" rx="2"/><path d="M5 9h1m3 0h1m3 0h1m3 0h2M5 13h1m3 0h1m3 0h1m3 0h2M8 16h8"/>',accessibility:'<circle cx="12" cy="4" r="2"/><path d="M3 8l9 2 9-2M12 10v5m0 0-5 7m5-7 5 7"/>',language:'<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c-5 5-5 13 0 18 5-5 5-13 0-18Z"/>',lock:'<rect x="5" y="10" width="14" height="12" rx="2"/><path d="M8 10V6a4 4 0 0 1 8 0v4M12 15v3"/>',document:'<path d="M5 2h10l5 5v15H5ZM14 2v6h6M8 13h8m-8 4h8"/>',mic:'<rect x="9" y="2" width="6" height="12" rx="3"/><path d="M5 10a7 7 0 0 0 14 0M12 17v5m-4 0h8"/>',undo:'<path d="m7 4-5 5 5 5M2 9h12a7 7 0 0 1 0 14"/>',redo:'<path d="m17 4 5 5-5 5M22 9H10a7 7 0 0 0 0 14"/>',rotate:'<path d="M3 9a9 9 0 1 1 1 10M3 3v6h6"/>',crop:'<path d="M6 2v16h16M2 6h16v16"/>',draw:'<path d="m16 3 5 5L9 20l-6 1 1-6ZM13 6l5 5"/>',smile:'<circle cx="12" cy="12" r="9"/><path d="M8 14s4 5 8 0M8 9h.01M16 9h.01"/>'};
  return paths[name]?`<svg class="ui-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths[name]}</svg>`:oldUIIcon(name);
};
function iconButton(id,icon,label,extra=''){return `<button type="button" class="icon-btn ${extra}" id="${id}" title="${escapeHtml(label)}" aria-label="${escapeHtml(label)}">${uiIcon(icon)}</button>`;}
function runUI(fn){return ()=>Promise.resolve().then(()=>fn()).catch(e=>toast(e.message));}
function workspacePanel(title,html,section='More',back=null){
  panel(title,html,'page');
  const overlay=document.querySelector('#modalRoot .modal-overlay');overlay.classList.add('workspace-overlay');
  const page=overlay.querySelector('.feature-page');page.classList.add('workspace-page');
  const heading=page.querySelector('.panel-heading');
  heading.insertAdjacentHTML('afterbegin',iconButton('pageBack','back',back?'Back':'Back to chats'));
  document.getElementById('pageBack').onclick=back?runUI(back):closePanel;
  selectMainSection(section);return page;
}

const chatSelection={active:false,ids:new Set()};
function personalLists(){try{return JSON.parse(localStorage.getItem('gc_lists_'+ME?.id)||'[]').filter(x=>x&&typeof x.id==='string'&&Array.isArray(x.chats));}catch{return [];}}
function chatInCustomList(c,id){return personalLists().find(x=>x.id===id)?.chats.includes(favoriteChatKey(c));}
function paintListChips(){
  const filters=document.getElementById('chatFilters');filters.querySelectorAll('[data-custom-list],#addChatList').forEach(x=>x.remove());
  personalLists().forEach(list=>{const b=document.createElement('button');b.type='button';b.className='chat-filter';b.dataset.customList=list.id;b.dataset.filter='list:'+list.id;b.setAttribute('role','tab');b.textContent=list.name;b.onclick=()=>{chatListFilter=b.dataset.filter;renderChatList();};filters.appendChild(b);});
  const add=document.createElement('button');add.type='button';add.id='addChatList';add.className='chat-filter add-list';add.innerHTML=uiIcon('plus');add.setAttribute('aria-label','Create a chat list');add.onclick=()=>showChatLists(true);filters.appendChild(add);
}
function decorateChatRow(el,c){
  if(chatSelection.active){
    el.classList.toggle('selected',chatSelection.ids.has(c.id));el.setAttribute('aria-pressed',String(chatSelection.ids.has(c.id)));
    const check=document.createElement('input');check.type='checkbox';check.className='chat-select-checkbox';check.checked=chatSelection.ids.has(c.id);check.tabIndex=-1;check.setAttribute('aria-label','Select '+(c.peer?.display_name||c.title));
    check.onclick=e=>{e.stopPropagation();toggleChatSelection(c.id);};el.prepend(check);
  }
  el.oncontextmenu=e=>{e.preventDefault();startChatSelection(c.id);};
}
function startChatSelection(id=null){
  closePanel();chatSelection.active=true;if(id)chatSelection.ids.add(id);renderChatList();
}
function toggleChatSelection(id){if(chatSelection.ids.has(id))chatSelection.ids.delete(id);else chatSelection.ids.add(id);renderChatList();}
function endChatSelection(){chatSelection.active=false;chatSelection.ids.clear();renderChatList();}
function selectionChatIds(){return [...new Set([...chatSelection.ids].flatMap(conversationIds))];}
async function performBulk(actionName,ids=selectionChatIds()){
  if(!ids.length)throw new Error('Select at least one chat');
  await request('/api/chats/bulk','POST',{chat_ids:ids,action:actionName});
  if(['clear','delete','mark_unread'].includes(actionName)){
    messageCache.clear();
    if(ids.includes(activeChatId)){
      if(actionName!=='clear'){activeChatId=null;document.getElementById('chatView').style.display='none';document.getElementById('emptyState').style.display='flex';document.getElementById('sidebar').classList.remove('hidden');}
      else await refreshMessages(false);
    }
  }
  closePanel();endChatSelection();await loadChats();toast('Chats updated');
}
async function refreshPersonalChats(event){
  if(event.chat_ids?.includes(activeChatId)){
    if(['delete','mark_unread'].includes(event.action)){activeChatId=null;messageCache.clear();document.getElementById('chatView').style.display='none';document.getElementById('emptyState').style.display='flex';document.getElementById('sidebar').classList.remove('hidden');}
    else if(event.action==='clear')await refreshMessages(false);
  }
  await loadChats();
}
function showSelectionMenu(){
  if(!chatSelection.ids.size)return toast('Select chats first');
  panel('Selected chats',`<div class="settings-list">${menuAction('bulkUnread','Mark as unread','chats')}${menuAction('bulkRead','Mark as read','check')}${menuAction('bulkMute','Mute notifications','mute')}${menuAction('bulkUnmute','Unmute notifications','bell')}${menuAction('bulkArchive',showArchived?'Unarchive chats':'Archive chats','archive')}${menuAction('bulkClear','Clear selected chats','chats','Hide the message history for you')}${menuAction('bulkDelete','Delete selected chats','trash','Remove these conversations from your list')}</div>`);
  for(const [id,actionName] of [['bulkUnread','mark_unread'],['bulkRead','mark_read'],['bulkMute','mute'],['bulkUnmute','unmute'],['bulkArchive',showArchived?'unarchive':'archive']])bind(id,()=>performBulk(actionName));
  for(const [id,actionName] of [['bulkClear','clear'],['bulkDelete','delete']])bind(id,()=>{const ids=selectionChatIds();confirmAction(actionName==='clear'?'Clear selected chats?':'Delete selected chats?',actionName==='clear'?'This hides the selected history for your account. Other members keep their messages.':'This removes the selected chats and hides their history for your account. A new message will bring a chat back.',()=>performBulk(actionName,ids));});
}
const originalChatListRenderer=renderChatList;
renderChatList=function(){
  originalChatListRenderer();
  document.getElementById('sidebar').classList.toggle('selecting-chats',chatSelection.active);
  const count=document.getElementById('selectionCount');if(count)count.textContent=chatSelection.ids.size+' selected';
  const archive=document.getElementById('archivedCount');if(archive)archive.textContent=chats.filter(x=>x.archived).length||'';
  const label=document.getElementById('archivedLabel');if(label)label.textContent=showArchived?'Back to chats':'Archived';
  const unread=chats.filter(x=>x.unread&&!x.archived).length;
  for(const id of ['desktopChats','mobileChats']){const button=document.getElementById(id);button?.setAttribute('data-count',unread?String(unread):'');}
  document.querySelectorAll('[data-custom-list]').forEach(b=>{b.classList.toggle('active',chatListFilter===b.dataset.filter);b.setAttribute('aria-selected',String(chatListFilter===b.dataset.filter));});
};
function homeMenu(){
  panel('Chats menu',`<div class="settings-list">${menuAction('homeNewGroup','New group','contacts')}${menuAction('homeBroadcast','New broadcast','send')}${menuAction('homeDevices','Linked devices','devices')}${menuAction('homeStars','Starred messages','star')}${menuAction('homeSelect','Select chats','check')}${menuAction('homeRead','Mark all as read','check')}${menuAction('homeSettings','Settings','settings')}${menuAction('homeLogout','Log out','logout')}</div>`);
  document.querySelector('#modalRoot .modal-overlay').classList.add('home-menu-overlay');
  const routes={homeNewGroup:()=>showGroup('group'),homeBroadcast:showBroadcast,homeDevices:showDevices,homeStars:showStars,homeSelect:()=>startChatSelection(),homeRead:()=>performBulk('mark_read',chats.map(x=>x.id)),homeSettings:showSettings,homeLogout:()=>document.getElementById('logoutBtn').click()};
  for(const [id,fn] of Object.entries(routes))bind(id,fn);
}

async function showChatLists(create=false,existing=null){
  if(create){
    workspacePanel(existing?'Edit list':'New list',field('listName','List name',existing?.name||'')+'<p class="helper">Choose conversations to include in this filter.</p><div id="listChoices"></div>'+action('saveChatList','Save list'),'More',showChatLists);
    const root=document.getElementById('listChoices'),selected=new Set(existing?.chats||[]);
    uniqueHomeChats(chats).forEach(c=>{const key=favoriteChatKey(c),label=document.createElement('label');label.className='contact-choice';label.innerHTML=`<input type="checkbox" ${selected.has(key)?'checked':''}><span class="small-avatar">${c.peer?avatarContent(c.peer):'G'}</span><span>${escapeHtml(c.peer?.display_name||c.title||'Group')}</span>`;label.querySelector('input').onchange=e=>e.target.checked?selected.add(key):selected.delete(key);root.appendChild(label);});
    bind('saveChatList',()=>{const name=document.getElementById('listName').value.trim();if(!name||name.length>32)throw new Error('Use a list name between 1 and 32 characters');const lists=personalLists().filter(x=>x.id!==existing?.id);if(lists.length>=12)throw new Error('You can create up to 12 lists');lists.push({id:existing?.id||crypto.randomUUID(),name,chats:[...selected]});localStorage.setItem('gc_lists_'+ME.id,JSON.stringify(lists));paintListChips();renderChatList();showChatLists();});return;
  }
  workspacePanel('Lists',`<p class="helper">Create your own filters for people, groups and channels. Lists are saved on this device for your account.</p>${menuAction('newList','New list','plus')}<div id="savedLists"></div>`,'More',showSettings);bind('newList',()=>showChatLists(true));
  for(const list of personalLists()){const row=document.createElement('div');row.className='saved-list';row.innerHTML=`<button class="menu-action feature-btn"><span class="menu-copy"><strong>${escapeHtml(list.name)}</strong><small>${list.chats.length} conversations</small></span>${uiIcon('pencil')}</button><button class="icon-btn" aria-label="Delete ${escapeHtml(list.name)}">${uiIcon('trash')}</button>`;row.firstElementChild.onclick=()=>showChatLists(true,list);row.lastElementChild.onclick=()=>{localStorage.setItem('gc_lists_'+ME.id,JSON.stringify(personalLists().filter(x=>x.id!==list.id)));if(chatListFilter==='list:'+list.id)chatListFilter='all';paintListChips();renderChatList();showChatLists();};document.getElementById('savedLists').appendChild(row);}
}
async function showBroadcast(){
  const contacts=await request('/api/contacts');
  panel('New broadcast','<p class="helper">Send the same message separately to up to 20 contacts. Each reply stays in its own chat.</p><div id="broadcastContacts"></div><div class="field"><label for="broadcastText">Message</label><textarea id="broadcastText" maxlength="10000" rows="4"></textarea></div>'+action('sendBroadcast','Send broadcast'));
  const selected=new Set(),root=document.getElementById('broadcastContacts');
  contacts.forEach(c=>{const label=document.createElement('label');label.className='contact-choice';label.innerHTML=`<input type="checkbox"><span class="small-avatar">${avatarContent(c)}</span><span>${escapeHtml(c.display_name)}</span>`;label.querySelector('input').onchange=e=>e.target.checked?selected.add(c.id):selected.delete(c.id);root.appendChild(label);});if(!contacts.length)root.innerHTML='<p class="helper">Save contacts first from Settings → Contacts.</p>';
  bind('sendBroadcast',async()=>{const text=document.getElementById('broadcastText').value.trim();if(!text||!selected.size||selected.size>20)throw new Error('Write a message and select 1–20 contacts');let sent=0;for(const id of [...selected]){try{const c=await request('/api/chats/direct/'+id,'POST');await request('/api/chats/'+c.chat_id+'/messages','POST',{text});selected.delete(id);sent++;}catch(e){toast('Could not send to one contact: '+e.message);}}if(selected.size)throw new Error(`${sent} sent. Press send to retry the ${selected.size} remaining contacts.`);closePanel();await loadChats();toast('Broadcast sent to '+sent+' contacts');});
}

showSettings=async function(){
  const account=ME?.id;
  try{const profile=await request('/api/profile');if(ME?.id!==account)return;ME={...ME,...profile};}catch{if(!ME)return;}
  const rows=[['settingsProfile','Profile','profile','Name, photo, About and links',showProfile],['settingsAccount','Account','lock','Verified email, Google sign-in and recovery',showRecoveryContact],['settingsPrivacy','Privacy','shield','Presence, read receipts and blocked accounts',showPrivacySettings],['settingsLists','Lists','contacts','Manage your people and groups',showChatLists],['settingsChats','Chats','chats','Chat themes, history and backup',showChatSettings],['settingsAppearance','Appearance','theme','Wallpaper, bubble colors and app theme',showAppearanceSettings],['settingsNotifications','Notifications','bell','Message, group and call preferences',showNotificationSettings],['settingsInbox','Notification inbox','bell','View your recent alerts',showNotificationInbox],['settingsDevices','Linked devices','devices','Manage sessions and link a device',showDevices],['settingsContacts','Contacts','contacts','Find, import and manage contacts',showContacts],['settingsStorage','Storage and data','download','Media downloads and offline cache',showStorageSettings],['settingsAccess','Accessibility','accessibility','Text size, contrast and motion',showAccessibility],['settingsPermissions','Device permissions','mic','Camera, microphone and notifications',showPhonePermissions],['settingsShortcuts','Keyboard shortcuts','keyboard','Quick actions on desktop',showKeyboardShortcuts],['settingsHelp','Help and feedback','info','About GOLDCHAT and privacy details',showGoldchatHelp],['settingsInvite','Invite a friend','link','Share your GOLDCHAT contact link',showMyQR],['settingsUpdates','App updates','download','Check for the latest version',showAppUpdates]];
  if(typeof ownerAdminAllowed!=='undefined'&&ownerAdminAllowed)rows.push(['settingsOwner','Owner dashboard','shield','Manage accounts and moderation',showOwnerDashboard]);
  workspacePanel('Settings',`<div class="settings-search">${uiIcon('search')}<input id="settingsSearch" type="search" placeholder="Search settings" aria-label="Search settings"></div><button class="settings-identity" id="settingsIdentity"><span class="identity-avatar">${avatarContent(ME)}</span><strong>${escapeHtml(ME.display_name)}</strong><small>@${escapeHtml(ME.username)}</small><span class="identity-about">${escapeHtml(ME.bio||'Add a little about yourself')}</span></button><div class="identity-tools">${iconButton('settingsQR','qr','My QR code')}${iconButton('settingsEdit','pencil','Edit profile')}</div><div class="settings-list settings-sections">${rows.map(([id,title,icon,detail])=>menuAction(id,title,icon,detail)).join('')}${menuAction('settingsLogout','Log out','logout')}</div>`);
  bind('settingsIdentity',showProfile);bind('settingsQR',showMyQR);bind('settingsEdit',()=>showProfile(true));
  rows.forEach(([id,,,,fn])=>bind(id,fn));bind('settingsLogout',()=>document.getElementById('logoutBtn').click());
  document.getElementById('settingsSearch').oninput=e=>{const query=e.target.value.trim().toLowerCase();document.querySelectorAll('.settings-sections>.menu-action').forEach(row=>row.hidden=!row.textContent.toLowerCase().includes(query));};
};
showProfile=async function(edit=false){
  const data=await request('/api/profile');
  if(edit===true){
    workspacePanel('Edit profile',`<div class="profile-hero"><span class="identity-avatar">${avatarContent(data)}</span></div>${field('profileName','Name',data.display_name)}${field('profileBio','About',data.bio)}<p class="helper">Your username is @${escapeHtml(data.username)}. Manage sign-in details in Account settings.</p>${action('saveProfileDetails','Save changes')}`,'More',showProfile);
    bind('saveProfileDetails',async()=>{ME=await request('/api/profile','PATCH',{display_name:document.getElementById('profileName').value,bio:document.getElementById('profileBio').value,privacy:data.privacy});localStorage.setItem('gc_me',JSON.stringify(ME));paintAvatar(document.getElementById('meAvatar'),ME);document.getElementById('meName').textContent=ME.display_name;await showProfile();toast('Profile updated');});return;
  }
  workspacePanel('Profile',`<div class="profile-hero"><span class="identity-avatar">${avatarContent(data)}</span>${iconButton('profileCamera','camera','Change profile photo','gold-circle')}</div><div class="settings-list">${menuAction('editProfileName','Name','profile',data.display_name)}${menuAction('editProfileAbout','About','info',data.bio||'Set About')}${menuAction('profileUsername','Username','profile','@'+data.username)}${menuAction('profileAccount','Email and sign-in','lock',data.verified?'Email verified · Manage account':'Verify your email')}${menuAction('profileLink','Your contact link','link','Share your profile with a link or QR code')}${data.avatar_media_id?menuAction('profileRemovePhoto','Remove photo','trash'):''}</div>`,'More',showSettings);
  bind('editProfileName',()=>showProfile(true));bind('editProfileAbout',()=>showProfile(true));bind('profileUsername',()=>toast('@'+data.username+' is your sign-in username'));bind('profileAccount',showRecoveryContact);bind('profileLink',showMyQR);
  bind('profileCamera',()=>{const input=document.createElement('input');input.type='file';input.accept='image/png,image/jpeg,image/webp,image/gif';input.onchange=runUI(async()=>{if(!input.files[0])return;await uploadSocialFile(input.files[0],'avatar');await syncOwnProfile();await showProfile();toast('Profile photo updated');});input.click();});
  if(data.avatar_media_id)bind('profileRemovePhoto',async()=>{await request('/api/social/avatar','DELETE');await syncOwnProfile();await showProfile();});
};
function showChatSettings(){
  workspacePanel('Chats',`<div class="settings-list">${menuAction('chatThemeSettings','Chat theme','theme','Wallpaper and bubble colors')}${menuAction('chatListSettings','Lists','contacts','Your custom chat filters')}${menuAction('chatStarsSettings','Starred messages','star','Messages you saved')}${menuAction('chatBackupSettings','Export backup','download','Download your retained chats and account data')}${menuAction('chatRestoreSettings','Restore backup','document','Import a GOLDCHAT backup through Contacts')}${menuAction('chatArchiveSettings','Archived chats','archive','Conversations you archived')}</div>`,'More',showSettings);
  bind('chatThemeSettings',showChatThemes);bind('chatListSettings',showChatLists);bind('chatStarsSettings',showStars);bind('chatBackupSettings',async()=>downloadJSON(await request('/api/export'),'goldchat-backup.json'));bind('chatRestoreSettings',showContacts);bind('chatArchiveSettings',()=>{closePanel();showArchived=true;renderChatList();});
}
function showAccessibility(){
  workspacePanel('Accessibility',`<div class="field"><label for="accessText">Message text size</label><input id="accessText" type="range" min="14" max="22" value="${Number(localStorage.getItem('gc_text_size')||16)}"><output id="accessSize"></output></div>${settingsCheckbox('accessMotion','Reduce animations','gc_reduce_motion',false)}${settingsCheckbox('accessContrast','Increase contrast','gc_high_contrast',false)}${action('saveAccessibility','Save preferences')}`,'More',showSettings);
  const slider=document.getElementById('accessText'),output=document.getElementById('accessSize');slider.oninput=()=>output.textContent=slider.value+' px';slider.oninput();bind('saveAccessibility',()=>{localStorage.setItem('gc_text_size',slider.value);localStorage.setItem('gc_reduce_motion',document.getElementById('accessMotion').checked?'on':'off');localStorage.setItem('gc_high_contrast',document.getElementById('accessContrast').checked?'on':'off');applySettings();showSettings();});
}
function showGoldchatHelp(){workspacePanel('Help and feedback',`<div class="help-brand">${uiIcon('chats')}<h2>GOLDCHAT</h2><p>Your people. Your conversations.</p></div><p class="helper">Start a chat with the new-chat button. Share updates from the Updates tab, and use Settings to make GOLDCHAT yours.</p><div class="settings-list">${menuAction('helpShortcuts','Keyboard shortcuts','keyboard')}${menuAction('helpPrivacy','Privacy and admin access','shield')}${menuAction('helpDevices','Manage linked devices','devices')}${menuAction('helpUpdates','App updates','download')}</div>`,'More',showSettings);bind('helpShortcuts',showKeyboardShortcuts);bind('helpPrivacy',showPrivacyData);bind('helpDevices',showDevices);bind('helpUpdates',showAppUpdates);}
async function showAppUpdates(){workspacePanel('App updates',`<div class="help-brand">${uiIcon('check')}<h2>A fresh GOLDCHAT</h2><p>Desktop and phone experience</p></div><p class="helper">This version includes the new chat home, Settings, status editor, wallpapers and personal chat actions.</p>${action('checkAppUpdate','Reload latest version')}`,'More',showSettings);bind('checkAppUpdate',async()=>{const registration=await navigator.serviceWorker?.getRegistration();await registration?.update();location.reload();});}

const oldCommunitiesTab=openCommunitiesTab;
openCommunitiesTab=async function(){
  await loadChats();workspacePanel('Communities',`<p class="helper">Keep your groups and channels together.</p><div class="community-actions">${action('communityGroup',uiIcon('contacts')+'New group')}${action('communityChannel',uiIcon('plus')+'Create channel')}</div><div id="communityList"></div>`,'Communities');bind('communityGroup',()=>showGroup('group'));bind('communityChannel',()=>showGroup('channel'));
  const root=document.getElementById('communityList'),groups=chats.filter(c=>c.type!=='direct');if(!groups.length)root.innerHTML='<p class="helper">Your groups and channels will appear here.</p>';groups.forEach(c=>{const row=document.createElement('button');row.className='feature-btn update-person';row.innerHTML=`<span class="small-avatar">${uiIcon('contacts')}</span><span><strong>${escapeHtml(c.title||'Group')}</strong><small>${c.type==='channel'?'Channel':'Group'} · ${escapeHtml(c.last_message?.text||'Start a conversation')}</small></span>${uiIcon('chevron')}`;row.onclick=()=>{closePanel();openChat(c.id);};root.appendChild(row);});
};

// Listeners installed by the earlier modules keep their original function reference.
for(const prefix of ['desktop','mobile']){
  const updates=document.getElementById(prefix+'Updates');updates?.removeEventListener('click',showUpdatesPage);updates?.addEventListener('click',()=>runUI(showUpdatesPage)());
  const communities=document.getElementById(prefix+'Communities');communities?.removeEventListener('click',oldCommunitiesTab);communities?.addEventListener('click',runUI(openCommunitiesTab));
  document.getElementById(prefix+'Chats')?.addEventListener('click',()=>{showArchived=false;if(chatSelection.active)endChatSelection();else renderChatList();});
}
document.getElementById('featuresMenu').onclick=showSettings;
const settingsNav=document.getElementById('desktopMore');settingsNav.setAttribute('aria-label','Settings');settingsNav.title='Settings';settingsNav.innerHTML='<span>'+uiIcon('settings')+'</span><small>Settings</small>';
const railProfile=document.createElement('button');railProfile.type='button';railProfile.className='desktop-nav-item rail-profile';railProfile.setAttribute('aria-label','Your profile');railProfile.title='Your profile';railProfile.appendChild(document.getElementById('meAvatar'));railProfile.onclick=runUI(showProfile);document.querySelector('.desktop-nav').appendChild(railProfile);
const homeHeader=document.querySelector('.sidebar-header');homeHeader.insertAdjacentHTML('afterbegin','<h1 class="sidebar-brand">GOLD<span>CHAT</span></h1>');homeHeader.insertAdjacentHTML('beforeend',iconButton('homeCamera','camera','Post a photo or video status')+iconButton('desktopNewChat','plus','New chat','gold-circle')+iconButton('homeMenu','more','Chats menu'));
homeHeader.insertAdjacentHTML('afterend','<div class="home-intro"><span class="eyebrow">YOUR CONVERSATIONS</span><h2>Your circle<span>.</span></h2><p>A good conversation starts here.</p></div>');
document.querySelector('.desktop-nav').insertAdjacentHTML('afterbegin','<div class="rail-monogram" aria-hidden="true">G<span>•</span></div>');
document.getElementById('homeCamera').onclick=()=>runUI(()=>showStatusComposer('media'))();document.getElementById('homeMenu').onclick=homeMenu;document.getElementById('desktopNewChat').onclick=()=>document.getElementById('newChatBtn').click();
document.querySelector('.search-box input').placeholder='Search or start a new chat';
document.querySelector('.search-wrap').insertAdjacentHTML('beforebegin',`<div class="chat-selection-bar">${iconButton('cancelChatSelection','close','Cancel selection')}<strong id="selectionCount">0 selected</strong>${iconButton('selectionMenu','more','Selected chat actions')}</div>`);
document.getElementById('cancelChatSelection').onclick=endChatSelection;document.getElementById('selectionMenu').onclick=showSelectionMenu;
document.getElementById('chatList').insertAdjacentHTML('beforebegin',`<button type="button" class="archived-row" id="archivedRow">${uiIcon('archive')}<span id="archivedLabel">Archived</span><small id="archivedCount"></small></button>`);document.getElementById('archivedRow').onclick=()=>{showArchived=!showArchived;renderChatList();};
document.getElementById('emptyState').insertAdjacentHTML('beforeend',`<div class="welcome-actions">${menuAction('welcomeContacts','Add contact','contacts')}${menuAction('welcomeThemes','Personalize chats','theme')}</div><small class="welcome-footnote">GOLDCHAT for your everyday conversations</small>`);document.getElementById('welcomeContacts').onclick=runUI(showContacts);document.getElementById('welcomeThemes').onclick=()=>showChatThemes();
const priorExperienceEnter=enterApp;
enterApp=async function(...args){chatSelection.active=false;chatSelection.ids.clear();paintListChips();await priorExperienceEnter(...args);paintListChips();applySettings();renderChatList();};
const priorExperienceClear=clearSignedInState;
clearSignedInState=function(){chatSelection.active=false;chatSelection.ids.clear();priorExperienceClear();if(typeof clearAppearance==='function')clearAppearance();};
paintListChips();
