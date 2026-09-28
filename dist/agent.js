const $ = selector => document.querySelector(selector);
const dialog = $('#agent-dialog');
const launcher = $('#agent-launcher');
const conversation = [];
let busy = false;
let config;
let previousFocus;
async function api(path, body) {
  const response = await fetch(path, {method: body ? 'POST' : 'GET', headers: body ? {'Content-Type':'application/json'} : {}, body: body ? JSON.stringify(body) : undefined});
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || 'The local service could not complete this request.');
  return result;
}
function status(text) { $('#agent-status').textContent = text; }
async function refreshConnection() {
  try {
    config = await api('/api/status');
    status(config.ai_ready ? 'JARVIS · Ready to talk' : config.wrapper_connected ? 'JARVIS connected · model offline' : 'JARVIS connection pending');
    $('#provider-notice').textContent = 'Your message and recent chat context are processed by JARVIS’s connected local model. Conversation context stays in this page until you refresh or start a new conversation.';
  } catch { status('Local service unavailable. Open this demo through its local server.'); }
}
function openChat() {
  previousFocus = document.activeElement;
  if (!dialog.open) dialog.showModal();
  launcher.setAttribute('aria-expanded','true');
  $('#agent-message').focus();
  refreshConnection();
}
document.querySelectorAll('[data-open-agent]').forEach(button => button.addEventListener('click',openChat));
$('#agent-close').addEventListener('click',()=>dialog.close());
dialog.addEventListener('close',()=>{launcher.setAttribute('aria-expanded','false');previousFocus?.focus();});
function message(role,text) {
  const item = document.createElement('div'); item.className=`chat-message ${role}`;
  const label=document.createElement('strong'); label.textContent=role==='user'?'You':role==='assistant'?'JARVIS':'Connection notice';
  const content=document.createElement('p');content.textContent=text;
  item.append(label,content);$('#chat-log').append(item);item.scrollIntoView({block:'nearest'});
}
$('#chat-form').addEventListener('submit',async event=>{
  event.preventDefault(); if(busy)return;
  if(!$('#ai-consent').checked){$('#chat-feedback').textContent='Please confirm the processing notice before sending.';return;}
  const input=$('#agent-message'); const text=input.value.trim();if(!text)return;
  busy=true;$('#agent-send').disabled=true;$('#chat-feedback').textContent='Connecting to the AI agent…';
  message('user',text); input.value='';
  try {
    const recent=conversation.slice(-10);while(recent.reduce((n,m)=>n+m.content.length,0)>12000)recent.shift();
    const result=await api('/api/command',{message:text,history:recent,audience:$('#chat-audience').value,ai_consent:true,share_text:$('#share-chat').checked});
    if(result.outcome==='responded'){
      message('assistant',result.answer);conversation.push({role:'user',content:text},{role:'assistant',content:result.answer.slice(0,4000)});
      $('#chat-feedback').textContent='AI response. Review important details; no external actions were taken.';
    } else {message('notice',result.message);$('#chat-feedback').textContent='No AI response was generated. You can leave an enquiry below.';}
  } catch(error){message('notice',error.message);$('#chat-feedback').textContent='Your request did not complete. You can retry or leave an enquiry.';}
  finally{busy=false;$('#agent-send').disabled=false;input.focus();}
});
$('#new-chat').addEventListener('click',()=>{
  if(busy)return;conversation.length=0;$('#chat-log').replaceChildren();$('#chat-feedback').textContent='New conversation. Previously shared records remain in the owner inbox until deleted or expired.';
});
$('#show-enquiry').addEventListener('click',()=>{
  $('#enquiry-form').hidden=!$('#enquiry-form').hidden;
  $('#show-enquiry').setAttribute('aria-expanded',String(!$('#enquiry-form').hidden));
  if(!$('#enquiry-form').hidden)$('#enquiry-message').focus();
});
$('#enquiry-form').addEventListener('submit',async event=>{
  event.preventDefault();const form=event.currentTarget;const button=form.querySelector('button[type=submit]');button.disabled=true;
  $('#enquiry-feedback').textContent='Saving…';
  try{
    const data=Object.fromEntries(new FormData(form));data.contact_consent=form.elements.contact_consent.checked;
    const result=await api('/api/enquiry',data);$('#enquiry-feedback').textContent=result.message+' Reference: '+result.id.slice(0,8);form.reset();
  }catch(error){$('#enquiry-feedback').textContent=error.message;}finally{button.disabled=false;}
});

// Analytics are opt-in. A random tab session is not a person or a fingerprint.
let analytics = false;
let session;
let pageRecorded=false;
try{
  analytics=localStorage.getItem('jarvis_analytics')==='yes';
  let saved=JSON.parse(sessionStorage.getItem('jarvis_visit')||'null');
  if(!saved||Date.now()-saved.created>30*60*1000)saved={id:crypto.randomUUID(),created:Date.now()};
  session=saved.id;
  if(analytics)sessionStorage.setItem('jarvis_visit',JSON.stringify(saved));
  $('#analytics-notice').hidden=localStorage.getItem('jarvis_analytics')!==null;
}catch{session=crypto.randomUUID();}
async function record(kind,value=''){
  if(!analytics)return;
  let referrer='';try{referrer=new URL(document.referrer).origin;}catch{}
  try{await api('/api/event',{id:crypto.randomUUID(),session,kind,value,referrer,consent:true});}catch{}
}
function pageView(){if(!pageRecorded&&analytics){pageRecorded=true;record('pageview');}}
$('#allow-analytics').addEventListener('click',()=>{analytics=true;try{localStorage.setItem('jarvis_analytics','yes');sessionStorage.setItem('jarvis_visit',JSON.stringify({id:session,created:Date.now()}));}catch{}$('#analytics-notice').hidden=true;pageView();});
$('#decline-analytics').addEventListener('click',()=>{analytics=false;try{localStorage.setItem('jarvis_analytics','no');sessionStorage.removeItem('jarvis_visit');}catch{}$('#analytics-notice').hidden=true;});
$('#privacy-settings').addEventListener('click',()=>$('#analytics-notice').hidden=false);
document.querySelectorAll('[role=tab]').forEach(tab=>tab.addEventListener('click',()=>record('section',tab.dataset.panel)));
pageView();refreshConnection();
