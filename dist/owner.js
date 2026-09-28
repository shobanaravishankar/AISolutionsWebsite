const el=id=>document.getElementById(id);
let setup=false, dashboard;
async function api(path,body){
  const response=await fetch(path,{method:body?'POST':'GET',headers:body?{'Content-Type':'application/json'}:{},body:body?JSON.stringify(body):undefined});
  const data=await response.json();if(!response.ok)throw new Error(data.error||'Request failed.');return data;
}
function node(tag,text,cls){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;}
function feedback(text){el('owner-feedback').textContent=text;}
async function load(){
  try{dashboard=await api('/api/owner/dashboard');el('login-panel').hidden=true;el('dashboard').hidden=false;render();}
  catch(error){el('dashboard').hidden=true;el('login-panel').hidden=false;const state=await api('/api/status');setup=state.owner_setup_needed;el('login-title').textContent=setup?'Set your local owner password':'Sign in';el('login-help').textContent=setup?'Choose at least 12 characters. This protects the inbox on this computer.':'Use your local owner password.';el('login-button').textContent=setup?'Create local owner access':'Sign in';el('owner-password').autocomplete=setup?'new-password':'current-password';}
}
function render(){
  el('connection-state').textContent=dashboard.config.ai_ready?'JARVIS model ready':dashboard.config.wrapper_connected?'JARVIS wrapper connected · model offline':'JARVIS connection pending';
  el('metrics').replaceChildren();
  for(const [key,label] of [['page_views','Opt-in page views'],['visits','Opt-in tab visits'],['enquiries','Enquiries'],['commands','AI requests'],['contacts','Supplied email contacts']]){const card=node('div',undefined,'owner-metric');card.append(node('strong',String(dashboard.totals[key])),node('span',label));el('metrics').append(card);}
  el('insights').replaceChildren();
  for(const [key,title] of [['topics','Topics'],['audiences','Audience selection'],['referrals','Referring domains']]){el('insights').append(node('h3',title));const list=node('ul');for(const row of dashboard[key])list.append(node('li',`${row.label.replaceAll('_',' ')} · ${row.count}`));if(!dashboard[key].length)list.append(node('li','No records yet.'));el('insights').append(list);}
  el('insights').append(node('h3','Recent recorded days'));const days=node('ul');for(const day of dashboard.daily)days.append(node('li',`${day.day} · ${day.page_views} page views / ${day.visits} tab visits`));if(!dashboard.daily.length)days.append(node('li','No opted-in visits yet.'));el('insights').append(days);
  el('business-email').value=dashboard.config.business_email;
  el('mail-state').textContent=dashboard.config.mail_ready?'Mail adapter is enabled on this server. This review inbox provides drafts only.':'Outbound email is disabled. No mailbox or sending service is connected.';
  renderRecords();
}
function renderRecords(){
  el('records').replaceChildren();const filter=el('record-filter').value;
  const records=dashboard.records.filter(row=>filter==='all'||row.kind===filter);
  if(!records.length)el('records').append(node('p','No matching records yet.','owner-note'));
  for(const row of records){
    const card=node('details',undefined,'owner-record');card.append(node('summary',`${row.kind==='enquiry'?'Enquiry':'AI request'} · ${row.name||row.topic.replaceAll('_',' ')} · ${row.status.replaceAll('_',' ')}`));
    card.append(node('p',`${new Date(row.created).toLocaleString()} · ${row.outcome} · ${row.audience.replaceAll('_',' ')} · ${row.id.slice(0,8)}`,'record-meta'),node('p',row.text??'Question text was not shared.','record-text'));
    if(row.email||row.phone)card.append(node('p',`Email: ${row.email||'not supplied'} | Phone: ${row.phone||'not supplied'} | Requested follow-up: ${row.contact_preference}`,'record-meta'));
    const status=node('select');status.id='status-'+row.id;for(const value of ['new','reviewing','drafted','followed_up','closed']){const option=node('option',value.replaceAll('_',' '));option.value=value;status.append(option);}status.value=row.status;
    const draft=node('textarea');draft.id='draft-'+row.id;draft.maxLength=6000;draft.value=row.draft;
    const note=node('textarea');note.id='note-'+row.id;note.maxLength=1000;note.value=row.note;
    for(const [control,label] of [[status,'Status'],[draft,'Reply draft — not sent'],[note,'Internal note']]){const lab=node('label',label);lab.htmlFor=control.id;card.append(lab,control);}
    const actions=node('div',undefined,'record-actions');const save=node('button','Save review');save.type='button';save.addEventListener('click',async()=>{save.disabled=true;try{await api('/api/owner/update',{id:row.id,status:status.value,draft:draft.value,note:note.value});row.status=status.value;row.draft=draft.value;row.note=note.value;card.querySelector('summary').textContent=`${row.kind==='enquiry'?'Enquiry':'AI request'} · ${row.name||row.topic.replaceAll('_',' ')} · ${row.status.replaceAll('_',' ')}`;feedback('Review saved. No message was sent.');}catch(error){feedback(error.message);}finally{save.disabled=false;}});
    const copy=node('button','Copy draft');copy.type='button';copy.addEventListener('click',async()=>{try{await navigator.clipboard.writeText(draft.value);feedback('Draft copied. Review it in your email application before sending.');}catch{feedback('Select the draft text and copy it manually.');}});
    const remove=node('button','Delete record');remove.type='button';remove.addEventListener('click',async()=>{if(!confirm('Permanently delete this record, including its contact details and draft?'))return;try{await api('/api/owner/delete',{id:row.id,confirm:true});feedback('Record deleted.');await load();}catch(error){feedback(error.message);}});
    actions.append(save,copy,remove);card.append(actions);el('records').append(card);
  }
}
el('login-form').addEventListener('submit',async event=>{event.preventDefault();el('login-button').disabled=true;try{await api(setup?'/api/owner/setup':'/api/owner/login',{password:el('owner-password').value});el('owner-password').value='';feedback('Signed in to the local inbox.');await load();}catch(error){feedback(error.message);}finally{el('login-button').disabled=false;}});
el('settings-form').addEventListener('submit',async event=>{event.preventDefault();try{await api('/api/owner/settings',{business_email:el('business-email').value});feedback('Business address saved as reference only.');}catch(error){feedback(error.message);}});
el('record-filter').addEventListener('change',renderRecords);
el('refresh').addEventListener('click',()=>load().catch(error=>feedback(error.message)));
el('logout').addEventListener('click',async()=>{await api('/api/owner/logout',{});dashboard=null;el('records').replaceChildren();feedback('Signed out.');await load();});
load().catch(error=>feedback(error.message));
