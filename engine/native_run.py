"""Native ARM64 GeoTrellis adapter, preserving upstream batch evaluation."""
import hashlib
import json
import os
import sys
from pathlib import Path


def setup(log_dir):
    from geopyspark import geopyspark_conf
    from pyspark import SparkContext
    from openeogeotrellis import deploy
    deploy.load_custom_processes()
    jars = Path(os.environ['GEOPYSPARK_JARS_PATH'])
    conf = geopyspark_conf(master='local[1]',appName='private-gee-native')
    paths = conf.get('spark.jars').split(',')
    adapter = jars/'local-ee-integer-adapter.jar'
    if adapter.exists():
        manifest = json.loads(adapter.with_suffix('.jar.manifest.json').read_text())
        if hashlib.sha256(adapter.read_bytes()).hexdigest() != manifest['jar_sha256']:
            raise RuntimeError('Local EE adapter checksum mismatch; rebuild the native adapter')
        if str(adapter) not in paths:
            paths.append(str(adapter))
    paths.sort(key=lambda p:'geotrellis-extensions' not in p and 'geotrellis-dependencies' not in p)
    # local[1] shares one JVM. Use its classpath instead of serving/copying JARs
    # through Spark's network FileServer (Darwin sendfile needs broader rights).
    conf.set('spark.jars','')
    extra = ':'.join(paths)
    log4j = Path(__file__).parent/'log4j2.xml'
    for key,value in {
        'spark.sql.session.timeZone':'UTC','spark.kryoserializer.buffer.max':'512m',
        'spark.kryo.registrator':'geotrellis.spark.store.kryo.KryoRegistrator',
        'spark.kryo.classesToRegister':'ar.com.hjg.pngj.ImageInfo,ar.com.hjg.pngj.ImageLineInt,geotrellis.raster.RasterRegion$GridBoundsRasterRegion',
        'spark.driver.memory':'1g','spark.executor.memory':'1g',
        'spark.ui.enabled':'false','spark.ui.showConsoleProgress':'false',
        'spark.driver.host':'127.0.0.1','spark.driver.bindAddress':'127.0.0.1',
        'spark.local.dir':str(log_dir/'spark'),
        'spark.driver.extraClassPath':extra,'spark.executor.extraClassPath':extra,
        'spark.driver.extraJavaOptions':f'-Dlog4j2.configurationFile=file:{log4j} -Djna.library.path=/opt/homebrew/opt/netcdf/lib -Dscala.concurrent.context.numThreads=1 -Djava.io.tmpdir={log_dir} -Dgeotrellis.jts.precision.type=fixed -Dgeotrellis.jts.simplification.scale=1e10',
        'spark.executor.extraJavaOptions':f'-Dlog4j2.configurationFile=file:{log4j} -Dscala.concurrent.context.numThreads=1',
    }.items():
        conf.set(key,value)
    SparkContext.getOrCreate(conf).setLogLevel('WARN')
    os.environ['PYTEST_CONFIGURE']=''


def run(job):
    os.umask(0o077)
    from openeogeotrellis.deploy import run_graph_locally as runner
    runner.setup_environment=setup
    output=job/'out'
    try:
        runner.run_graph_locally(json.loads((job/'graph.json').read_text()),output)
    finally:
        for path in output.rglob('*'):
            if path.is_file() and not path.is_symlink():
                path.chmod(0o640)


if __name__=='__main__':
    run(Path(sys.argv[1]))
