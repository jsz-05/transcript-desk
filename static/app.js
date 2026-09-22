const $=id=>document.getElementById(id);let selected=null,loggedIn=false,currentText='',polling=false;let modelState=null,modelChanging=false,deleteTarget=null,deleting=false,refreshVersion=0,menuJob=null,menuOrigin=null;
async function api(path,options={}){const response=await fetch(path,{...options,headers:{'X-Transcript-Request':'1',...(options.body instanceof FormData?{}:{'Content-Type':'application/json'}),...options.headers}});const data=await response.json();if(!response.ok){if(response.status===401&&path!='/api/login')showLogin();throw Error(typeof data.detail==='string'?data.detail:'The request could not be completed.')}return data;}
function showLogin(){loggedIn=false;$('login').hidden=false;$('workspace').hidden=true;$('logout').hidden=true;}
async function showApp(){loggedIn=true;$('login').hidden=true;$('workspace').hidden=false;$('logout').hidden=false;await refresh();}
function toast(text){$('toast').textContent=text;$('toast').hidden=false;setTimeout(()=>$('toast').hidden=true,2200);}
$('loginForm').onsubmit=async e=>{e.preventDefault();$('loginError').textContent='';try{await api('/api/login',{method:'POST',body:JSON.stringify({password:$('password').value})});$('password').value='';await showApp();}catch(error){$('loginError').textContent=error.message;}};
$('logout').onclick=async()=>{try{await api('/api/logout',{method:'POST'});showLogin();}catch(e){toast(e.message);}};
$('file').onchange=()=>{const f=$('file').files[0];$('fileName').textContent=f?f.name:'Up to 300 MB';$('clearFile').hidden=!f;$('url').disabled=!!f;$('captions').disabled=!!f;};
$('clearFile').onclick=()=>{$('file').value='';$('file').onchange();};
$('transcriptForm').onsubmit=async e=>{e.preventDefault();$('formError').textContent='';const file=$('file').files[0];if(!file&&!$('url').value.trim()){$('formError').textContent='Paste a video link or choose a file.';return;}if(file&&file.size>300*1024*1024){$('formError').textContent='Choose a file smaller than 300 MB.';return;}$('submit').disabled=true;$('submit').textContent=file?'Uploading…':'Adding…';try{let job;if(file){const body=new FormData();body.append('file',file);body.append('language',$('language').value);body.append('model',$('model').value);job=await api('/api/upload',{method:'POST',body});}else{job=await api('/api/jobs',{method:'POST',body:JSON.stringify({url:$('url').value,language:$('language').value,model:$('model').value,captions:$('captions').checked})});}selected=job.id;$('url').value='';$('clearFile').click();await refresh();}catch(error){$('formError').textContent=error.message;}finally{$('submit').disabled=false;$('submit').textContent='Get transcript';}};
async function refresh(){if(!loggedIn||polling||deleting||menuJob||$('deleteDialog').open)return;polling=true;const version=refreshVersion;try{const [jobs,model]=await Promise.all([api('/api/jobs'),api('/api/model')]);if(version!==refreshVersion)return;renderModel(model);$('count').textContent=jobs.length||'';$('emptyHistory').hidden=jobs.length>0;const frag=document.createDocumentFragment();if(!jobs.some(job=>job.id===selected))selected=jobs[0]?.id||null;for(const job of jobs){const button=document.createElement('button');button.dataset.jobId=job.id;button.setAttribute('aria-haspopup','menu');button.oncontextmenu=event=>{event.preventDefault();openJobMenu(job,button,event.clientX,event.clientY);};button.onkeydown=event=>{if(event.key==='ContextMenu'||(event.shiftKey&&event.key==='F10')){event.preventDefault();const rect=button.getBoundingClientRect();openJobMenu(job,button,rect.left+12,rect.bottom);}};button.className='job'+(job.id===selected?' active':'');button.setAttribute('aria-pressed',job.id===selected?'true':'false');const title=document.createElement('strong');title.textContent=job.title;const meta=document.createElement('small');const names={queued:'Queued',working:'Preparing',downloading:'Downloading',transcribing:'Transcribing',done:'Ready',error:'Needs attention'};meta.textContent=(names[job.status]||job.status)+' · '+new Date(job.created*1000).toLocaleDateString(undefined,{month:'short',day:'numeric'});button.append(title,meta);button.onclick=()=>{selected=job.id;refresh();};frag.append(button);}$('jobs').replaceChildren(frag);if(!selected){$('emptyReader').hidden=false;$('detail').hidden=true;currentText='';$('transcript').textContent='';}if(selected){const requested=selected;const job=await api('/api/jobs/'+requested);if(version!==refreshVersion||selected!==requested)return;$('emptyReader').hidden=true;$('detail').hidden=false;$('title').textContent=job.title;$('source').textContent=job.source||'TRANSCRIPT';$('status').textContent=job.status==='queued'&&!modelState?.enabled?'Queued · load the model to resume processing':job.message||job.status;$('jobError').textContent=job.error||'';$('progress').hidden=!['working','downloading','transcribing'].includes(job.status);if(job.progress>0)$('progress').value=job.progress;else $('progress').removeAttribute('value');$('actions').hidden=job.status!=='done';currentText=job.result?.formatted_text||job.result?.text||'';if($('transcript').textContent!==currentText)$('transcript').textContent=currentText;if(job.status==='done'){$('status').textContent=job.result.segments.length?`${job.result.language} · ${job.result.elapsed_seconds}s processing time`:'No speech detected.';$('txt').href=`/api/jobs/${selected}/download?format=txt`;$('srt').href=`/api/jobs/${selected}/download?format=srt`;}}}catch(error){if(loggedIn)$('formError').textContent='Connection interrupted. Retrying automatically. '+error.message;}finally{polling=false;}}
$('copy').onclick=async()=>{try{await navigator.clipboard.writeText(currentText);toast('Transcript copied');}catch{$('transcript').focus();const range=document.createRange();range.selectNodeContents($('transcript'));const selection=window.getSelection();selection.removeAllRanges();selection.addRange(range);toast('Text selected. Press Ctrl+C or ⌘C to copy.');}};
api('/api/session').then(data=>data.authenticated?showApp():showLogin()).catch(()=>{showLogin();$('loginError').textContent='Cannot reach the server. Check that the mini PC is online.';});setInterval(refresh,4000);
if(document.modelContext?.registerTool){const life=new AbortController();window.addEventListener('pagehide',()=>life.abort(),{once:true});for(const tool of [{name:'submit_transcription',description:'Submit a YouTube or Instagram URL to the signed-in user’s transcript queue. Creates a job; does not immediately return a finished transcript.',inputSchema:{type:'object',properties:{url:{type:'string'},use_subtitles:{type:'boolean'}},required:['url'],additionalProperties:false},annotations:{readOnlyHint:false,untrustedContentHint:true},execute:async input=>{if(!loggedIn)throw Error('Sign in first.');if(typeof input.url!=='string')throw Error('A URL is required.');const job=await api('/api/jobs',{method:'POST',body:JSON.stringify({url:input.url,captions:input.use_subtitles!==false,language:$('language').value,model:$('model').value})});selected=job.id;await refresh();return {job_id:job.id,status:job.status};}},{name:'read_transcription',description:'Read job progress or raw transcript text. Long transcripts are chunked; follow next_offset to retrieve the complete text.',inputSchema:{type:'object',properties:{job_id:{type:'string'},offset:{type:'integer',minimum:0}},required:['job_id'],additionalProperties:false},annotations:{readOnlyHint:true,untrustedContentHint:true},execute:async input=>{if(!loggedIn)throw Error('Sign in first.');if(!/^[a-f0-9]{24}$/.test(input.job_id))throw Error('Invalid job ID.');const job=await api('/api/jobs/'+input.job_id);const offset=input.offset||0;if(!Number.isInteger(offset)||offset<0)throw Error('Invalid offset.');if(job.status!=='done')return {job_id:job.id,status:job.status,progress:job.progress,error:job.error};const text=job.result.text,end=Math.min(text.length,offset+24000);return {job_id:job.id,source:job.result.source,description:job.result.description||'',description_status:job.result.description_status||'not_saved',text:text.slice(offset,end),total_characters:text.length,next_offset:end<text.length?end:null};}}]){try{Promise.resolve(document.modelContext.registerTool(tool,{signal:life.signal})).catch(()=>{});}catch{}}}

