/* Verified account registration and recovery. No codes or proof tokens go in URLs. */
const passwordInput=document.getElementById('password');
passwordInput.parentElement.classList.add('password-field');
const passwordToggle=document.createElement('button');
passwordToggle.type='button';passwordToggle.className='password-toggle';
passwordToggle.textContent='Show';passwordToggle.setAttribute('aria-label','Show password');passwordToggle.setAttribute('aria-controls','password');passwordToggle.setAttribute('aria-pressed','false');
passwordToggle.onclick=()=>{const show=passwordInput.type==='password';passwordInput.type=show?'text':'password';passwordToggle.textContent=show?'Hide':'Show';passwordToggle.setAttribute('aria-label',show?'Hide password':'Show password');passwordToggle.setAttribute('aria-pressed',String(show));};
passwordInput.after(passwordToggle);
let authChallenge=null,authCodeSending=false;
let savedAuthChallenges={};try{savedAuthChallenges=JSON.parse(sessionStorage.getItem("gc_verification_requests")||"{}");}catch(e){sessionStorage.removeItem("gc_verification_requests");}
function rememberAuthChallenge(value){authChallenge=value;if(value){savedAuthChallenges[value.purpose]={...value,expiresAt:Date.now()+value.expires_in*1000};sessionStorage.setItem("gc_verification_requests",JSON.stringify(savedAuthChallenges));}}
const contactFields=document.createElement('div');contactFields.id='verifiedContactFields';
contactFields.innerHTML='<div class="field" hidden><label for="verificationChannel">Verify using</label><select id="verificationChannel"><option value="email">Email</option></select></div><div class="field"><label id="verificationAddressLabel" for="verificationAddress">Email address</label><input id="verificationAddress" type="email" autocomplete="email" maxlength="254"></div><button id="sendVerificationCode" class="feature-btn" type="button">Send verification code</button><div class="field"><label for="verificationCode">Verification code</label><input id="verificationCode" inputmode="numeric" autocomplete="one-time-code" maxlength="12" placeholder="6-digit code"></div><p class="helper" id="verificationHelp">Verify your email before creating an account.</p>';
authForm.insertBefore(contactFields,authBtn);
const forgotPassword=document.createElement('button');forgotPassword.type='button';forgotPassword.className='feature-btn';forgotPassword.textContent='Forgot password?';authForm.after(forgotPassword);
forgotPassword.onclick=()=>setMode('reset');
const baseSetMode=setMode;
setMode=function(next){
  passwordInput.type='password';passwordToggle.textContent='Show';passwordToggle.setAttribute('aria-label','Show password');passwordToggle.setAttribute('aria-pressed','false');
  baseSetMode(next);authChallenge=null;document.getElementById('verificationCode').value='';
  const reset=next==='reset',contact=next!=='login';
  contactFields.hidden=!contact;forgotPassword.hidden=contact;
  contactFields.querySelectorAll('input,select,button').forEach(control=>control.disabled=!contact);
  document.getElementById('username').closest('.field').hidden=reset;document.getElementById('username').required=!reset;
  document.getElementById('username').closest('.field').querySelector('label').textContent=next==='register'?'Username':'Username or verified email';
  document.getElementById('username').placeholder=next==='register'?'Choose a username':'Username or email';
  document.getElementById('password').closest('.field').querySelector('label').textContent=reset?'New password':'Password';
  document.getElementById('password').autocomplete=next==='login'?'current-password':'new-password';
  document.getElementById('verificationAddress').required=contact;
  document.getElementById('verificationCode').required=false;
  authBtn.textContent=reset?'Reset password':next==='register'?'Verify & create account':'Sign In';
  if(reset){authSub.textContent='Reset your password using a verified email';switchText.textContent='Remember your password?';switchBtn.textContent='Sign in';}
  const saved=savedAuthChallenges[reset?'reset':'register'];
  if(contact && saved?.expiresAt>Date.now()){authChallenge={...saved};document.getElementById('verificationAddress').value=saved.address;}
  document.getElementById('verificationHelp').textContent=reset?'Use the email previously verified on your account.':'A code is required before your account is created.';
};
switchBtn.addEventListener('click',e=>{if(mode==='reset'){e.stopImmediatePropagation();setMode('login');}},true);
function resetAuthChallenge(){authChallenge=null;document.getElementById('verificationCode').value='';}
document.getElementById('verificationAddress').oninput=resetAuthChallenge;
document.getElementById('verificationChannel').onchange=()=>{
  resetAuthChallenge();const phone=document.getElementById('verificationChannel').value==='phone',input=document.getElementById('verificationAddress');
  input.type=phone?'tel':'email';input.autocomplete=phone?'tel':'email';input.value='';input.placeholder=phone?'+234…':'you@example.com';
  document.getElementById('verificationAddressLabel').textContent=phone?'International phone number':'Email address';
};
async function authRequest(path,body){
  const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),90000);
  try {
    const health=await fetch('/healthz',{signal:controller.signal,cache:'no-store'});
    if(!health.ok)throw new Error('GOLDCHAT is starting or temporarily unavailable. Wait a minute and try again.');
    const response=await fetch(path,{method:'POST',signal:controller.signal,headers:{'Content-Type':'application/json',...(TOKEN?{Authorization:'Bearer '+TOKEN}:{})},body:JSON.stringify(body)});
    const text=await response.text();let data;
    try{data=JSON.parse(text);}catch(e){throw new Error('The server could not complete your request. Wait a minute and try again.');}
    if(!response.ok){const error=new Error(typeof data.detail==='string'?data.detail:'Please check your details.');error.data=data;throw error;}return data;
  } catch(e) {
    if(e.name==='AbortError'||e instanceof TypeError)throw new Error('Could not reach GOLDCHAT. Check your connection and try again in a minute.');
    throw e;
  } finally {clearTimeout(timer);}
}
function authError(error){authErr.textContent=error.message;authErr.classList.add('show');}
async function sendAuthCode(){
  if(authCodeSending)return;
  const input=document.getElementById('verificationAddress');if(!input.reportValidity())return;
  const channel=document.getElementById('verificationChannel').value,address=input.value.trim(),purpose=mode==='reset'?'reset':'register',button=document.getElementById('sendVerificationCode');
  authCodeSending=true;button.disabled=true;authBtn.disabled=true;authErr.classList.remove('show');
  try{
    const result=await authRequest('/api/auth/verification/start',{channel,address,purpose});
    if(input.value.trim()!==address||document.getElementById('verificationChannel').value!==channel||(mode==='reset'?'reset':mode==='register'?'register':'')!==purpose)return;
    rememberAuthChallenge({...result,channel,address,purpose});const confirmation=document.getElementById('verificationHelp');confirmation.setAttribute('role','status');confirmation.setAttribute('aria-live','polite');confirmation.style.cssText='padding:12px;border:1px solid #d4af37;border-radius:10px;color:#f5df93;background:#221d0c;';confirmation.textContent=result.message+' You have '+Math.ceil(result.expires_in/60)+' minutes to enter it.';toast(purpose==='reset'?'Verification requested. Check your email.':result.message);
    document.getElementById('verificationCode').focus();
  }catch(e){if(e.data?.challenge_id){rememberAuthChallenge({...e.data,channel,address,purpose});document.getElementById('verificationCode').focus();}authError(e);}finally{authCodeSending=false;button.disabled=false;authBtn.disabled=false;}
}
document.getElementById('sendVerificationCode').onclick=sendAuthCode;
authForm.addEventListener('submit',async e=>{
  if(mode==='login')return;e.preventDefault();e.stopImmediatePropagation();
  if(!authChallenge){await sendAuthCode();return;}
  authBtn.disabled=true;authErr.classList.remove('show');
  try{
    const code=document.getElementById('verificationCode').value.replace(/\s+/g,'');if(!/^\d{6}$/.test(code))throw new Error('Enter the 6-digit code sent to your email');
    if(mode==='reset'){
      await authRequest('/api/auth/password/reset',{challenge_id:authChallenge.challenge_id,code,password:document.getElementById('password').value});
      delete savedAuthChallenges.reset;sessionStorage.setItem('gc_verification_requests',JSON.stringify(savedAuthChallenges));document.getElementById('password').value='';setMode('login');toast('Password reset. Sign in with your new password.');return;
    }
    if(!authChallenge.verification_proof){const verified=await authRequest('/api/auth/verification/confirm',{challenge_id:authChallenge.challenge_id,code});authChallenge.verification_proof=verified.verification_proof;}
    const result=await authRequest('/api/register',{username:document.getElementById('username').value.trim(),display_name:document.getElementById('displayName').value.trim(),password:document.getElementById('password').value,verification_proof:authChallenge.verification_proof});
    delete savedAuthChallenges.register;sessionStorage.setItem('gc_verification_requests',JSON.stringify(savedAuthChallenges));TOKEN=result.token;ME=result.user;localStorage.setItem('gc_token',TOKEN);localStorage.setItem('gc_me',JSON.stringify(ME));await enterApp();
  }catch(e){authError(e);}finally{authBtn.disabled=false;authBtn.textContent=mode==='reset'?'Reset password':mode==='register'?'Verify & create account':'Sign In';}
},true);
setMode(mode);
document.querySelector('.auth-hint').textContent='New accounts require a code sent to your email. Existing accounts can sign in normally.';

