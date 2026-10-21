import argparse
import hashlib
import json
import os
import time
import shutil
import uuid
from datetime import date
from pathlib import Path
from urllib.parse import urlparse
import requests
import yaml
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from . import db,auth
from .ingest import optical_item,ROOT,sha256,IngestBudget

ALLOWED={'earth-search.aws.element84.com','sentinel-cogs.s3.us-west-2.amazonaws.com',
         'e84-earth-search-sentinel-data.s3.us-west-2.amazonaws.com',
         'planetarycomputer.microsoft.com','landsateuwest.blob.core.windows.net',
         'copdem30m.blob.core.windows.net','cds.climate.copernicus.eu','object-store.os-api.cci2.ecmwf.int'}

def checked(url):
    parsed=urlparse(url)
    if len(url)>8192 or parsed.scheme!='https' or parsed.hostname not in ALLOWED or parsed.username or parsed.password or parsed.port not in {None,443}:
        raise ValueError('供应方地址未在白名单: '+str(parsed.hostname))
    return url

def session():
    s=requests.Session();s.mount('https://',HTTPAdapter(max_retries=Retry(total=3,backoff_factor=2,status_forcelist=[429,500,502,503,504],allowed_methods=['GET','POST','HEAD'])))
    return s

def response_json(response, max_bytes=8*1024*1024, deadline=None):
    """Bound decoded response bytes before JSON deserialization."""
    try:
        response.raise_for_status()
        if response.is_redirect:raise ValueError('Redirect not permitted')
        length=response.headers.get('Content-Length')
        if length and int(length)>max_bytes:raise ValueError('Provider JSON exceeds byte limit')
        data=bytearray()
        for chunk in response.iter_content(65536):
            if deadline is not None and time.monotonic()>deadline:raise ValueError('Sync deadline exceeded')
            if len(data)+len(chunk)>max_bytes:raise ValueError('Provider JSON exceeds byte limit')
            data.extend(chunk)
        return json.loads(data)
    finally:response.close()

def download(url,target,expected_sha=None,max_bytes=512*1024*1024):
    """Resumable download; require stable ETag before appending, validate size/hash."""
    checked(url);target=Path(target);partial=target.with_suffix(target.suffix+'.part');tagfile=partial.with_suffix('.etag')
    s=session();head=s.head(url,timeout=30,allow_redirects=False);head.raise_for_status()
    if head.is_redirect: raise ValueError('Redirect must be explicitly reviewed')
    length=head.headers.get('Content-Length')
    if length and int(length)>max_bytes:raise ValueError('Provider download exceeds byte limit')
    if shutil.disk_usage(target.parent).free < max_bytes+128*1024*1024:raise ValueError('Insufficient staging space')
    deadline=time.monotonic()+1800
    etag=head.headers.get('ETag');offset=partial.stat().st_size if partial.exists() else 0
    if not etag or not tagfile.exists() or tagfile.read_text()!=etag:
        offset=0
    if offset>max_bytes:partial.unlink();offset=0
    headers={'Range':f'bytes={offset}-','If-Range':etag} if offset else {}
    with s.get(url,headers=headers,stream=True,timeout=(30,120),allow_redirects=False) as r:
        r.raise_for_status()
        if r.is_redirect: raise ValueError('Redirect must be explicitly reviewed')
        if offset and (r.status_code!=206 or not r.headers.get('Content-Range','').startswith(f'bytes {offset}-')): offset=0
        tagfile.write_text(etag or '')
        with open(partial,'ab' if offset else 'wb') as f:
            for chunk in r.iter_content(1024*1024):
                if time.monotonic()>deadline:raise ValueError('Download deadline exceeded')
                if f.tell()+len(chunk)>max_bytes:raise ValueError('Provider download exceeds byte limit')
                f.write(chunk)
    length=head.headers.get('Content-Length')
    if length and partial.stat().st_size!=int(length): raise ValueError('下载长度校验失败')
    digest=sha256(partial)
    if expected_sha and digest!=expected_sha: raise ValueError('SHA256 校验失败')
    partial.replace(target);return digest

