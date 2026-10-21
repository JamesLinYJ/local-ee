"""Offline compiler audit. Run with project .venv/bin/python and PYTHONPATH=.

The catalogue is synthetic metadata only. No jobs, DB, or science engine run.
Node probes run under native Seatbelt with no network or credential environment.
Use a fresh --output directory; existing evidence is never overwritten.
"""
from pathlib import Path
import argparse, datetime, hashlib, json, os, shutil, subprocess, sys

from gee.ee_translate import compile_expression, SUPPORTED_FUNCTIONS, UnsupportedEEError
from gee.native.sandbox import profile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    output = Path(parser.parse_args().output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    node = Path(shutil.which('node')).resolve()
    env = {'PATH': str(node.parent)+':/usr/bin:/bin', 'HOME': str(output),
           'TMPDIR': str(output), 'LANG': 'en_US.UTF-8'}
    reads = [ROOT/'vendor/earthengine-js', HERE, ROOT/'.native/eejs', Path('/opt/homebrew/Cellar')]
    policy = profile(reads=reads, writes=[output])
    def run(args):
        return subprocess.run(['/usr/bin/sandbox-exec', '-p', policy, str(node), *map(str,args)],
                              env=env, capture_output=True, text=True, timeout=30)
    generated = run([HERE/'probes.cjs'])
    if generated.returncode:
        raise RuntimeError(generated.stderr[:2000])
    fixtures = json.loads(generated.stdout)
    (output/'expressions.json').write_text(json.dumps(fixtures,indent=2)+'\n')
    catalog = [{'id':'sentinel-2-l2a','cube:dimensions':{'bands':{'values':['blue','green','red','nir','SCL']}}}]
    def members(count):
        return {'sentinel-2-l2a':[
            {'id':f'probe-{i:04d}', 'bbox':[0,0,2,2],
             'geometry':{'type':'Polygon','coordinates':[[[0,0],[2,0],[2,2],[0,2],[0,0]]]},
             'properties':{'system:time_start':1704067200000+i*86400000,
                           'system:index':f'probe-{i:04d}','CLOUDY_PIXEL_PERCENTAGE':i%100}}
            for i in range(count)]}
    def calls(value):
        if isinstance(value,dict):
            names = {value['functionName']} if 'functionName' in value else set()
            return names.union(*(calls(v) for v in value.values()))
        if isinstance(value,list):
            return set().union(*(calls(v) for v in value))
        return set()
    def compile_case(case,count):
        rec = {k:v for k,v in case.items() if k!='expression'}
        rec['fixture_scenes']=count
        if not case['sdk_serialized']:return rec
        names=calls(case['expression']);rec['serialized_functions']=sorted(names)
        rec['outside_declared_handler_inventory']=sorted(names-SUPPORTED_FUNCTIONS)
        try:
            compiled=compile_expression(case['expression'],catalog,members(count))
            rec.update(compiled=True,kind=compiled['kind'],graph_nodes=len(compiled.get('process_graph',{})))
            if compiled['kind']=='value':rec['value']=compiled['value']
        except UnsupportedEEError as error:
            rec.update(compiled=False,error=str(error))
        return rec
    results=[compile_case(case,3) for case in fixtures if case['workflow']!='scale']
    scale=[compile_case(case,count) for case in fixtures if case['workflow']=='scale'
           for count in (1,10,20,30,50,100,365)]
    runtime=[]
    for name,source in {
        'ui_panel':"ui.Panel({widgets: [ui.Label('Audit')]});\n",
        'ui_chart':"ui.Chart.image.series({imageCollection: ee.ImageCollection('sentinel-2-l2a'), region: ee.Geometry.Point([0,0]), scale: 10});\n",
        'gee_users_require':"require('users/emaprlab/public:Modules/LandTrendr.js');\n",
    }.items():
        file=output/(name+'.js');file.write_text(source)
        result=run([ROOT/'.native/eejs/runner.cjs',file])
        runtime.append({'id':name,'returncode':result.returncode,'stderr':result.stderr[:3000],
                        'network_allowed':False})
    summary={'sampled_at':datetime.datetime.now().astimezone().isoformat(),
             'sdk':'1.7.49','backend_sha256':hashlib.sha256((ROOT/'gee/ee_translate.py').read_bytes()).hexdigest(),
             'scope':'Source inspection plus isolated official-SDK serialization and local compilation; no original full workflow or Google-service numerical acceptance',
             'data':'Synthetic local metadata used to remove missing remote datasets as the first blocker',
             'array_probe_limitation':'Placeholder Image inputs isolate handler absence, not array shape/type/numerical validity',
             'probes':results,'scale_probes':scale,'runtime_probes':runtime}
    summary['harness_validated']=all(r['sdk_serialized'] for r in results+scale) and all(
        r.get('compiled') for r in results if r['workflow']=='control')
    (output/'validation.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    for rec in results:print(rec['id'], 'COMPILED' if rec.get('compiled') else rec.get('error'))
    for rec in scale:print('SCALE',rec['id'],rec['fixture_scenes'],rec.get('graph_nodes'),rec.get('error',''))
    for rec in runtime:print('RUNTIME',rec['id'],rec['returncode'],rec['stderr'].splitlines()[0:4])
    assert summary['harness_validated'], 'Audit harness serialization/positive controls failed'


if __name__=='__main__':main()
