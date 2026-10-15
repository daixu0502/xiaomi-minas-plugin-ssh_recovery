// Real form/bridge, synthetic keys and mocked APIs; never uploads real keys.
const {chromium}=require('playwright');
const fs=require('fs'),path=require('path'),assert=require('assert/strict');
const ui=path.resolve(__dirname,'../payload/ui');
const state={ok:true,version:'1.1.5',helperVersion:'1.0.5',sshActive:true,port:22,hostKey:true,hostKeyValid:true,keySaved:false,bootFinished:true,socketSupported:true,bootService:{worker:true,cron:true,dropin:true},settings:{generateWithoutPublicKey:false},events:[]};
const publicKey='ssh-ed25519 '+Buffer.concat([Buffer.from([0,0,0,11]),Buffer.from('ssh-ed25519'),Buffer.from([0,0,0,32]),Buffer.alloc(32,120)]).toString('base64');
const privateKey='-----BEGIN OPENSSH PRIVATE KEY-----\nsynthetic-not-a-real-private-key\n-----END OPENSSH PRIVATE KEY-----';

(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:process.env.EDGE_PATH||'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'});
 try{for(const profile of [{name:'desktop',width:1440,height:900},{name:'embedded-small',width:870,height:526,embedded:true},{name:'android-dark',width:390,height:844,mobile:true,dark:true},{name:'ios-light',width:390,height:844,mobile:true}]){
  const errors=[],calls=[];let reject=true,delay=0;
  const context=await browser.newContext({viewport:{width:profile.width,height:profile.height},isMobile:!!profile.mobile,hasTouch:!!profile.mobile,colorScheme:profile.dark?'dark':'light',userAgent:profile.mobile?(profile.name.startsWith('android')?'Android Mobile':'iPhone Mobile Safari'):'SmartStorage Electron/35'});
  const page=await context.newPage();page.on('pageerror',error=>errors.push(error.message));
  if(profile.embedded)await page.addInitScript(()=>window.__MICRO_APP_ENVIRONMENT__=true);
  await page.exposeFunction('importFixture',async q=>{
   calls.push(q);if(q.action==='status')return state;
   if(q.action==='import_public'){if(delay)await new Promise(r=>setTimeout(r,delay));return reject?{ok:false,error:'文件包含多条公钥，请选择只包含一条公钥的文件，不会自动选取其中一条'}:{...state,keySaved:true,message:'恢复公钥已保存'};}
   throw Error('Unexpected action '+q.action);
  });
  await page.route('**/*',route=>{
   const name=path.basename(new URL(route.request().url()).pathname)||'index.html';if(!/^[\w.-]+$/.test(name)||!fs.existsSync(path.join(ui,name)))return route.abort();
   let body=fs.readFileSync(path.join(ui,name),'utf8');
   if(name==='client-bridge.js')body+='\nwindow.XiaomiPluginClient.request=async p=>new Response(JSON.stringify(await window.importFixture({action:p.action,body:JSON.parse(p.options.body||"{}")})));';
   if(name==='index.html'&&profile.embedded)body=body.replace('<body>','<body><micro-app style="display:block;position:absolute;left:20px;top:20px;width:830px;height:486px">').replace('</body>','</micro-app></body>');
   return route.fulfill({body,contentType:name.endsWith('.js')?'application/javascript':name.endsWith('.css')?'text/css':'text/html'});
  });
  await page.goto('http://ssh-import.test/index.html');await page.waitForFunction(()=>!document.querySelector('#saveKey').disabled);
  await page.locator('#keyText').fill(publicKey+'\n'+publicKey);await page.locator('#saveKey').click();
  await page.locator('#confirm button[value=ok]').click();
  await page.locator('#keyError').filter({hasText:'多条公钥'}).waitFor();
  assert(await page.locator('#error').isHidden(),'import error remained at page top');
  assert.equal(await page.locator('#keyText').inputValue(),publicKey+'\n'+publicKey,'failed public input was discarded');
  assert(await page.locator('#toast').isVisible(),'error toast not visible');
  await page.waitForTimeout(450);
  assert(await page.locator('#keyError').evaluate(e=>{const r=e.getBoundingClientRect(),clip=e.closest('micro-app')?.getBoundingClientRect();return r.top>=(clip?.top||0)-1&&r.bottom<=(clip?.bottom||innerHeight)+1;}),'inline error not in visible viewport');
  const before=calls.filter(c=>c.action==='import_public').length;
  await page.locator('#keyFile').setInputFiles({name:'private-key.txt',mimeType:'text/plain',buffer:Buffer.from(privateKey)});await page.locator('#saveKey').click();
  await page.locator('#keyError').filter({hasText:'选择的是私钥'}).waitFor();
  assert.equal(calls.filter(c=>c.action==='import_public').length,before,'private key was posted in public mode');
  assert(!(await page.locator('#confirm').evaluate(e=>e.open)),'private mismatch opened confirmation');
  const utf16=Buffer.concat([Buffer.from([255,254]),Buffer.from(publicKey+'\r\n','utf16le')]);
  await page.locator('#keyFile').setInputFiles({name:'public-key.pub',mimeType:'text/plain',buffer:utf16});
  await page.locator('#saveKey').click();await page.locator('#confirm button[value=cancel]').click();
  assert.equal(await page.locator('#keyFile').evaluate(e=>e.files.length),1,'cancel discarded selected public file');
  reject=false;delay=300;await page.locator('#saveKey').click();await page.locator('#confirm button[value=ok]').click();
  await page.waitForFunction(()=>document.querySelector('#saveKey').disabled);
  assert(await page.locator('#keyType').isDisabled(),'format changed during submission');
  await page.waitForFunction(()=>!document.querySelector('#saveKey').disabled&&document.querySelector('#keyFile').files.length===0);
  const posted=calls.filter(c=>c.action==='import_public').at(-1).body.key;
  assert.equal(posted.trim(),publicKey,'UTF-16 public file decoded incorrectly');
  assert(await page.locator('#keyError').isHidden(),'successful import retained old error');
  assert.deepEqual(errors,[],profile.name+' JavaScript errors');
  console.log('PASS '+profile.name+': inline errors, retry, private mismatch, cancel, UTF-16, busy state');await context.close();
 }}finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
