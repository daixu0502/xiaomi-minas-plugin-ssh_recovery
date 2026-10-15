// Isolated Chromium/Edge regression: no real NAS requests or real key material.
const fs=require('fs'),path=require('path'),assert=require('assert/strict');
const {chromium}=require('playwright');
const ui=path.resolve(__dirname,'../payload/ui');
const profiles=[
 {name:'desktop',width:1440,height:900,desktop:true},
 {name:'desktop-small',width:850,height:600,desktop:true},
 {name:'android-dark',width:390,height:844,mobile:true,dark:true},
 {name:'ios-light',width:390,height:844,mobile:true}
];
(async()=>{const browser=await chromium.launch({headless:true,executablePath:process.env.EDGE_PATH});
 try{for(const p of profiles){
  const context=await browser.newContext({viewport:{width:p.width,height:p.height},isMobile:!!p.mobile,hasTouch:!!p.mobile,colorScheme:p.dark?'dark':'light',userAgent:p.desktop?'SmartStorage Electron/30':p.name.startsWith('ios')?'Mozilla/5.0 iPhone Mobile Safari':'Mozilla/5.0 Android Mobile Chrome',acceptDownloads:true});
  const page=await context.newPage(),errors=[],calls=[];
  let s={ok:true,version:'1.1.3',helperVersion:'1.0.4',sshActive:true,socketSupported:true,port:22,hostKey:true,hostBackup:true,keySaved:false,fingerprint:'',bootFinished:true,bootService:{worker:true,cron:true,dropin:true},events:[],settings:{generateWithoutPublicKey:false},generated:{ready:false}};
  s.hostKeyValid=true;s.loginAuthorization={rootHome:'/home/rootx',homeExists:false,ready:false,reason:'home_missing'};
  if(p.desktop)await page.addInitScript(()=>{window.__MICRO_APP_ENVIRONMENT__=true;let listener;window.microApp={addDataListener(cb){listener=cb;},removeDataListener(){},dispatch(){setTimeout(()=>listener({cmd:'getDeviceInfo',data:{cgiPort:1234,cgiToken:'local-test-token'}}),0);}};});
  page.on('pageerror',e=>errors.push(e.message));
  await page.route('**/*',async route=>{
   const request=route.request(),url=new URL(request.url()),name=path.basename(url.pathname);
   if(name==='sshrecovery.cgi'){
    if(p.desktop&&request.headers().authorization!=='local-test-token')return route.fulfill({body:'<!doctype html><html>login</html>',contentType:'text/html'});
    const action=url.searchParams.get('action'),data=JSON.parse(request.postData()||'{}');calls.push({action,data,url:url.pathname,authorization:request.headers().authorization});
    if(action==='save_settings')s.settings.generateWithoutPublicKey=data.generateWithoutPublicKey;
    if(action==='recover'&&s.settings.generateWithoutPublicKey&&!s.keySaved){s.keySaved=true;s.fingerprint='SHA256:fake-generated-test-fingerprint';s.generated={ready:true,expires:Date.now()/1000+900};}
    if(action==='import_public'){s.keySaved=true;s.fingerprint='SHA256:fake-upload-test';}
    let extra={};if(action==='download_keys'){s.generated={ready:false};extra={keyArchive:Buffer.from('mock ZIP fixture; not a real private key').toString('base64'),downloadName:'ssh-login-keys.zip'};}
    if(action==='download_emergency')extra={emergencyArchive:Buffer.from('mock public-only emergency ZIP').toString('base64')};
    return route.fulfill({json:{...s,...extra}});
   }
   if(!/^(index\.html|[\w-]+\.(css|js))$/.test(name))return route.abort();
   let body=fs.readFileSync(path.join(ui,name),'utf8');
   if(name==='index.html')body=body.replace('<body>','<body><style>html,body{margin:0;height:100%;font-family:serif}ul,li{font-family:serif;font-size:16px;line-height:normal}#outside{position:fixed;opacity:0;pointer-events:none}</style><p id="outside">Host text</p><script>const $="host-global";let state="host-global";</script>');
   return route.fulfill({body,contentType:name.endsWith('.css')?'text/css':name.endsWith('.js')?'application/javascript':'text/html'});
  });
  await page.goto('http://ssh-ui.test/plugin/123/sshrecovery/index.html');
  await page.waitForFunction(()=>document.querySelector('#sshState').textContent==='已开启');
  assert(await page.locator('#error').isHidden());assert.equal(await page.locator('footer').textContent(),'插件版本 1.1.3 · 公共权限组件 1.0.4');
  assert.equal(await page.locator('#hostState').textContent(),'可用');
  assert.equal(await page.locator('#authorizationState').textContent(),'目录缺失');
  const emergencyDownload=page.waitForEvent('download');await page.locator('#downloadEmergency').click();
  assert.equal((await emergencyDownload).suggestedFilename(),'nas-ssh-emergency.zip');
  await page.waitForFunction(()=>!document.querySelector('#refresh').disabled);
  assert(!(await page.locator('body').innerText()).includes('id_ed25519'));
  assert.equal(await page.locator('.panel').first().evaluate(e=>getComputedStyle(e).paddingTop),'0px');
  assert(!(await page.locator('#fingerprint').evaluate(e=>getComputedStyle(e).fontFamily)).includes('monospace'));
  assert((await page.locator('h1').evaluate(e=>getComputedStyle(e).fontFamily)).includes('Segoe UI'));
  assert((await page.locator('#outside').evaluate(e=>getComputedStyle(e).fontFamily)).includes('serif'));
  assert(await page.locator('#keyFile').evaluate(e=>getComputedStyle(e).clipPath==='inset(50%)'));
  assert(await page.locator('#generateKey').isChecked()===false);
  assert(await page.locator('#downloadKeys').isDisabled());
  const cells=await page.locator('.ssh-status-item').evaluateAll(es=>es.map(e=>({top:e.getBoundingClientRect().top,left:e.getBoundingClientRect().left,width:e.getBoundingClientRect().width,border:getComputedStyle(e).borderLeftWidth})));
  const typography=await page.locator('.boot-copy p,.boot-facts li>span').evaluateAll(es=>es.map(e=>{const s=getComputedStyle(e);return {size:s.fontSize,line:s.lineHeight,family:s.fontFamily};}));
  assert(typography.length>=8);for(const style of typography)assert.deepEqual(style,typography[0]);assert.equal(typography[0].size,'14px');
  if(p.mobile){
   assert.equal(cells[2].top,cells[3].top);assert(cells[2].top>cells[0].top);assert.equal(cells[2].border,'0px');
   assert(cells[4].width>cells[0].width*1.9);assert.equal(cells[4].border,'0px');
   assert(await page.locator('.shell').evaluate(e=>e.scrollWidth<=e.clientWidth+1));
  }else{assert(calls[0].authorization==='local-test-token');for(const cell of cells){assert.equal(cell.top,cells[0].top);assert(Math.abs(cell.width-cells[0].width)<1);}}
  const choose=page.waitForEvent('filechooser');await page.locator('#selectFile').click();await (await choose).setFiles({name:'example-public.txt',mimeType:'text/plain',buffer:Buffer.from('local public key fixture')});
  assert.equal(await page.locator('#fileName').innerText(),'example-public.txt');
  if(process.env.SSH_SCREENSHOT_DIR){fs.mkdirSync(process.env.SSH_SCREENSHOT_DIR,{recursive:true});await page.locator('.shell').evaluate(e=>{e.scrollTop=0;window.scrollTo(0,0);});await page.screenshot({path:path.join(process.env.SSH_SCREENSHOT_DIR,p.name+'.png'),fullPage:!p.desktop});}
  const saving=page.waitForResponse(r=>r.url().includes('action=save_settings'));
  await page.locator('#generateKey').check();await page.locator('#confirm button[value=ok]').click();await saving;
  await page.waitForFunction(()=>!document.querySelector('#generateKey').disabled);
  assert(calls.some(c=>c.action==='save_settings'));assert(!calls.some(c=>c.action==='recover'));
  await page.locator('#recover').click();await page.locator('#confirm button[value=ok]').click();
  await page.waitForFunction(()=>!document.querySelector('#downloadKeys').disabled);
  await page.locator('#downloadKeys').click();const download=page.waitForEvent('download');await page.locator('#confirm button[value=ok]').click();
  assert.equal((await download).suggestedFilename(),'ssh-login-keys.zip');assert(await page.locator('#downloadFallback').isVisible());
  assert.deepEqual(errors,[]);console.log(p.name+': auth bridge / scoped DOM / card geometry / file control / explicit generation / download passed');
  await context.close();
 }}finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
