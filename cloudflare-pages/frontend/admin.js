/* Administrative permissions are checked by the server on every request. */
let ownerAdminAllowed=false;
let ownerState={tab:'overview',q:'',offset:0,accountState:'all',userId:null,userLabel:'',before:null};
let ownerObjectUrls=[];

async function ownerRequest(path,method='GET',body){
  const session=TOKEN;
  const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),25000);
  try{
    const response=await fetch('/api/admin/'+path,{method,cache:'no-store',signal:controller.signal,
      headers:{Authorization:'Bearer '+session,...(body?{'Content-Type':'application/json'}:{})},body:body?JSON.stringify(body):undefined});
    const data=await response.json();
    if(TOKEN!==session)throw new Error('Your session changed. Open the dashboard again.');
    if(response.status===401)clearSignedInState();
    else if(response.status===403){ownerAdminAllowed=false;closePanel();}
    if(!response.ok)throw new Error(typeof data.detail==='string'?data.detail:'The owner request could not be completed.');
    return data;
  }catch(error){
    if(error.name==='AbortError')throw new Error('The dashboard took too long to respond. Please refresh.');
    throw error;
  }finally{clearTimeout(timer);}
}

function ownerDate(value){
  if(!value)return '—';
  return new Date(typeof value==='number'?value*1000:value).toLocaleString([], {dateStyle:'medium',timeStyle:'short'});
}
function ownerEscape(value){return escapeHtml(String(value??''));}
function ownerStateBadge(user){
  const label=user.deleted_at?'Deleted':user.suspended_at?'Banned':user.is_owner?'Owner':'Active';
  return `<span class="owner-badge ${user.deleted_at||user.suspended_at?'restricted':''}">${label}</span>`;
}
function cleanOwnerMedia(){
  document.querySelectorAll('.owner-media audio,.owner-media video').forEach(el=>el.pause());
  ownerObjectUrls.forEach(url=>URL.revokeObjectURL(url));ownerObjectUrls=[];
}
function ownerError(error){const el=document.getElementById('ownerError');if(el)el.textContent=error.message;else toast(error.message);}

async function refreshOwnerAccess(){
  ownerAdminAllowed=false;
  if(!TOKEN)return;
  const session=TOKEN;
  try{
    const result=await ownerRequest('access');if(TOKEN!==session)return;ownerAdminAllowed=result.allowed===true;
    if(new URLSearchParams(location.search).get('admin')==='1'){
      if(ownerAdminAllowed)await showOwnerDashboard();
      else toast('Sign in with the designated owner account to open this dashboard.');
    }
  }catch(error){/* The owner tools are optional for ordinary accounts. */}
}
const enterAppWithOwnerTools=enterApp;
enterApp=async function(...args){
  ownerAdminAllowed=false;closePanel();
  await enterAppWithOwnerTools(...args);
  if(!document.getElementById('privacyReminder')){
    const note=document.createElement('div');note.id='privacyReminder';note.className='privacy-reminder';
    note.innerHTML='GOLDCHAT stores chats on its servers. Authorized admins can review retained content for support and moderation. <button type="button">Privacy details</button>';
    note.querySelector('button').onclick=showPrivacyData;
    document.querySelector('.search-wrap').before(note);
  }
  refreshOwnerAccess();
};

function showPrivacyData(){
  panel('Privacy & admin access',`<div class="privacy-copy"><p>GOLDCHAT stores accounts, messages, shared files and status updates on its servers. It currently does not provide end-to-end encryption.</p><h4>Support and moderation</h4><p>Only the designated owner administrator can review retained conversation content and media through the owner dashboard. A support or moderation reason is required, and each content review is recorded in an audit log.</p><h4>Deletion and expiry</h4><p>Expired disappearing messages and statuses are excluded from admin review. Deleted-message text is not shown. Administratively deleted accounts are disabled in a recoverable state; retained chat history remains available for moderation.</p><h4>Your account</h4><p>You can manage presence and read receipts in Privacy & security. For account or privacy questions, contact <a href="mailto:adewoleadewumi61@gmail.com">adewoleadewumi61@gmail.com</a>.</p></div>`);
}

