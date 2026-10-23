'use strict';
// Local-only HTTP transport used by the script's bounded bridge thread.
const api = new URL(process.env.OPENEO_URL || 'http://api:8080/openeo/1.2');
if (!['api','localhost','127.0.0.1'].includes(api.hostname) || !['http:','https:'].includes(api.protocol)) throw Error('Invalid local API destination');
const token = process.env.OPENEO_TOKEN;
const root = new URL('/gee/v1/dispatch', api);
async function request(payload) {
  const response = await fetch(root, {method:'POST',headers:{'Content-Type':'application/json','Authorization':'Bearer basic//'+token},body:JSON.stringify(payload),redirect:'error',signal:AbortSignal.timeout(105000)});
  const result = await response.json();
  if (!response.ok) throw Error(result.message || result.error || `Local API ${response.status}`);
  if(payload.action==='evaluate' && result.pending){
    const deadline=Date.now()+100000;
    while(Date.now()<deadline){
      await new Promise(resolve=>setTimeout(resolve,1000));
      const next=await request({action:'result',job_id:result.job_id});
      if(!next.pending)return {...next,warnings:result.warnings||[]};
    }
    throw Error('Local evaluation is still queued/running; inspect the batch task '+result.job_id);
  }
  return result;
}
if (require.main === module) {
  let input='';
  process.stdin.setEncoding('utf8');process.stdin.on('data',s=>{input+=s;if(input.length>1048576)process.exit(2);});
  process.stdin.on('end',()=>request(JSON.parse(input)).then(value=>process.stdout.write(JSON.stringify({ok:true,value}))).catch(error=>{process.stdout.write(JSON.stringify({ok:false,error:error.message}));process.exitCode=1;}));
}
module.exports={request};
