/* Account-scoped appearance; gallery photos stay on this device. */
const bubblePalette=[['Forest','#176b4b'],['Deep forest','#134c39'],['Ocean','#0d548c'],['Navy','#0d315c'],['Violet','#4936a0'],['Indigo','#322e62'],['Azure','#0b547d'],['Midnight blue','#0b3b50'],['Orchid','#74348a'],['Plum','#55275f'],['Graphite','#4a4a4a'],['Charcoal','#33383b'],['Terracotta','#8b422c'],['Cocoa','#59382c'],['Sage','#405839'],['Olive','#303e2c'],['Teal','#086360'],['Deep teal','#0b4544'],['Ruby','#8b1138'],['Burgundy','#59172e'],['Chestnut','#65452d'],['Umber','#423123'],['Sand','#857257'],['Stone','#4a4338'],['Sea green','#0b7a68'],['Pine','#0b5847'],['Mustard','#aa9200'],['Deep gold','#716000'],['Lime','#577f21'],['Moss','#344d17'],['Rose','#b3235a'],['Wine','#64283e'],['Crimson','#a81236'],['Berry','#711d3c'],['Rust','#9c2c12'],['Burnt orange','#6c2009'],['GOLDCHAT gold','#b59837'],['Bronze','#66562e'],['Denim','#385c82'],['Slate','#50616b'],['Grape','#644981'],['Coral','#a44747']];
const wallpaperLibrary=[
  {id:'petals',name:'Peony petals',photo:'petals.png'},
  {id:'silk',name:'Lavender silk',css:'radial-gradient(ellipse at 20% 20%,#ffe8fd,transparent 55%),repeating-conic-gradient(from 30deg at 30% 60%,#bca2e8 0deg,#f0d9ff 38deg,#c7cef3 65deg,#f7c8e3 94deg)'},
  {id:'botanical',name:'Monstera',photo:'botanical.png'},
  {id:'rose',name:'Rose quartz',css:'radial-gradient(ellipse at 80% 10%,#fff1da,transparent 70%),linear-gradient(135deg,#facbbf,#dca9bc 55%,#fbd9ce)'},
  {id:'orchid',name:'Orchid haze',css:'radial-gradient(ellipse at 20% 60%,#d3c7ed,transparent 70%),linear-gradient(130deg,#ece1f4,#b48fc2,#f4d2e7)'},
  {id:'amethyst',name:'Amethyst',css:'repeating-radial-gradient(ellipse at 100% 100%,#52448e 0%,#b19ce0 15%,#7569ad 22%,#c8b5ee 35%)'},
  {id:'sunrise',name:'Amber light',css:'radial-gradient(ellipse at 20% 20%,#ffefb3,transparent 50%),repeating-radial-gradient(ellipse at 90% 20%,#ffc083 0%,#f4a06d 15%,#ffd697 30%)'},
  {id:'gold',name:'Golden hour',css:'radial-gradient(ellipse at 20% 10%,#ffe4a4,transparent 70%),linear-gradient(150deg,#c7843e,#f9c575 50%,#ad5b39)'},
  {id:'peach',name:'Peach ribbons',css:'repeating-linear-gradient(124deg,#ffddb9 0px,#e9b18f 35px,#f9d1b5 80px,#f5c4a5 130px)'},
  {id:'fern',name:'Fern',css:'repeating-radial-gradient(ellipse at 0% 100%,#719966 0%,#3e7657 10%,#a4b579 15%,#4a8265 23%)'},
  {id:'lagoon',name:'Blue lagoon',css:'radial-gradient(ellipse at 90% 10%,#c7eff0,transparent 55%),linear-gradient(145deg,#116f9b,#6fc0d6 40%,#084f77)'},
  {id:'mint',name:'Mint',css:'radial-gradient(circle at 20% 30%,#edfad6,transparent 35%),linear-gradient(140deg,#b2d6ab,#6baf99,#d5e9cb)'},
  {id:'ocean',name:'Atlantic shore',photo:'ocean.png'},
  {id:'glacier',name:'Glacier',css:'repeating-linear-gradient(145deg,#bce4ef 0%,#e9f8ff 12%,#8cbfdb 23%,#d4f0f8 36%)'},
  {id:'blueglass',name:'Blue glass',css:'repeating-conic-gradient(from 12deg at 70% 60%,#68afc9 0deg,#a4e2ea 60deg,#24758e 96deg,#a0c5e2 150deg)'},
  {id:'tennis',name:'Blue court',css:'linear-gradient(35deg,transparent 48.8%,#e3effc 49%,#e3effc 49.5%,transparent 49.7%),linear-gradient(90deg,transparent 65%,#d4e8f8 65.3%,#d4e8f8 66%,transparent 66.3%),linear-gradient(130deg,#77bdde,#2a7cb7)'},
  {id:'football',name:'Green pitch',css:'linear-gradient(90deg,transparent 48.8%,#d9ebce 49%,#d9ebce 50%,transparent 50.2%),repeating-linear-gradient(0deg,#40784c 0px,#40784c 45px,#478752 45px,#478752 90px)'},
  {id:'midnight',name:'Midnight',css:'radial-gradient(ellipse at 10% 20%,#243744,transparent 75%),linear-gradient(145deg,#172328,#0c171c)'},
  {id:'alpine',name:'Alpine dawn',photo:'alpine.png'},
  {id:'dusk',name:'Dusk',css:'linear-gradient(160deg,#e8bdc4,#797fac 50%,#2d4568)'},
  {id:'dunes',name:'Desert dunes',css:'repeating-radial-gradient(ellipse at 20% 120%,#ddaa7e 0%,#cc8b5f 12%,#f4c79c 21%,#b87550 32%)'},
  {id:'ink',name:'Ink folds',css:'repeating-radial-gradient(ellipse at 0% 70%,#0d1418 0%,#253338 12%,#141c21 20%,#536269 33%)'},
  {id:'stone',name:'Silver dunes',css:'repeating-radial-gradient(ellipse at 0% 20%,#939b9e 0%,#465358 10%,#b1b8b9 22%,#747c80 32%)'},
  {id:'seafoam',name:'Seafoam',css:'radial-gradient(ellipse at 20% 90%,#e4faf3,transparent 60%),linear-gradient(145deg,#a6d4cc,#306c68)'},
  {id:'clay',name:'Clay',css:'radial-gradient(ellipse at 90% 10%,#f8c2ac,transparent 60%),linear-gradient(140deg,#b67e76,#e3b3a1,#bd8580)'},
  {id:'paper',name:'Warm paper',css:'linear-gradient(135deg,#e8dac1,#d5bf9c)'},
  {id:'aurora',name:'Aurora',css:'radial-gradient(ellipse at 10% 90%,#759fbd,transparent 50%),conic-gradient(from 45deg at 30% 40%,#142d45,#226a66,#7e91b1,#2b574e,#142d45)'},
];
function appearanceKey(){return 'gc_appearance_'+(ME?.id||'device');}
function appearancePreferences(){try{return {wallpaper:'midnight',bubble:'#8b422c',dim:25,...JSON.parse(localStorage.getItem(appearanceKey())||'{}')};}catch{return {wallpaper:'midnight',bubble:'#8b422c',dim:25};}}
function saveAppearance(patch){localStorage.setItem(appearanceKey(),JSON.stringify({...appearancePreferences(),...patch}));applySettings();}
function wallpaperStyle(id){const item=wallpaperLibrary.find(x=>x.id===id);if(item)return item.photo?`url('/static/wallpapers/${item.photo}')`:item.css;if(/^#[0-9a-f]{6}$/i.test(id))return `linear-gradient(${id},${id})`;return wallpaperLibrary.find(x=>x.id==='midnight').css;}
let galleryObjectURL=null,appearanceGeneration=0;
function galleryDB(){return new Promise((resolve,reject)=>{const req=indexedDB.open('goldchat-appearance',1);req.onupgradeneeded=()=>req.result.createObjectStore('photos');req.onsuccess=()=>resolve(req.result);req.onerror=()=>reject(new Error('Gallery storage is unavailable on this device'));});}
async function galleryPhoto(blob=undefined){const db=await galleryDB();try{return await new Promise((resolve,reject)=>{const tx=db.transaction('photos',blob===undefined?'readonly':'readwrite'),store=tx.objectStore('photos'),req=blob===undefined?store.get(ME.id):store.put(blob,ME.id);req.onsuccess=()=>{const result=req.result;tx.oncomplete=()=>resolve(result);};req.onerror=()=>reject(req.error);tx.onabort=()=>reject(new Error('Could not save the gallery wallpaper'));});}finally{db.close();}}
function bubbleForeground(color){const rgb=color.match(/[a-f\d]{2}/gi).map(n=>parseInt(n,16));return rgb[0]*.299+rgb[1]*.587+rgb[2]*.114>155?'#182020':'#fff';}
function clearAppearance(){appearanceGeneration++;if(galleryObjectURL)URL.revokeObjectURL(galleryObjectURL);galleryObjectURL=null;document.getElementById('messages').style.backgroundImage='';document.documentElement.style.removeProperty('--sent-bubble');document.documentElement.style.removeProperty('--sent-text');}
const applyBaseSettings=applySettings;
applySettings=function(){
  applyBaseSettings();document.body.classList.toggle('high-contrast',localStorage.getItem('gc_high_contrast')==='on');
  const prefs=appearancePreferences(),generation=++appearanceGeneration;
  const color=/^#[0-9a-f]{6}$/i.test(prefs.bubble)?prefs.bubble:'#8b422c';
  document.documentElement.style.setProperty('--sent-bubble',color);document.documentElement.style.setProperty('--sent-text',bubbleForeground(color));
  const dim=Math.max(0,Math.min(80,Number(prefs.dim)||0))/100,shade=`linear-gradient(rgba(0,0,0,${dim}),rgba(0,0,0,${dim}))`;
  const messages=document.getElementById('messages');messages.style.backgroundImage=shade+','+wallpaperStyle(prefs.wallpaper);
  if(galleryObjectURL){URL.revokeObjectURL(galleryObjectURL);galleryObjectURL=null;}
  if(prefs.wallpaper==='gallery'&&ME)galleryPhoto().then(blob=>{if(generation!==appearanceGeneration||!blob)return;galleryObjectURL=URL.createObjectURL(blob);messages.style.backgroundImage=shade+`,url('${galleryObjectURL}')`;}).catch(()=>{});
};
function themeSample(background=wallpaperStyle(appearancePreferences().wallpaper),bubble=appearancePreferences().bubble){return `<div class="theme-conversation" style="background-image:${escapeHtml(background)}"><span class="sample-date">Today</span><div class="sample-recv">A little more you.<small>10:24</small></div><div class="sample-sent" style="background:${bubble};color:${bubbleForeground(bubble)}">Make yourself at home ✨<small>10:25 <span>✓✓</span></small></div><div class="sample-recv">Your chats, your style.<small>10:25</small></div></div>`;}
showChatThemes=function(){
  workspacePanel('Chat theme',`<p class="helper">Personalize the look of your conversations. These choices are for you, on this device.</p>${themeSample()}<div class="settings-list">${menuAction('themeBubble','Chat bubble','chats','Choose a color')}${menuAction('themeWallpaper','Wallpaper','theme','Gallery, colors and original wallpapers')}${menuAction('themeReset','Reset chat theme','undo','Use GOLDCHAT defaults')}</div>`,'More',showAppearanceSettings);
  bind('themeBubble',showBubbleColors);bind('themeWallpaper',showWallpapers);bind('themeReset',()=>{saveAppearance({wallpaper:'midnight',bubble:'#8b422c',dim:25});showChatThemes();});
};
showAppearanceSettings=function(){
  workspacePanel('Appearance',`${themeSample()}<div class="settings-list">${menuAction('appearanceThemes','Chat theme','theme','Wallpapers and chat bubble colors')}</div><div class="field"><label for="appTheme">App theme</label><select id="appTheme"><option value="dark">Dark</option><option value="light">Light</option><option value="system">Use device setting</option></select></div><div class="field"><label for="appearanceTextSize">Message text size</label><input id="appearanceTextSize" type="range" min="14" max="22"><output id="appearanceTextOutput"></output></div><div class="field"><label for="appearanceTime">Time format</label><select id="appearanceTime"><option value="12">12 hour</option><option value="24">24 hour</option></select></div>${action('saveAppAppearance','Save preferences')}`,'More',showSettings);
  document.getElementById('appTheme').value=localStorage.getItem('gc_theme')||'dark';document.getElementById('appearanceTime').value=localStorage.getItem('gc_time_format')||'12';const size=document.getElementById('appearanceTextSize');size.value=localStorage.getItem('gc_text_size')||16;size.oninput=()=>document.getElementById('appearanceTextOutput').textContent=size.value+' px';size.oninput();bind('appearanceThemes',showChatThemes);
  bind('saveAppAppearance',()=>{localStorage.setItem('gc_theme',document.getElementById('appTheme').value);localStorage.setItem('gc_time_format',document.getElementById('appearanceTime').value);localStorage.setItem('gc_text_size',size.value);applySettings();renderChatList();if(activeChatId)refreshMessages();showSettings();toast('Appearance saved');});
};
function showBubbleColors(){
  const current=appearancePreferences().bubble;
  workspacePanel('Chat bubble',`<p class="helper">Choose the color of messages you send.</p><div class="bubble-palette">${bubblePalette.map(([name,color])=>`<button type="button" class="bubble-swatch ${color===current?'selected':''}" style="--swatch:${color}" data-color="${color}" aria-label="${name}" aria-pressed="${color===current}"><span>${uiIcon('check')}</span></button>`).join('')}</div><div class="custom-color"><label for="customBubbleColor">Custom color</label><input type="color" id="customBubbleColor" value="${current}"></div><div class="bubble-live-preview" id="bubblePreview">${themeSample()}</div>`,'More',showChatThemes);
  const choose=color=>{saveAppearance({bubble:color});document.querySelectorAll('.bubble-swatch').forEach(b=>{b.classList.toggle('selected',b.dataset.color===color);b.setAttribute('aria-pressed',String(b.dataset.color===color));});document.getElementById('customBubbleColor').value=color;document.getElementById('bubblePreview').innerHTML=themeSample();};
  document.querySelectorAll('.bubble-swatch').forEach(b=>b.onclick=()=>choose(b.dataset.color));document.getElementById('customBubbleColor').oninput=e=>choose(e.target.value);
}
function showWallpapers(){
  const current=appearancePreferences().wallpaper;
  workspacePanel('Wallpaper',`<div class="settings-list wallpaper-actions">${menuAction('wallpaperGallery','Choose from gallery','document')}${menuAction('wallpaperColor','Set a color','theme')}</div><div class="wallpaper-grid">${wallpaperLibrary.map(item=>`<button type="button" class="wallpaper-card ${current===item.id?'selected':''}" data-wallpaper-id="${item.id}" aria-label="Preview ${item.name}" style="${item.photo?'':'background-image:'+item.css}">${item.photo?`<img src="/static/wallpapers/${item.photo}" alt="" loading="lazy" decoding="async">`:''}<span class="wallpaper-name">${item.name}</span>${current===item.id?'<span class="wallpaper-check">'+uiIcon('check')+'</span>':''}</button>`).join('')}</div><p class="helper">Original GOLDCHAT wallpapers. Gallery photos stay on this device.</p>`,'More',showChatThemes);
  document.querySelectorAll('.wallpaper-card').forEach(b=>b.onclick=()=>previewWallpaper(b.dataset.wallpaperId));
  bind('wallpaperGallery',()=>{const picker=document.createElement('input');picker.type='file';picker.accept='image/png,image/jpeg,image/webp';picker.onchange=runUI(async()=>{const file=picker.files[0];if(!file)return;if(file.size>10*1024*1024)throw new Error('Choose a wallpaper under 10 MB');const bitmap=await createImageBitmap(file);if(bitmap.width*bitmap.height>40000000){bitmap.close();throw new Error('Choose a smaller image');}bitmap.close();await galleryPhoto(file);previewWallpaper('gallery');});picker.click();});
  bind('wallpaperColor',()=>{workspacePanel('Wallpaper color',`<div class="wallpaper-color-grid">${['#0c171c','#182b32','#223b33','#243849','#4e2e3b','#583622','#636046','#816a80','#b98f81','#decebd','#a9c7cf','#c9d4ba'].map(c=>`<button type="button" style="background:${c}" data-wallpaper-color="${c}" aria-label="Preview color ${c}"></button>`).join('')}</div><div class="custom-color"><label for="customWallpaperColor">Custom color</label><input type="color" id="customWallpaperColor" value="#182b32"></div>${action('previewWallpaperColor','Preview color')}`,'More',showWallpapers);document.querySelectorAll('[data-wallpaper-color]').forEach(b=>b.onclick=()=>previewWallpaper(b.dataset.wallpaperColor));bind('previewWallpaperColor',()=>previewWallpaper(document.getElementById('customWallpaperColor').value));});
}
async function previewWallpaper(id){
  let style=wallpaperStyle(id),url=null;if(id==='gallery'){const blob=await galleryPhoto();if(!blob)throw new Error('Choose a gallery photo first');url=URL.createObjectURL(blob);style=`url('${url}')`;}
  const page=workspacePanel('Wallpaper preview',`${themeSample(style)}<div class="field"><label for="wallpaperDim">Wallpaper brightness</label><input id="wallpaperDim" type="range" min="0" max="80" value="${80-appearancePreferences().dim}"><output id="wallpaperBrightness"></output></div>${action('applyWallpaper','Set wallpaper')}`,'More',showWallpapers);page.classList.add('wallpaper-preview-page');
  if(url)socialCleanup=()=>URL.revokeObjectURL(url);
  const dim=document.getElementById('wallpaperDim'),sample=page.querySelector('.theme-conversation');dim.oninput=()=>{sample.style.boxShadow=`inset 0 0 0 1000px rgba(0,0,0,${(80-Number(dim.value))/100})`;document.getElementById('wallpaperBrightness').textContent=Math.round(Number(dim.value)/80*100)+'%';};dim.oninput();
  bind('applyWallpaper',()=>{saveAppearance({wallpaper:id,dim:80-Number(dim.value)});showWallpapers();toast('Wallpaper updated');});
}
applySettings();