async function showUserProfile(id){
  try{
    const user=await request('/api/users/'+id+'/profile');
    panel('User profile',`<div class="profile-photo">${avatarContent(user)}</div><h3>${escapeHtml(user.display_name)}</h3><p>@${escapeHtml(user.username)}</p>${user.verified?'<p class="verified-label">Email verified</p>':''}<p>${escapeHtml(user.bio||'No bio yet.')}</p>${id!==ME.id?action('profileMessage','Message')+action('profileAddContact','Add contact'):''}`);
    bind('profileMessage',async()=>{const chat=await request('/api/chats/direct/'+id,'POST');closePanel();await loadChats();await openChat(chat.chat_id);});
    bind('profileAddContact',async()=>{await request('/api/contacts/'+id,'POST');toast('Contact added');});
  }catch(e){toast(e.message);}
}
for(const id of ['hAvatar','hName']){
  const element=document.getElementById(id);element.classList.add('profile-link');element.tabIndex=0;element.setAttribute('role','button');element.setAttribute('aria-label','View profile');
  const open=()=>{const chat=chats.find(c=>c.id===activeChatId);if(chat?.type==='direct'&&chat.peer)showUserProfile(chat.peer.id);else if(chat)showMembers();};
  element.onclick=open;element.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();open();}};
}
async function showRecoveryContact(){
  const contacts=await request('/api/auth/contact');
  panel('Account verification',`<p class="helper">Verify a contact so you can recover a forgotten password. Your email is private.</p><p>${contacts.email?'Email: '+escapeHtml(contacts.email):'No verified email'}</p><div class="field" hidden><label for="linkChannel">Verify using</label><select id="linkChannel"><option value="email">Email</option></select></div>${field('linkAddress','Email address')}${action('sendLinkCode','Send code')}${field('linkCode','Verification code')}${action('confirmLinkCode','Verify contact')}<div id="linkGoogle" class="google-link" hidden><p class="helper">Connect your Google account for quicker sign-in.</p><div id="linkGoogleButton"></div></div>`);
  if(window.goldchatRenderGoogleButton){document.getElementById('linkGoogle').hidden=false;window.goldchatRenderGoogleButton(document.getElementById('linkGoogleButton'));}
  let challenge=null;const invalidate=()=>challenge=null;document.getElementById('linkAddress').oninput=invalidate;document.getElementById('linkChannel').onchange=invalidate;
  bind('sendLinkCode',async()=>{const address=document.getElementById('linkAddress').value,channel=document.getElementById('linkChannel').value;try{challenge=await authRequest('/api/auth/verification/start',{channel,address,purpose:'link'});toast(challenge.message);}catch(e){if(e.data?.challenge_id)challenge=e.data;throw e;}});
  bind('confirmLinkCode',async()=>{if(!challenge)throw new Error('Request a code first');await request('/api/auth/contact/confirm','POST',{challenge_id:challenge.challenge_id,code:document.getElementById('linkCode').value.trim()});await syncOwnProfile();await showRecoveryContact();toast('Contact verified');});
}
const profileWithVerification=showProfile;
showProfile=async function(){await profileWithVerification();const button=document.createElement('button');button.className='feature-btn';button.textContent='Verify email for password recovery';button.onclick=()=>showRecoveryContact().catch(e=>toast(e.message));document.querySelector('.profile-photo-controls').after(button);};
