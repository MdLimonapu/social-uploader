(function(){
const $=(s,r=document)=>r.querySelector(s),$$=(s,r=document)=>[...r.querySelectorAll(s)];
// theme
$('#themeBtn')?.addEventListener('click',()=>{const t=document.documentElement.dataset.theme==='dark'?'light':'dark';document.documentElement.dataset.theme=t;try{localStorage.setItem('theme',t)}catch(e){}});
// toasts
window.toast=function(msg,kind='info'){const w=$('#toasts'),el=document.createElement('div');el.className='toast '+kind;
 const tx=document.createElement('div');tx.className='tx';tx.textContent=msg;const b=document.createElement('button');b.textContent='✕';b.onclick=()=>el.remove();
 el.append(tx,b);w.append(el);setTimeout(()=>{el.classList.add('out');setTimeout(()=>el.remove(),300)},kind==='bad'?8000:4500)};
try{JSON.parse(document.body.dataset.toasts||'[]').forEach(([k,m])=>toast(m,k))}catch(e){}
const Q={uploaded:['ok','Upload started – watch the progress below.'],scheduled:['ok','Post scheduled.'],cancelled:['ok','Scheduled post cancelled.'],
 rescheduled:['ok','New time saved.'],badtime:['bad','Please pick a valid future date and time.'],connected:['ok','Account connected!']};
const q=new URLSearchParams(location.search).get('t');if(q&&Q[q]){toast(Q[q][1],Q[q][0]);history.replaceState(null,'',location.pathname)}
// auto refresh while jobs are running
if(document.body.dataset.refresh==='1')setTimeout(()=>location.reload(),4000);
// copy buttons
$$('[data-copy]').forEach(b=>b.addEventListener('click',()=>{navigator.clipboard?.writeText(b.dataset.copy).then(()=>toast('Copied to clipboard','ok'),()=>toast(b.dataset.copy))}));
// drop zone
const dz=$('#drop');if(dz){const inp=$('input[type=file]',dz),vid=$('video',dz);
 const show=f=>{if(!f)return;dz.classList.add('has');$('#fname').textContent=f.name;$('#fsize').textContent=(f.size/1048576).toFixed(1)+' MB';try{vid.src=URL.createObjectURL(f)}catch(e){}
  const sc=$('#shortsCheck');sc.innerHTML='';vid.onloadedmetadata=()=>{const w=vid.videoWidth,h=vid.videoHeight,d=vid.duration,bad=[];
   if(w&&h&&h<w)bad.push('horizontal '+w+'×'+h);if(d>180.5)bad.push(Math.round(d)+'s long');
   const b=document.createElement('span');b.className='badge '+(bad.length?'warn':'ok');b.innerHTML='<i></i>';
   b.append(bad.length?'Not a Short: '+bad.join(', ')+' – use “YouTube (normal video)” instead of YouTube Shorts':'Shorts-ready · '+w+'×'+h+' · '+Math.round(d)+'s');sc.replaceChildren(b);
   const ys=$('input[name=platforms][value=youtube]');
   if(bad.length&&ys&&ys.checked)toast('Not a YouTube Short ('+bad.join(', ')+'). Untick YouTube Shorts and pick “YouTube (normal video)”.','bad')}};
 ['dragenter','dragover'].forEach(e=>dz.addEventListener(e,ev=>{ev.preventDefault();dz.classList.add('over')}));
 ['dragleave','drop'].forEach(e=>dz.addEventListener(e,()=>dz.classList.remove('over')));
 dz.addEventListener('drop',ev=>{ev.preventDefault();if(ev.dataTransfer.files.length){inp.files=ev.dataTransfer.files;show(inp.files[0])}});
 inp.addEventListener('change',()=>show(inp.files[0]));}
// schedule toggle + quick picks
const at=$('#whenAt');if(at){const upd=()=>{const s=$('input[name=when]:checked').value==='schedule';at.classList.toggle('show',s);$('#submitTxt').textContent=s?'Schedule post':'Post now'};
 $$('input[name=when]').forEach(r=>r.addEventListener('change',upd));upd();
 const pad=n=>String(n).padStart(2,'0'),fmt=d=>`${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
 const dt=$('input[name=run_at]');dt.min=fmt(new Date());
 $$('[data-quick]').forEach(b=>b.addEventListener('click',()=>{const d=new Date(),v=b.dataset.quick;
  if(v.endsWith('h'))d.setHours(d.getHours()+ +v.slice(0,-1));else{d.setDate(d.getDate()+ +v.split('@')[0]);d.setHours(+v.split('@')[1],0,0,0)}dt.value=fmt(d)}));}
// upload form validation + busy state
const uf=$('#uploadForm');if(uf)uf.addEventListener('submit',e=>{
 if(!$('input[type=file]',uf).files.length){e.preventDefault();return toast('Choose or drop a video first.','bad')}
 if(!$$('input[name=platforms]:checked',uf).length){e.preventDefault();return toast('Pick at least one platform.','bad')}
 if($('input[name=when]:checked').value==='schedule'){const v=$('input[name=run_at]').value;if(!v||new Date(v)<=new Date()){e.preventDefault();return toast('Pick a future date and time.','bad')}}
 const b=$('button[type=submit]',uf);b.disabled=true;$('#submitTxt').textContent='Uploading…'});
// local times rendered from epoch
$$('[data-ts]').forEach(el=>{const d=new Date(+el.dataset.ts*1000);el.textContent=d.toLocaleString([], {weekday:'short',day:'numeric',month:'short',hour:'2-digit',minute:'2-digit'})});
// log autoscroll
const lg=$('.log');if(lg)lg.scrollTop=lg.scrollHeight;
})();