async function showOwnerDashboard(tab='overview',options={}){
  if(!ownerAdminAllowed){toast('Owner access is required.');return;}
  cleanOwnerMedia();
  ownerState={tab,q:'',offset:0,accountState:'all',userId:null,userLabel:'',before:null,...options};
  const tabs=[['overview','Overview'],['users','Users'],['chats','Conversations'],['statuses','Statuses'],['calls','Calls'],['audit','Audit log']];
  panel('Owner dashboard',`<div class="owner-dashboard"><div class="owner-heading"><div><span class="owner-eyebrow">GOLDCHAT ADMINISTRATION</span><p>Review activity and manage accounts.</p></div><button type="button" class="feature-btn" id="ownerRefresh">Refresh</button></div><nav class="owner-tabs" aria-label="Owner dashboard sections">${tabs.map(([key,label])=>`<button type="button" data-owner-tab="${key}" class="${key===tab?'active':''}" ${key===tab?'aria-current="page"':''}>${label}</button>`).join('')}</nav><p id="ownerError" class="panel-error" role="alert"></p><section id="ownerContent" aria-live="polite"><p class="helper">Loading dashboard…</p></section></div>`,'page');
  selectMainSection('More');socialCleanup=cleanOwnerMedia;
  document.querySelector('.feature-page').classList.add('owner-console');
  document.querySelectorAll('[data-owner-tab]').forEach(button=>button.onclick=()=>showOwnerDashboard(button.dataset.ownerTab));
  document.getElementById('ownerRefresh').onclick=loadOwnerSection;
  await loadOwnerSection();
}

async function loadOwnerSection(){
  cleanOwnerMedia();
  const previous=document.getElementById('ownerContent');if(!previous)return;
  // Detach the old view so a slower response cannot overwrite a newer section.
  const content=previous.cloneNode(false);previous.replaceWith(content);
  document.getElementById('ownerError').textContent='';
  content.innerHTML='<p class="helper">Loading…</p>';
  document.getElementById('ownerRefresh').disabled=true;
  try{
    if(ownerState.tab==='overview')await ownerOverview(content);
    else if(ownerState.tab==='users')await ownerUsers(content);
    else if(ownerState.tab==='chats')await ownerChats(content);
    else if(ownerState.tab==='statuses')ownerStatusStart(content);
    else if(ownerState.tab==='calls')await ownerCalls(content);
    else if(ownerState.tab==='audit')await ownerAudit(content);
  }catch(error){if(content.isConnected){content.innerHTML='<p class="helper">This section could not load. Use Refresh to try again.</p>';ownerError(error);}}
  finally{const button=document.getElementById('ownerRefresh');if(button&&content.isConnected)button.disabled=false;}
}

async function ownerOverview(content){
  const data=await ownerRequest('overview');if(!content.isConnected)return;
  const labels={users:'Registered accounts',signups_24h:'New accounts · 24h',suspended:'Banned accounts',deleted_accounts:'Deleted accounts',conversations:'Conversations',messages:'Retained messages',statuses:'Active statuses',signed_in_accounts:'Accounts with valid sessions',calls_24h:'Calls · 24h'};
  content.innerHTML=`<div class="owner-stats">${Object.entries(labels).map(([key,label])=>`<article><small>${label}</small><strong>${Number(data.counts[key])||0}</strong></article>`).join('')}</div><h4>Latest registrations</h4><div class="owner-list">${data.recent_users.map(user=>`<div><span><strong>${ownerEscape(user.display_name)}</strong><small>@${ownerEscape(user.username)}</small></span><time>${ownerEscape(ownerDate(user.created_at))}</time></div>`).join('')||'<p class="helper">No accounts yet.</p>'}</div><h4>Service configuration</h4><div class="owner-service">${Object.entries({email_configured:'Verification email',google_configured:'Google sign-in',push_configured:'Push notifications',cloud_storage:'Cloud media storage'}).map(([key,label])=>`<span>${label}<b>${data.service[key]?'Configured':'Not configured'}</b></span>`).join('')}</div><p class="helper">Checked ${ownerEscape(ownerDate(data.checked_at))}. Session totals do not mean every account is currently online.</p>`;
}

