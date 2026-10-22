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
        const linking=appEl.style.display==='flex',session=TOKEN;
        const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),20000);
        authErr.classList.remove('show');
        holder.classList.add('busy');
        document.getElementById('linkGoogle')?.classList.add('busy');
        try{
          const response=await fetch('/api/auth/google',{
            method:'POST',signal:controller.signal,
            headers:{'Content-Type':'application/json',...(linking?{'Authorization':'Bearer '+session}:{})},
            body:JSON.stringify({credential:result.credential,link:linking})
          });
          const data=await response.json();
          if(!response.ok)throw new Error(data.detail||'Google sign-in failed');
          if(linking && TOKEN!==session)return;
          TOKEN=data.token;ME=data.user;
          localStorage.setItem('gc_token',TOKEN);
          localStorage.setItem('gc_me',JSON.stringify(ME));
          if(linking){
            closePanel();
            toast('Google account connected');
          }else{
            await enterApp();
          }
        }catch(error){
          const message=error.name==='AbortError'?'Google sign-in took too long. Please try again.':error.message;
          if(linking){const errorBox=document.getElementById('panelError');if(errorBox)errorBox.textContent=message;else toast(message);}
          else{authErr.textContent=message;authErr.classList.add('show');}
        }
        finally{clearTimeout(timer);holder.classList.remove('busy');document.getElementById('linkGoogle')?.classList.remove('busy');}
      }});
      holder.hidden=false;divider.hidden=false;
      window.goldchatRenderGoogleButton=element=>google.accounts.id.renderButton(element,{theme:'outline',size:'large',shape:'pill',text:'continue_with',width:Math.min(320,element.clientWidth||320)});
      window.goldchatRenderGoogleButton(holder);
    };
    document.head.appendChild(script);
  }catch(error){/* Email and password sign-in remain available. */}
})();
