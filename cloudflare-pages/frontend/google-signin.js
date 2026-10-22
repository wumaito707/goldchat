/* Google Identity Services is loaded only when a web client ID is configured. */
(async function initGoogleSignIn(){
  const holder=document.getElementById('googleSignIn');
  const divider=document.getElementById('authDivider');
  try{
    const response=await fetch('/api/auth/google/config',{cache:'no-store'});
    if(!response.ok)return;
    const {client_id:clientId}=await response.json();
    if(!clientId)return;
    const script=document.createElement('script');
    script.src='https://accounts.google.com/gsi/client';
    script.async=true;
    script.onload=()=>{
      if(!window.google?.accounts?.id)return;
      google.accounts.id.initialize({client_id:clientId,callback:async result=>{
        if(!result.credential)return;
        authErr.classList.remove('show');
        holder.classList.add('busy');
        try{
          const response=await fetch('/api/auth/google',{
            method:'POST',headers:{'Content-Type':'application/json',...(TOKEN?{'Authorization':'Bearer '+TOKEN}:{})},
            body:JSON.stringify({credential:result.credential})
          });
          const data=await response.json();
          if(!response.ok)throw new Error(data.detail||'Google sign-in failed');
          TOKEN=data.token;ME=data.user;
          localStorage.setItem('gc_token',TOKEN);
          localStorage.setItem('gc_me',JSON.stringify(ME));
          if(appEl.style.display==='flex'){
            closePanel();
            toast('Google account connected');
          }else{
            await enterApp();
          }
        }catch(error){authErr.textContent=error.message;authErr.classList.add('show');}
        finally{holder.classList.remove('busy');}
      }});
      holder.hidden=false;divider.hidden=false;
      window.goldchatRenderGoogleButton=element=>google.accounts.id.renderButton(element,{theme:'outline',size:'large',shape:'pill',text:'continue_with',width:Math.min(320,element.clientWidth||320)});
      window.goldchatRenderGoogleButton(holder);
    };
    document.head.appendChild(script);
  }catch(error){/* Email and password sign-in remain available. */}
})();