def sync_optical(cid,config,page_size,max_items=10000):
    s=session();budget=IngestBudget();pc=cid!='sentinel-2-l2a'
    base='https://planetarycomputer.microsoft.com/api/stac/v1' if pc else 'https://earth-search.aws.element84.com/v1'
    query={'collections':['sentinel-2-c1-l2a' if cid=='sentinel-2-l2a' else cid],'bbox':config['bbox'],'limit':min(page_size,100)}
    end=date.today().isoformat() if config['end']=='today' else str(config['end'])
    if cid!='cop-dem-glo-30':query['datetime']=str(config['start'])+'T00:00:00Z/'+end+'T23:59:59Z'
    if cid=='sentinel-2-l2a':query['query']={'eo:cloud_cover':{'lt':config.get('cloud_cover_max',30)}}
    def sign(url):
        checked(url)
        if not pc:return url
        response=s.get(checked('https://planetarycomputer.microsoft.com/api/sas/v1/sign'),params={'href':url},timeout=30,stream=True,allow_redirects=False)
        return checked(response_json(response,max_bytes=65536,deadline=deadline)['href'])
    link={'href':base+'/search','method':'POST','body':query};seen=set();count=0;pages=0
    deadline=time.monotonic()+1800
    while link:
        pages+=1
        if pages>1000 or time.monotonic()>deadline:raise ValueError('Sync page/deadline limit exceeded')
        url=checked(link['href'])
        if urlparse(url).hostname!=urlparse(base).hostname:raise ValueError('Unexpected STAC pagination host')
        key=hashlib.sha256(json.dumps(link,sort_keys=True).encode()).digest()
        if key in seen:raise ValueError('STAC pagination cycle')
        seen.add(key)
        method=link.get('method','GET').upper()
        if method not in {'GET','POST'}:raise ValueError('Unexpected pagination method')
        response=s.request(method,url,json=link.get('body') if method=='POST' else None,timeout=(10,60),allow_redirects=False,stream=True)
        result=response_json(response,deadline=deadline)
        if not isinstance(result,dict) or not isinstance(result.get('features',[]),list):raise ValueError('Invalid STAC response')
        for item in result.get('features',[]):
            if time.monotonic()>deadline:raise ValueError('Sync deadline exceeded')
            if count>=max_items:raise ValueError('同步达到 max_items 安全上限；缩小时间范围或调高上限后重试，已入库数据保留')
            optical_item(item,cid,config['bbox'],sign=sign,budget=budget);count+=1
        link=next((l for l in result.get('links',[]) if l.get('rel')=='next'),None)
        if link and link.get('merge'):
            link={**link,'body':{**query,**link.get('body',{})}}
    return count

def run(config):
    if not db.query("SELECT to_regclass('public.sync_runs') AS table_name",one=True)['table_name']:raise RuntimeError('Initialize schema through API before sync')
    ROOT.mkdir(parents=True,exist_ok=True)
    for source,settings in config['sources'].items():
        if not settings.get('enabled'):continue
        rid=str(uuid.uuid4());db.query("INSERT INTO sync_runs(id,source,status) VALUES(%s,%s,'running')",(rid,source))
        try:
            if source=='era5-land':
                from .climate import retrieve
                count=retrieve(config,settings)
            else:count=sync_optical(source,config,int(settings.get('page_size',settings.get('limit',100))),int(settings.get('max_items',10000)))
            db.query("UPDATE sync_runs SET status='finished',finished=now(),message=%s WHERE id=%s",(f'Processed {count} item(s)',rid))
        except Exception as e:
            db.query("UPDATE sync_runs SET status='error',finished=now(),message=%s WHERE id=%s",(auth.redact(str(e))[:1500],rid))
            raise

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--config',default='/app/deploy/sync.yaml');p.add_argument('--once',action='store_true');args=p.parse_args()
    while True:
        config=yaml.safe_load(Path(args.config).read_text())
        try:run(config)
        except Exception as e:
            print(auth.redact(str(e)),flush=True)
            if args.once:raise SystemExit(1)
        if args.once:break
        time.sleep(float(config.get('interval_hours',24))*3600)
