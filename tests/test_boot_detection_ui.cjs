// Isolated status fixtures; no NAS writes or credentials.
const {chromium}=require('playwright');
const fs=require('fs'),path=require('path'),assert=require('assert/strict');
const ui=path.resolve(__dirname,'../payload/ui');
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:process.env.EDGE_PATH||'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'});
 try{for(const width of [1280,390]){
  const context=await browser.newContext({viewport:{width,height:850},isMobile:width===390,hasTouch:width===390});
  const page=await context.newPage();const errors=[],calls=[];page.on('pageerror',e=>errors.push(e.message));
  let state={ok:true,version:'1.1.8',sshActive:true,port:22,hostKeyValid:true,keySaved:false,bootFinished:true,socketSupported:true,settings:{generateWithoutPublicKey:false},events:[],bootService:{worker:true,cron:true,dropin:true,current:true,conflicts:[]}};
  await page.route('**/*',route=>{
   const url=new URL(route.request().url()),name=path.basename(url.pathname);
   if(name==='sshrecovery.cgi'){
    const action=url.searchParams.get('action'),body=JSON.parse(route.request().postData()||'{}');calls.push({action,body});
    return route.fulfill({json:state});
   }
   if(!/^[\w.-]+$/.test(name)||!fs.existsSync(path.join(ui,name)))return route.abort();
   return route.fulfill({body:fs.readFileSync(path.join(ui,name)),contentType:name.endsWith('.js')?'application/javascript':name.endsWith('.css')?'text/css':'text/html'});
  });
  await page.goto('http://ssh-boot.test/index.html');await page.waitForFunction(()=>!document.querySelector('#installBoot').disabled);
  assert.equal(await page.locator('#bootService').textContent(),'已安装（当前版本）');
  await page.locator('#installBoot').click();await page.locator('#confirm[open]').waitFor();
  assert(await page.locator('#overwriteRow').isHidden());assert((await page.locator('#confirmText').textContent()).includes('与本插件一致'));
  const installed=page.waitForResponse(r=>new URL(r.url()).searchParams.get('action')==='install_boot');
  await page.locator('#confirm button[value=ok]').click();await installed;await page.waitForFunction(()=>!document.querySelector('#installBoot').disabled);
  assert.equal(calls.filter(x=>x.action==='install_boot').at(-1).body.overwrite,false);
  state={...state,bootService:{...state.bootService,current:false,conflicts:['restore-ssh.sh']}};
  await page.locator('#installBoot').click();await page.locator('#confirm[open]').waitFor();
  assert(await page.locator('#overwriteRow').isVisible());assert((await page.locator('#confirmText').textContent()).includes('restore-ssh.sh'));
  await page.locator('#confirm button[value=cancel]').click();assert.equal(calls.filter(x=>x.action==='install_boot').length,1);
  assert.deepEqual(errors,[]);console.log('PASS '+width+': current worker needs no override; genuine conflict is named');await context.close();
 }}finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
