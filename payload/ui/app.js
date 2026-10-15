(function () {
'use strict';
const doc=window.XiaomiPluginClient?.document||document;
const byId=id=>doc.getElementById(id);
let state=null,working=false,downloadURL='';
async function api(action,data={}){
 const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),60000);
 try{
  const options={method:'POST',credentials:'same-origin',cache:'no-store',headers:{'Content-Type':'application/json'},body:JSON.stringify(data),signal:controller.signal};
  const response=window.XiaomiPluginClient?await window.XiaomiPluginClient.request({plugin:'sshrecovery',cgi:'sshrecovery.cgi',action,options}):await fetch('sshrecovery.cgi?action='+action,options);
  const raw=await response.text();let result;
  try{result=JSON.parse(raw);}catch{throw Error(raw.trim().startsWith('<')?'接口返回了网页，请重新打开插件刷新客户端授权。':'设备返回的数据格式异常，请稍后刷新。');}
  if(!response.ok||!result.ok)throw Error(result.error||'操作失败');
  return result;
 }finally{clearTimeout(timer);}
}
function setBusy(on){
 working=on;
 for(const id of ['refresh','recover','installBoot','saveKey','forgetKey','selectFile','generateKey','downloadKeys','downloadEmergency'])byId(id).disabled=on||!state;
 if(!on&&state){byId('recover').disabled=!state.socketSupported||state.bootFinished===false;byId('forgetKey').disabled=!state.keySaved;byId('downloadKeys').disabled=!state.generated?.ready;}
 byId('refresh').classList.toggle('is-loading',on);
}
function render(s){
 state=s;byId('sshState').textContent=s.sshActive?'已开启':'未开启';byId('port').textContent=s.port;
 byId('hostState').textContent=(s.hostKeyValid??s.hostKey)?'可用':s.hostBackup?'可恢复':s.hostKey?'待修复':'缺失';byId('keyState').textContent=s.keySaved?'已保存':'未配置';
 const a=s.loginAuthorization,reasons={home_missing:'目录缺失',ssh_missing:'目录缺失',authorization_missing:'未写入',saved_key_not_installed:'公钥未安装',no_saved_key:'未配置校验',permissions_or_content:'权限或内容异常',ready:'已就绪'};
 byId('authorizationState').textContent=a?(reasons[a.reason]||'待检查'):'待检查';
 byId('authorizationNote').textContent=a?'实际登录目录：'+a.rootHome+'。服务器身份密钥与登录授权分别检查；“恢复公钥已保存”不代表已安装到登录目录。':'正在检查实际登录目录和授权文件。';
 byId('fingerprint').textContent=s.fingerprint||'尚未保存恢复公钥';byId('fingerprint').classList.toggle('empty',!s.fingerprint);
 byId('bootState').textContent=s.bootFinished===false?'开机检查中':s.bootFinished===true?'开机检查已结束':'无开机检查单元';
 const b=s.bootService;byId('bootService').textContent=b.worker&&b.cron&&b.dropin?'已安装':b.worker||b.cron||b.dropin?'配置不完整':'未安装';
 byId('generateKey').checked=s.settings?.generateWithoutPublicKey===true;
 byId('recoveryNote').textContent=byId('generateKey').checked?'未保存公钥时，点击恢复才生成登录密钥。请及时下载并妥善保存私钥。':'未保存公钥时，只开启 SSH，不改动密钥文件。已有公钥时，按保存的恢复材料恢复。';
 byId('downloadHint').hidden=!s.generated?.ready;
 if(s.generated?.ready)byId('downloadHint').textContent='新登录密钥仅可领取一次，截止 '+new Date(s.generated.expires*1000).toLocaleTimeString()+'；不要公开私钥。';
 byId('pluginVersion').textContent='插件版本 '+s.version+' · 公共权限组件 '+(s.helperVersion||'未知');
 const box=byId('events');box.replaceChildren();
 if(!s.events.length){const p=doc.createElement('p');p.className='note';p.textContent='暂无操作记录';box.append(p);}
 for(const e of s.events){const row=doc.createElement('div');row.className='event';const t=doc.createElement('time');t.textContent=new Date(e.time*1000).toLocaleString();const text=doc.createElement('div');text.textContent=e.message;row.append(t,text);box.append(row);}
}
async function perform(action,data={}){
 if(working)return null;setBusy(true);byId('error').hidden=true;
 try{const result=await api(action,data);const visible={...result};delete visible.keyArchive;delete visible.emergencyArchive;render(visible);if(result.message){byId('toast').textContent=result.message;byId('toast').hidden=false;setTimeout(()=>byId('toast').hidden=true,6000);}return result;}
 catch(e){byId('error').textContent=e.name==='AbortError'?'操作超时，请刷新状态后再重试':e.message;byId('error').hidden=false;return null;}
 finally{setBusy(false);}
}
function confirmAction(title,text,overwrite=false){
 return new Promise(resolve=>{const d=byId('confirm');byId('confirmTitle').textContent=title;byId('confirmText').textContent=text;byId('overwriteRow').hidden=!overwrite;byId('overwrite').checked=false;d.returnValue='';
 d.addEventListener('close',()=>resolve({ok:d.returnValue==='ok',overwrite:byId('overwrite').checked}),{once:true});window.XiaomiPluginClient.openDialog(d);});
}
byId('refresh').onclick=()=>perform('status');
byId('recover').onclick=async()=>{
 const message=state?.keySaved?'将开启 SSH，并按保存的公钥和主机密钥副本恢复。不会覆盖其他登录公钥。':state?.settings?.generateWithoutPublicKey?'将生成新的登录密钥并开启 SSH。请在 15 分钟内领取一次密钥包，私钥不得公开。':'仅开启 SSH，不改动登录公钥、主机密钥或恢复副本。';
 if((await confirmAction('恢复 SSH',message)).ok)perform('recover');
};
byId('generateKey').onchange=async()=>{
 const wanted=byId('generateKey').checked;
 if(wanted&&!(await confirmAction('开启登录密钥生成','仅当没有保存公钥且点击恢复 SSH 时生成新的登录密钥。保存设置不会立即生成密钥；生成后提供一次性下载。')).ok){byId('generateKey').checked=false;return;}
 const result=await perform('save_settings',{generateWithoutPublicKey:wanted});if(!result)byId('generateKey').checked=state?.settings?.generateWithoutPublicKey===true;
};
byId('downloadKeys').onclick=async()=>{
 if(!(await confirmAction('下载新登录密钥','密钥包包含登录私钥，只能领取一次。请使用可信连接并保存到安全位置；不会下载 NAS 主机私钥。')).ok)return;
 const result=await perform('download_keys');if(!result?.keyArchive)return;
 if(downloadURL)URL.revokeObjectURL(downloadURL);
 const bytes=Uint8Array.from(atob(result.keyArchive),c=>c.charCodeAt(0));delete result.keyArchive;
 downloadURL=URL.createObjectURL(new Blob([bytes],{type:'application/zip'}));
 const link=byId('downloadFallback');link.href=downloadURL;link.download=result.downloadName||'ssh-login-keys.zip';link.hidden=false;
 byId('downloadHint').textContent='密钥包已领取。若客户端未自动保存，请点击“点此保存密钥包”；关闭或刷新页面会失去此临时下载。';byId('downloadHint').hidden=false;link.click();
};
byId('installBoot').onclick=async()=>{const r=await confirmAction('安装 / 更新开机修复','安装等待开机检查和有限复查任务，备份现有登录公钥供文件缺失时恢复，并修复新固件 mi-shell。不会生成登录密钥或重启 NAS。',true);if(r.ok)perform('install_boot',{overwrite:r.overwrite});};
byId('downloadEmergency').onclick=async()=>{
 const result=await perform('download_emergency');if(!result?.emergencyArchive)return;
 if(downloadURL)URL.revokeObjectURL(downloadURL);
 const bytes=Uint8Array.from(atob(result.emergencyArchive),c=>c.charCodeAt(0));delete result.emergencyArchive;
 downloadURL=URL.createObjectURL(new Blob([bytes],{type:'application/zip'}));
 const link=byId('downloadFallback');link.href=downloadURL;link.download='nas-ssh-emergency.zip';link.hidden=false;link.textContent='保存已生成的恢复包';link.click();
};
byId('selectFile').onclick=()=>byId('keyFile').click();
byId('keyFile').onchange=()=>byId('fileName').textContent=byId('keyFile').files[0]?.name||'尚未选择文件';
function resetFile(){byId('keyText').value='';byId('keyFile').value='';byId('fileName').textContent='尚未选择文件';}
byId('keyType').onchange=()=>{const privateMode=byId('keyType').value==='import_private';resetFile();byId('keyText').disabled=privateMode;byId('privateNote').textContent=privateMode?'仅支持未加密的 OpenSSH Ed25519 私钥，只在内存中提取公钥，不写入磁盘。建议优先上传公钥；私钥上传应使用可信 HTTPS 连接。':'公钥保存到独立运行数据区，不参与源码校验；恢复时追加到登录授权文件，不覆盖其他公钥。';};
byId('keyForm').onsubmit=async e=>{
 e.preventDefault();if(working)return;const type=byId('keyType').value,file=byId('keyFile').files[0];
 try{if(file&&file.size>65536)throw Error('密钥文件过大');let key=file?await file.text():byId('keyText').value;if(!key.trim())throw Error('请先选择文件或填写公钥');
 const r=await confirmAction('保存恢复公钥',type==='import_private'?'仅提取、校验并保存公钥，私钥不写入磁盘。此操作不会立即修改登录授权文件。':'保存此公钥用于后续恢复，不会立即修改登录授权文件。保存新公钥会清理未领取的旧生成密钥包。');if(r.ok)await perform(type,{key});key='';
 }catch(error){byId('error').textContent=error.message;byId('error').hidden=false;}finally{resetFile();}
};
byId('forgetKey').onclick=async()=>{if((await confirmAction('移除保存的公钥','只删除插件内的公钥和未领取的生成密钥包，不撤销当前登录授权，不关闭 SSH。')).ok)perform('forget_key');};
window.addEventListener('unmount',()=>{if(downloadURL)URL.revokeObjectURL(downloadURL);});
perform('status');
})();
