'use strict';
const $=s=>document.querySelector(s);let csrf='',last='';
const uid=()=>+$('#actor').value;
const chatId=()=>$('#destination').value==='group'?-1007:uid();
function toast(t){$('#toast').textContent=t;$('#toast').hidden=false;setTimeout(()=>$('#toast').hidden=true,5000);}
async function request(path,data){const res=await fetch(path,{credentials:'same-origin',...(data===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:JSON.stringify(data)})});const val=await res.json();if(!res.ok)throw new Error(val.error);return val;}
async function send(text){await request('/demo/message',{user_id:uid(),chat_id:chatId(),text});await refresh(true);}
async function clickLink(url){const parsed=new URL(url);const arg=parsed.searchParams.get('start');if(parsed.hostname==='t.me'&&arg){await send('/start '+arg);}else{window.open(url,'_blank','noopener');}}
async function refresh(force=false){
 const messages=await request('/demo/chat?chat='+chatId());const signature=JSON.stringify(messages)+chatId();if(!force&&signature===last)return;last=signature;
 const box=$('#chat'),atBottom=box.scrollHeight-box.scrollTop-box.clientHeight<100;box.replaceChildren();
 for(const m of messages){
  const bubble=document.createElement('div');bubble.className='bubble'+(m.mine?' mine':'');
  const text=document.createElement('div');text.textContent=m.text;bubble.append(text);
  if(m.document&&m.document_url){const file=document.createElement('a');file.href=m.document_url;file.download=m.document.file_name;file.textContent=m.document.file_name+' · '+m.document.file_size+' bytes';bubble.append(file);}
  if(m.reply_markup?.inline_keyboard){const buttons=document.createElement('div');buttons.className='buttons';
   for(const row of m.reply_markup.inline_keyboard){const line=document.createElement('div');line.className='row';for(const b of row){const button=document.createElement('button');button.type='button';button.textContent=b.text;button.onclick=async()=>{button.disabled=true;try{if(b.callback_data){await request('/demo/callback',{user_id:uid(),data:b.callback_data,message_id:m.message_id});await refresh(true);}else if(b.url)await clickLink(b.url);else if(b.web_app)window.open('/','_blank','noopener');}catch(e){toast(e.message);}finally{button.disabled=false;}};line.append(button);}buttons.append(line);}bubble.append(buttons);
  }box.append(bubble);
 }
 if(atBottom||force)box.scrollTop=box.scrollHeight;
}
$('#composer').onsubmit=async e=>{e.preventDefault();const text=$('#message').value.trim();if(!text)return;$('#composer').querySelector('button').disabled=true;try{await send(text);$('#message').value='';$('#message').focus();}catch(err){toast(err.message);}finally{$('#composer').querySelector('button').disabled=false;}};
$('#actor').onchange=()=>refresh(true).catch(e=>toast(e.message));$('#destination').onchange=()=>refresh(true).catch(e=>toast(e.message));
$('#start').onclick=async()=>{const button=$('#start');button.disabled=true;try{await send('/start');}catch(e){toast(e.message);}finally{button.disabled=false;}};
async function boot(){const config=await request('/api/config');if(!config.demo)throw new Error('The simulator is available only in demo mode.');try{csrf=(await request('/api/me')).csrf;}catch(e){csrf=(await request('/api/auth/demo',{user_id:1})).csrf;}await refresh(true);$('#start').disabled=false;setInterval(()=>refresh().catch(()=>{}),1500);}
boot().catch(e=>toast(e.message));