function ownerPager(content,total,limit){
  const nav=document.createElement('div');nav.className='owner-pager';
  nav.innerHTML=`<button type="button" class="feature-btn" ${ownerState.offset===0?'disabled':''}>Previous</button><span>${total?ownerState.offset+1:0}–${Math.min(ownerState.offset+limit,total)} of ${total}</span><button type="button" class="feature-btn" ${ownerState.offset+limit>=total?'disabled':''}>Next</button>`;
  const buttons=nav.querySelectorAll('button');buttons[0].onclick=()=>{ownerState.offset=Math.max(0,ownerState.offset-limit);loadOwnerSection();};buttons[1].onclick=()=>{ownerState.offset+=limit;loadOwnerSection();};content.appendChild(nav);
}

async function ownerUsers(content){
  const data=await ownerRequest(`users?q=${encodeURIComponent(ownerState.q)}&state=${ownerState.accountState}&offset=${ownerState.offset}`);if(!content.isConnected)return;
  content.innerHTML=`<form class="owner-search" id="ownerUserSearch"><label><span class="sr-only">Search accounts</span><input id="ownerSearchText" placeholder="Search username, name or verified email" value="${ownerEscape(ownerState.q)}" maxlength="80"></label><select id="ownerAccountState" aria-label="Account state"><option value="all">All accounts</option><option value="active">Active</option><option value="banned">Banned</option><option value="deleted">Deleted</option></select><button class="feature-btn">Search</button></form><div class="owner-table-wrap"><table class="owner-table"><thead><tr><th>Account</th><th>Verified email</th><th>Joined</th><th>Activity</th><th>State</th><th>Actions</th></tr></thead><tbody>${data.items.map(user=>`<tr><td><strong>${ownerEscape(user.display_name)}</strong><small>@${ownerEscape(user.username)} · #${user.id}</small></td><td>${ownerEscape(user.verified_email||'Not verified')}</td><td>${ownerEscape(ownerDate(user.created_at))}</td><td>${user.message_count} messages<small>${user.chat_count} conversations</small></td><td>${ownerStateBadge(user)}</td><td><div class="owner-row-actions"><button type="button" class="feature-btn" data-user-chats="${user.id}">Chats</button><button type="button" class="feature-btn" data-user-manage="${user.id}">Manage</button></div></td></tr>`).join('')||'<tr><td colspan="6">No matching accounts.</td></tr>'}</tbody></table></div><div id="ownerManageAccount"></div>`;
  document.getElementById('ownerAccountState').value=ownerState.accountState;
  document.getElementById('ownerUserSearch').onsubmit=e=>{e.preventDefault();ownerState.q=document.getElementById('ownerSearchText').value.trim();ownerState.accountState=document.getElementById('ownerAccountState').value;ownerState.offset=0;loadOwnerSection();};
  content.querySelectorAll('[data-user-chats]').forEach(button=>button.onclick=()=>{const user=data.items.find(item=>item.id===Number(button.dataset.userChats));showOwnerDashboard('chats',{userId:user.id,userLabel:`${user.display_name} (@${user.username})`});});
  content.querySelectorAll('[data-user-manage]').forEach(button=>button.onclick=()=>ownerManageUser(data.items.find(item=>item.id===Number(button.dataset.userManage))));
  ownerPager(content,data.total,data.limit);
}

