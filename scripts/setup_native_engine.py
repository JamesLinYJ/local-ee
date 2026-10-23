"""Build the pinned GeoTrellis/JEP/GDAL bridge for native macOS ARM64."""
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
NATIVE=ROOT/'.native'


def run(args,**kwargs):
    subprocess.run([str(a) for a in args],check=True,cwd=ROOT,**kwargs)


def main():
    if platform.system()!='Darwin' or platform.machine()!='arm64':
        raise SystemExit('This build profile requires native Apple Silicon macOS')
    NATIVE.mkdir(exist_ok=True,mode=0o700)
    from gee.native.toolchains import selected
    java=Path(selected(ROOT)['java_home'])
    env={**os.environ,'JAVA_HOME':str(java),'PATH':str(java/'bin')+':/opt/homebrew/bin:'+os.environ['PATH']}
    python=NATIVE/'engine/bin/python'
    if not python.exists():run(['uv','venv','--python',ROOT/'.venv/bin/python',NATIVE/'engine'])
    pip=['uv','pip','install','--python',python]
    run([*pip,'numpy==2.3.3','setuptools==69.5.1','wheel==0.46.3','Cython==3.0.12','pkgconfig==1.5.5'],env=env)
    run([*pip,'--no-build-isolation',ROOT/'vendor/jep'],env=env)
    run([*pip,'setuptools==80.9.0','Cython==3.1.6'],env=env)
    # Adapt build metadata in a private copy; the pinned upstream source remains untouched.
    source=NATIVE/'sources/geopyspark-driver'
    if source.exists():shutil.rmtree(source)
    shutil.copytree(ROOT/'vendor/openeo-geopyspark-driver',source,ignore=shutil.ignore_patterns('.git','__pycache__'))
    setup=source/'setup.py';text=setup.read_text()
    replacements={'jep_openeo_numpy==4.1.2':'jep==4.1.1','h5py~=3.11.0':'h5py==3.15.1',
                  'protobuf~=3.9.2':'protobuf==5.29.6','elasticsearch==7.16.3':'elasticsearch==7.17.13',
                  'rasterio~=1.3.10':'rasterio==1.4.4'}
    for old,new in replacements.items():
        if old not in text:raise RuntimeError('Upstream metadata changed: '+old)
        text=text.replace(old,new)
    setup.write_text(text)
    run([*pip,'--no-build-isolation','--no-binary','rasterio',ROOT/'vendor/geopyspark',ROOT/'vendor/openeo-python-driver',source,'pyspark==4.2.0','urllib3==2.8.0'],env=env)
    version=subprocess.check_output(['/opt/homebrew/bin/gdal-config','--version'],text=True).strip()
    run([*pip,'--no-build-isolation','GDAL=='+version],env=env)
    bridge=NATIVE/'sources/gdal-warp-bindings'
    if bridge.exists():shutil.rmtree(bridge)
    shutil.copytree(ROOT/'vendor/gdal-warp-bindings',bridge,ignore=shutil.ignore_patterns('.git','*.o','*.class','*.so'))
    src=bridge/'src'
    for name in ['locked_dataset.hpp','bindings.cpp','bindings.h']:
        p=src/name;p.write_text(p.read_text().replace('const char *domain, char ***list','const char *domain, const char *const **list'))
    p=src/'com_azavea_gdal_GDALWarp.c';p.write_text(p.read_text().replace('char **list = NULL;','const char *const *list = NULL;'))
    p=src/'main/java/com/azavea/gdal/GDALWarp.java';text=p.read_text()
    text=text.replace('NativeUtils.loadLibraryFromJar(GDALWARP_BINDINGS_RESOURCE_AMD64_MACHO);',
                      'NativeUtils.loadLibraryFromJar(arch.contains("aarch64") || arch.contains("arm64") ? "/resources/libgdalwarp_bindings-arm64.dylib" : GDALWARP_BINDINGS_RESOURCE_AMD64_MACHO);')
    p.write_text(text)
    run(['make','-C',src,'-j2','JAVA_HOME='+str(java),'OS=darwin','SO=dylib','ARCH=arm64',
         'BOOST_ROOT=/opt/homebrew/include','CFLAGS=-O2 -fPIC','CXXFLAGS=-std=c++17 -include utility',
         'LDFLAGS=-L/opt/homebrew/lib -lgdal -lc++ -lpthread','libgdalwarp_bindings-arm64.dylib'],env=env)
    jars=NATIVE/'jars';jars.mkdir(exist_ok=True)
    for item in json.loads((ROOT/'engine/jars-lock.json').read_text()):
        jar=ROOT/'engine/jars'/item['file'];digest=hashlib.sha256()
        with jar.open('rb') as stream:
            while chunk:=stream.read(1024*1024):digest.update(chunk)
        if digest.hexdigest()!=item['sha256']:raise RuntimeError('Upstream JAR checksum mismatch: '+jar.name)
        shutil.copy2(jar,jars/jar.name)
    resources=src/'main/resources';resources.mkdir(exist_ok=True)
    shutil.copy2(src/'libgdalwarp_bindings-arm64.dylib',resources)
    dependency=next(jars.glob('geotrellis-dependencies*.jar'))
    run([java/'bin/jar','uf',dependency,'-C',src/'main','resources/libgdalwarp_bindings-arm64.dylib',
         '-C',src/'main/java','com/azavea/gdal/GDALWarp.class'],env=env)
    spark=NATIVE/'engine/lib/python3.11/site-packages/pyspark/jars'
    for jar in spark.glob('spire*'):jar.unlink()
    hardening={**env,'GEE_JARS':str(jars),'GEE_SPARK_JARS':str(spark),
               'GEE_SECURITY_JARS':str(ROOT/'engine/security-jars'),'GEE_SECURITY_JAR_LOCK':str(ROOT/'engine/security-jar-lock.json'),
               'GEE_JAR_REPORT':str(NATIVE/'jar-hardening.json')}
    run([python,ROOT/'engine/harden_jars.py'],env=hardening)
    run([python,'-m','engine.rebuild_shaded','--fatroot',jars,'--spark',spark,
         '--buildroot',ROOT/'engine/security-build-jars','--directroot',ROOT/'engine/security-jars',
         '--java',java/'bin/java','--report',NATIVE/'shaded-hardening.json'],env={**env,'PYTHONPATH':str(ROOT)})
    run([*pip,'setuptools==84.2.1'],env=env)
    with (NATIVE/'engine-requirements.lock').open('w') as out:
        run(['uv','pip','freeze','--python',python],stdout=out)
    record={'platform':platform.platform(),'architecture':platform.machine(),'java_home':str(java),
            'spark':'4.2.0','gdal':version,'metadata_adaptations':replacements,
            'jni_adaptation':'Darwin arm64 resource dispatch; GDAL const metadata pointers; C++17 libc++',
            'jars':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in jars.glob('*.jar') if not p.name.startswith('local-ee-')}}
    (NATIVE/'engine-lock.json').write_text(json.dumps(record,indent=2)+'\n')
    # Local SPI extensions have their own source/artifact manifests. They are
    # not upstream downloads and must never enter engine/jars-lock.json.
    run([sys.executable,ROOT/'scripts/build_integer_adapter.py','--output',jars/'local-ee-integer-adapter.jar'],env=env)
    print('Native engine built; no VM or container used.')


if __name__=='__main__':main()