function renderModel(state){
  modelState=state;
  const descriptions={ready:'Loaded in memory · ready for the next recording.',busy:'Processing a recording · model stays loaded between jobs.',starting:'Loading Whisper Base into memory…',unloaded:'Unloaded · RAM released. New jobs wait until you load the model.',unloading:state.busy?'Finishing the current recording, then releasing RAM. New jobs are paused.':'Releasing model memory…',error:'Model unavailable. '+state.error};
  $('modelStatus').textContent=descriptions[state.state]||state.state;
  $('modelToggle').textContent=state.state==='error'?'Retry load':state.enabled?'Unload model':state.state==='unloading'?'Keep model loaded':'Load model';
  $('modelToggle').disabled=modelChanging;
}
$('modelToggle').onclick=async()=>{
  if(!modelState)return;
  modelChanging=true;$('modelToggle').disabled=true;
  try{renderModel(await api('/api/model',{method:'POST',body:JSON.stringify({enabled:modelState.state==='error'||!modelState.enabled})}));}
  catch(error){toast(error.message);}
  finally{modelChanging=false;$('modelToggle').disabled=false;await refresh();}
};

function closeJobMenu(restoreFocus=false){
  $('jobMenu').hidden=true;menuJob=null;
  if(restoreFocus&&menuOrigin?.isConnected)menuOrigin.focus();
}
function openJobMenu(job,origin,x,y){
  menuJob=job;menuOrigin=origin;
  const menu=$('jobMenu'),item=$('menuDelete');
  item.disabled=!['done','error'].includes(job.status);
  item.title=item.disabled?'Wait for this job to finish before deleting it.':'';
  menu.hidden=false;
  if(!x&&!y){const rect=origin.getBoundingClientRect();x=rect.left+12;y=rect.bottom;}
  menu.style.left=Math.max(8,Math.min(x,window.innerWidth-menu.offsetWidth-8))+'px';
  menu.style.top=Math.max(8,Math.min(y,window.innerHeight-menu.offsetHeight-8))+'px';
  if(!item.disabled)item.focus();
}
$('menuDelete').onclick=()=>{
  if(!menuJob)return;
  deleteTarget=menuJob.id;
  $('deleteName').textContent=menuJob.title;
  closeJobMenu();
  $('deleteError').textContent='';
  $('deleteDialog').showModal();
  $('cancelDelete').focus();
};
document.addEventListener('pointerdown',event=>{if(!$('jobMenu').contains(event.target))closeJobMenu();});
document.addEventListener('keydown',event=>{if(menuJob&&['Escape','Tab'].includes(event.key)){if(event.key==='Escape')event.preventDefault();closeJobMenu(true);}});
window.addEventListener('resize',()=>closeJobMenu());
document.addEventListener('scroll',()=>closeJobMenu(),true);
$('deleteDialog').addEventListener('close',()=>{if(menuOrigin?.isConnected)menuOrigin.focus();});
$('cancelDelete').onclick=()=>{if(!deleting)$('deleteDialog').close();};
$('deleteDialog').addEventListener('cancel',event=>{if(deleting)event.preventDefault();});
$('confirmDelete').onclick=async()=>{
  if(!deleteTarget||deleting)return;
  deleting=true;refreshVersion++;
  $('confirmDelete').disabled=true;$('cancelDelete').disabled=true;
  try{
    await api('/api/jobs/'+deleteTarget,{method:'DELETE'});
    if(selected===deleteTarget){selected=null;currentText='';$('transcript').textContent='';$('detail').hidden=true;$('emptyReader').hidden=false;}
    $('deleteDialog').close();deleteTarget=null;
    toast('Transcript deleted from the server');
  }catch(error){$('deleteError').textContent=error.message;}
  finally{
    deleting=false;$('confirmDelete').disabled=false;$('cancelDelete').disabled=false;
    while(polling)await new Promise(resolve=>setTimeout(resolve,25));
    await refresh();
  }
};