function ownerManageUser(user){
  const root=document.getElementById('ownerManageAccount');
  if(user.is_owner){root.innerHTML='<p class="helper">Owner accounts are protected. Manage your own sessions from Linked devices.</p>';return;}
  root.innerHTML=`<section class="owner-action-card"><h4>Manage ${ownerEscape(user.display_name)} · @${ownerEscape(user.username)}</h4><p class="helper">Banning stops sign-in and signs out existing sessions. Deleting disables the account in a recoverable state and keeps retained chat history for moderation.</p><form id="ownerActionForm"><div class="field"><label for="ownerAccountAction">Action</label><select id="ownerAccountAction">${user.deleted_at?'<option value="restore">Restore deleted account</option>':`<option value="${user.suspended_at?'unban':'ban'}">${user.suspended_at?'Unban account':'Ban account'}</option><option value="sign-out">Sign out all devices</option><option value="delete">Delete account · recoverable</option>`}</select></div><div class="field"><label for="ownerActionReason">Reason for this action</label><textarea id="ownerActionReason" rows="3" minlength="10" maxlength="500" required placeholder="Describe the abuse, support request or account concern"></textarea></div><div class="field" id="ownerConfirmField" hidden><label for="ownerConfirmUsername">Type ${ownerEscape(user.username)} to confirm</label><input id="ownerConfirmUsername" autocomplete="off"></div><button class="feature-btn owner-danger" id="ownerApplyAction">Apply action</button><p class="helper">This action and your reason will be recorded in the audit log.</p></form></section>`;
  const actionSelect=document.getElementById('ownerAccountAction');
  const update=()=>{const typed=['delete','restore'].includes(actionSelect.value);document.getElementById('ownerConfirmField').hidden=!typed;document.getElementById('ownerConfirmUsername').required=typed;};actionSelect.onchange=update;update();
  document.getElementById('ownerActionForm').onsubmit=async e=>{
    e.preventDefault();const action=actionSelect.value,reason=document.getElementById('ownerActionReason').value.trim();
    if(reason.length<10){ownerError(new Error('Enter a reason with at least 10 characters.'));return;}
    const button=document.getElementById('ownerApplyAction');button.disabled=true;
    try{
      if(action==='ban'||action==='unban')await ownerRequest(`users/${user.id}/suspension`,'POST',{reason,suspended:action==='ban'});
      else if(action==='sign-out')await ownerRequest(`users/${user.id}/sign-out`,'POST',{reason});
      else await ownerRequest(`users/${user.id}/deletion`,'POST',{reason,deleted:action==='delete',username_confirmation:document.getElementById('ownerConfirmUsername').value});
      toast('Account updated. Action recorded.');await loadOwnerSection();
    }catch(error){ownerError(error);button.disabled=false;}
  };
  root.scrollIntoView({block:'nearest',behavior:'smooth'});document.getElementById('ownerActionReason').focus();
}

async function ownerChats(content){
  const data=await ownerRequest(`chats?q=${encodeURIComponent(ownerState.q)}&offset=${ownerState.offset}${ownerState.userId?'&user_id='+ownerState.userId:''}`);if(!content.isConnected)return;
  content.innerHTML=`${ownerState.userId?`<p class="helper">Conversations involving ${ownerEscape(ownerState.userLabel)}.</p>`:''}<form id="ownerChatSearch" class="owner-search"><label><span class="sr-only">Search conversations</span><input id="ownerChatQuery" value="${ownerEscape(ownerState.q)}" placeholder="Search conversation title or participant" maxlength="80"></label><button class="feature-btn">Search</button></form><p class="helper">Opening retained message content requires a reason. Reviews do not mark the messages as read.</p><div class="owner-list">${data.items.map(chat=>`<article class="owner-chat-row"><div><strong>${ownerEscape(chat.title||chat.participants||'Conversation #'+chat.id)}</strong><small>${ownerEscape(chat.type)} · #${chat.id} · ${chat.message_count} retained messages</small>${chat.title?`<small>${ownerEscape(chat.participants||'')}</small>`:''}</div><button type="button" class="feature-btn" data-review-chat="${chat.id}">Review</button></article>`).join('')||'<p class="helper">No matching conversations.</p>'}</div>`;
  document.getElementById('ownerChatSearch').onsubmit=e=>{e.preventDefault();ownerState.q=document.getElementById('ownerChatQuery').value.trim();ownerState.offset=0;loadOwnerSection();};
  content.querySelectorAll('[data-review-chat]').forEach(button=>button.onclick=()=>ownerChatReview(data.items.find(chat=>chat.id===Number(button.dataset.reviewChat))));
  ownerPager(content,data.total,data.limit);
}

