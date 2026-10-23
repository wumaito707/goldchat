/* Update announcements are separate from message, status and call alerts. */
let activeUpdateAnnouncement=null,updateAnnouncementClock=null;
let updateAnnouncementExpiryTimer=null,updateAnnouncementPollTimer=null,updateAnnouncementSequence=0;

function updateAnnouncementNow(){
  return updateAnnouncementClock
    ?updateAnnouncementClock.server+(performance.now()-updateAnnouncementClock.local)/1000
    :Date.now()/1000;
}

function clearUpdateAnnouncement(){
  updateAnnouncementSequence++;
  clearTimeout(updateAnnouncementExpiryTimer);clearTimeout(updateAnnouncementPollTimer);
  activeUpdateAnnouncement=null;updateAnnouncementClock=null;
  document.getElementById('updateAnnouncement')?.remove();
}

function renderUpdateAnnouncement(){
  clearTimeout(updateAnnouncementExpiryTimer);
  const item=activeUpdateAnnouncement;
  if(!TOKEN||!ME||!item||!Number.isFinite(item.expires_at)||item.expires_at<=updateAnnouncementNow()){
    activeUpdateAnnouncement=null;document.getElementById('updateAnnouncement')?.remove();return;
  }
  let card=document.getElementById('updateAnnouncement');
  if(!card){
    const search=document.querySelector('.search-wrap');if(!search)return;
    card=document.createElement('aside');card.id='updateAnnouncement';card.className='update-announcement';
    card.setAttribute('aria-label','GOLDCHAT update');card.setAttribute('role','status');search.before(card);
  }
  const title=document.createElement('strong'),body=document.createElement('p'),expiry=document.createElement('small');
  title.textContent=item.title;body.textContent=item.body;
  expiry.textContent='Update announcement · ends '+new Date(item.expires_at*1000).toLocaleTimeString([],{hour:'numeric',minute:'2-digit'});
  card.replaceChildren(title,body,expiry);
  updateAnnouncementExpiryTimer=setTimeout(renderUpdateAnnouncement,Math.max(1,Math.ceil((item.expires_at-updateAnnouncementNow())*1000)));
}

async function refreshUpdateAnnouncement(){
  if(!TOKEN||!ME){clearUpdateAnnouncement();return;}
  const session=TOKEN,sequence=++updateAnnouncementSequence,controller=new AbortController();
  const timeout=setTimeout(()=>controller.abort(),15000);
  clearTimeout(updateAnnouncementPollTimer);
  try{
    const response=await fetch('/api/announcements',{cache:'no-store',signal:controller.signal,headers:{Authorization:'Bearer '+session}});
    if(!response.ok)throw new Error('Update announcements are unavailable');
    const data=await response.json();
    if(TOKEN!==session||sequence!==updateAnnouncementSequence)return;
    if(!Number.isFinite(data.server_time))throw new Error('Invalid announcement time');
    updateAnnouncementClock={server:data.server_time,local:performance.now()};
    activeUpdateAnnouncement=data.announcement;renderUpdateAnnouncement();
  }catch(error){
    if(TOKEN===session&&sequence===updateAnnouncementSequence)renderUpdateAnnouncement();
  }finally{
    clearTimeout(timeout);
    if(TOKEN===session&&sequence===updateAnnouncementSequence)
      updateAnnouncementPollTimer=setTimeout(refreshUpdateAnnouncement,300000);
  }
}

document.addEventListener('visibilitychange',()=>{
  if(!document.hidden){renderUpdateAnnouncement();if(TOKEN&&ME)refreshUpdateAnnouncement();}
});