function ownerReasonForm(label){
  return `<form class="owner-review-form" id="ownerReviewForm"><div class="field"><label for="ownerReviewReason">Support or moderation reason</label><textarea id="ownerReviewReason" rows="3" required minlength="10" maxlength="500" placeholder="Explain why this content needs to be reviewed"></textarea></div><button class="feature-btn">${label}</button><p class="helper">Each review is recorded with your account, time, reason and content reference.</p></form><div id="ownerReviewResults"></div>`;
}
function ownerChatReview(chat){
  cleanOwnerMedia();const content=document.getElementById('ownerContent');
  content.innerHTML=`<button type="button" class="feature-btn" id="ownerReviewBack">Back to conversations</button><h4>${ownerEscape(chat.title||chat.participants||'Conversation #'+chat.id)}</h4>${ownerReasonForm('Open retained messages')}`;
  document.getElementById('ownerReviewBack').onclick=loadOwnerSection;
  const results=content.querySelector('#ownerReviewResults'),reasonInput=content.querySelector('#ownerReviewReason');
  const read=async before=>{
    const reason=reasonInput.value.trim();if(reason.length<10)throw new Error('Enter a reason with at least 10 characters.');
    const data=await ownerRequest(`chats/${chat.id}/messages`,'POST',{reason,before});
    if(!results.isConnected)return;cleanOwnerMedia();
    results.innerHTML=`<p class="helper">Review logged. Expired content is excluded.</p><div class="owner-message-list">${data.items.map(message=>`<article class="owner-message"><header><strong>${ownerEscape(message.display_name)} <small>@${ownerEscape(message.username)}</small></strong><time>${ownerEscape(ownerDate(message.created_at))}</time></header><p>${message.deleted?'<em>Message deleted</em>':ownerEscape(message.text)}</p>${message.attachment_id?`<button type="button" class="feature-btn" data-media-kind="attachment" data-media-id="${message.attachment_id}">${ownerEscape(message.attachment_name||'Open attachment')}</button><div class="owner-media"></div>`:''}<small>#${message.id}${message.edited_at?' · edited':''}</small></article>`).join('')||'<p class="helper">No retained messages on this page.</p>'}</div>${data.has_more?'<button type="button" class="feature-btn" id="ownerOlderMessages">Load earlier messages</button>':''}`;
    bindOwnerMedia(results,reason);
    document.getElementById('ownerOlderMessages')?.addEventListener('click',()=>read(data.before).catch(ownerError));
  };
  document.getElementById('ownerReviewForm').onsubmit=async e=>{e.preventDefault();const button=e.currentTarget.querySelector('button');button.disabled=true;try{await read(null);}catch(error){ownerError(error);}finally{button.disabled=false;}};
}

function ownerStatusStart(content){
  content.innerHTML=`<h4>Review active statuses</h4><p class="helper">Only statuses that have not reached their expiry time are available.</p>${ownerReasonForm('Review active statuses')}`;
  const results=content.querySelector('#ownerReviewResults'),reasonInput=content.querySelector('#ownerReviewReason');
  const read=async before=>{
    const reason=reasonInput.value.trim();if(reason.length<10)throw new Error('Enter a reason with at least 10 characters.');
    const data=await ownerRequest('statuses/review','POST',{reason,before});
    if(!results.isConnected)return;cleanOwnerMedia();
    results.innerHTML=data.items.map(status=>`<article class="owner-message"><header><strong>${ownerEscape(status.display_name)} <small>@${ownerEscape(status.username)}</small></strong><time>${ownerEscape(ownerDate(status.created_at))}</time></header><p>${ownerEscape(status.text)}</p><small>Audience: ${ownerEscape(status.audience||'profile default')} · Expires ${ownerEscape(ownerDate(status.expires_at))}</small>${status.media_id?`<button type="button" class="feature-btn" data-media-kind="status" data-media-id="${status.media_id}">${ownerEscape(status.media_name||'Open status media')}</button><div class="owner-media"></div>`:''}</article>`).join('')||'<p class="helper">No active statuses on this page.</p>';
    bindOwnerMedia(results,reason);
    if(data.has_more){const button=document.createElement('button');button.className='feature-btn';button.textContent='Load earlier statuses';button.onclick=()=>read(data.before).catch(ownerError);results.appendChild(button);}
  };
  document.getElementById('ownerReviewForm').onsubmit=async e=>{e.preventDefault();const button=e.currentTarget.querySelector('button');button.disabled=true;try{await read(null);}catch(error){ownerError(error);}finally{button.disabled=false;}};
}

function bindOwnerMedia(root,reason){
  root.querySelectorAll('[data-media-kind]').forEach(button=>button.onclick=async()=>{
    button.disabled=true;
    const session=TOKEN,controller=new AbortController(),timer=setTimeout(()=>controller.abort(),25000);
    try{
      const response=await fetch(`/api/admin/media/${button.dataset.mediaKind}/${button.dataset.mediaId}/review`,{method:'POST',cache:'no-store',signal:controller.signal,headers:{Authorization:'Bearer '+session,'Content-Type':'application/json'},body:JSON.stringify({reason})});
      if(!response.ok){const data=await response.json();throw new Error(typeof data.detail==='string'?data.detail:'Media review failed.');}
      const blob=await response.blob();if(TOKEN!==session||!button.isConnected)return;
      const url=URL.createObjectURL(blob);ownerObjectUrls.push(url);
      const container=button.nextElementSibling;container.replaceChildren();
      let element;
      if(['image/jpeg','image/png','image/gif','image/webp'].includes(blob.type)){element=document.createElement('img');element.alt='Reviewed attachment';}
      else if(blob.type.startsWith('audio/')){element=document.createElement('audio');element.controls=true;}
      else if(blob.type.startsWith('video/')){element=document.createElement('video');element.controls=true;element.playsInline=true;}
      else{element=document.createElement('a');element.href=url;element.download=button.textContent;element.textContent='Download reviewed file';}
      if(element.tagName!=='A')element.src=url;container.appendChild(element);
    }catch(error){if(button.isConnected){ownerError(error.name==='AbortError'?new Error('Media took too long to load. Please try again.'):error);button.disabled=false;}}
    finally{clearTimeout(timer);}
  });
}

async function ownerCalls(content){
  const data=await ownerRequest('calls?offset='+ownerState.offset);if(!content.isConnected)return;
  content.innerHTML=`<p class="helper">Call history contains participant, time and outcome records. Calls are not recorded by GOLDCHAT.</p><div class="owner-table-wrap"><table class="owner-table"><thead><tr><th>Participants</th><th>Type</th><th>Outcome</th><th>Started</th><th>Duration</th></tr></thead><tbody>${data.items.map(call=>`<tr><td>@${ownerEscape(call.caller)} → @${ownerEscape(call.callee)}</td><td>${call.video?'Video':'Voice'}</td><td>${ownerEscape(call.status)}</td><td>${ownerEscape(ownerDate(call.created_at))}</td><td>${call.connected_at&&call.ended_at?Math.max(0,Math.floor(call.ended_at-call.connected_at))+' sec':'—'}</td></tr>`).join('')||'<tr><td colspan="5">No calls on this page.</td></tr>'}</tbody></table></div>`;
  ownerPager(content,data.total,data.limit);
}

async function ownerAudit(content){
  const data=await ownerRequest('audit'+(ownerState.before?'?before='+ownerState.before:''));if(!content.isConnected)return;
  content.innerHTML=`<p class="helper">Content reviews and account actions are recorded here. The dashboard cannot edit or delete these records.</p><div class="owner-table-wrap"><table class="owner-table"><thead><tr><th>Time</th><th>Owner</th><th>Action</th><th>Reference</th><th>Reason</th></tr></thead><tbody>${data.items.map(item=>`<tr><td>${ownerEscape(ownerDate(item.created_at))}</td><td>@${ownerEscape(item.actor)}</td><td>${ownerEscape(item.action.replaceAll('_',' '))}</td><td>${ownerEscape(item.target_type)} ${item.target_id||''}</td><td>${ownerEscape(item.reason)}</td></tr>`).join('')||'<tr><td colspan="5">No administrative actions yet.</td></tr>'}</tbody></table></div>${data.has_more?'<button class="feature-btn" id="ownerOlderAudit">Older activity</button>':''}`;
  document.getElementById('ownerOlderAudit')?.addEventListener('click',()=>{ownerState.before=data.before;loadOwnerSection();});
}
