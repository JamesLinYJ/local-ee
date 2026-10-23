"""Rebuild the native-only Spark 4.2 profile from checksum-verified real code."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

from engine.jar_relocation import entries, finish, merge, relocated, remove, write

ROOT = Path(__file__).resolve().parents[1]
JETTY_MODULES = ('jetty-security', 'jetty-util', 'jetty-server', 'jetty-io', 'jetty-http',
                 'jetty-session', 'jetty-client', 'jetty-ee10-plus', 'jetty-ee10-servlet',
                 'jetty-ee10-proxy', 'jetty-ee10-servlets', 'jetty-compression-server',
                 'jetty-compression-common', 'jetty-compression-gzip')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def inputs(buildroot, directroot):
    result = {}
    for directory, manifest in [(buildroot, 'security-build-downloads.json'), (directroot, 'security-downloads.json')]:
        for item in json.loads((ROOT/'engine'/manifest).read_text()):
            path = Path(directory)/item['file']
            if path.name != item['file'] or digest(path) != item['sha256']:
                raise RuntimeError('Build input digest mismatch: '+item['file'])
            result[item['file']] = path
    return result


def replace_component(values, source, original, target, metadata, tool, java, *, package=None):
    metadata = 'META-INF/maven/'+metadata+'/'
    service = {'core':'core.JsonFactory', 'databind':'core.ObjectCodec'}.get(package)
    old_services = ['META-INF/services/'+prefix+'.'+service for prefix in
                    (original.replace('/', '.'), target.replace('/', '.'))] if service else []
    removed = remove(values, (target+'/'+package+'/' if package else target+'/',), (metadata,), old_services)
    if original == 'org/apache/commons/configuration2':
        # This DTD is a Configuration2-owned root resource outside its package.
        removed += remove(values, services=('PropertyList-1.0.dtd', 'properties.dtd'))
    context = dict(rules_original='org/apache/commons', rules_target='org/apache/hadoop/shaded/org/apache/commons',
                   preserve=('org/apache/commons/logging',)) if original.startswith('org/apache/commons/') else {}
    new = relocated(source, original, target, tool=tool, java=java, **context)
    merge(values, new, source.stem)
    return dict(source=source.name, sha256=digest(source), removed_entries=len(removed),
                replacement_classes=sum(name.endswith('.class') for name in new))


def patch_storage(jar, sources, lang3, java):
    """Compile the original Hive class with real Lang3 API descriptors."""
    source_name = 'org/apache/hadoop/hive/common/ValidReadTxnList.java'
    original = entries(sources)[source_name].decode('utf-8')
    source = original.replace('org.apache.commons.lang.', 'org.apache.commons.lang3.')
    if source == original or source.count('org.apache.commons.lang3.') != 2:
        raise RuntimeError('Unexpected Hive storage source imports')
    with tempfile.TemporaryDirectory(prefix='local-ee-hive-storage-') as temporary:
        temporary = Path(temporary)
        source_path = temporary/source_name
        source_path.parent.mkdir(parents=True)
        source_path.write_text(source)
        classes = temporary/'classes'; classes.mkdir()
        subprocess.run([str(Path(java).with_name('javac')), '--release', '8',
                        '-classpath', str(jar)+':'+str(lang3), '-d', str(classes), str(source_path)],
                       check=True, capture_output=True, timeout=90)
        values = entries(jar)
        compiled = list(classes.rglob('*.class'))
        if len(compiled) != 1: raise RuntimeError('Unexpected Hive patch class output')
        values[str(compiled[0].relative_to(classes))] = compiled[0].read_bytes()
        values['META-INF/local-ee/patches/hive-storage-lang3.json'] = json.dumps(dict(
            source_artifact=sources.name, source_artifact_sha256=digest(sources), source=source_name,
            original_sha256=hashlib.sha256(original.encode()).hexdigest(),
            patched_sha256=hashlib.sha256(source.encode()).hexdigest(),
            change='Only Commons Lang2 imports replaced with Lang3; compiled against actual API.'
        ), sort_keys=True).encode()
        finish(values); write(jar, values)


def rebuild(fatroot, spark, buildroot, directroot, java, report):
    spark, fatroot = Path(spark), Path(fatroot)
    verified = inputs(buildroot, directroot)
    tool = verified['jarjar-assembly-1.18.1.jar']
    profile = json.loads((ROOT/'engine/security-runtime-profile.json').read_text())
    # Validate all upstream Spark assemblies before modifying any of them.
    for name, expected in profile['upstream_assemblies'].items():
        if digest(spark/name) != expected: raise RuntimeError('Unexpected upstream assembly: '+name)
    changes = {}
    for name, target in [('hadoop-client-runtime-3.5.0.jar', 'org/apache/hadoop/shaded/com/fasterxml/jackson'),
                         ('parquet-jackson-1.17.0.jar', 'shaded/parquet/com/fasterxml/jackson')]:
        path = spark/name; values = entries(path); details = []
        hadoop = name.startswith('hadoop')
        for module, package, version in [('core', 'core', '2.18.12' if hadoop else '2.21.7'),
                                         ('databind', 'databind', '2.18.12' if hadoop else '2.21.7'),
                                         ('annotations', 'annotation', '2.18.6' if hadoop else '2.21')]:
            details.append(replace_component(values, verified[f'jackson-{module}-{version}.jar'],
                'com/fasterxml/jackson', target,
                'com.fasterxml.jackson.core/jackson-'+module, tool, java, package=package))
        if name.startswith('hadoop'):
            for source, original, metadata in [
                ('commons-configuration2-2.15.1.jar', 'org/apache/commons/configuration2', 'org.apache.commons/commons-configuration2'),
                ('commons-lang3-3.21.0.jar', 'org/apache/commons/lang3', 'org.apache.commons/commons-lang3')]:
                details.append(replace_component(values, verified[source], original,
                    'org/apache/hadoop/shaded/'+original, metadata, tool, java))
            removed = remove(values, ('org/apache/hadoop/shaded/org/eclipse/jetty/', 'org/apache/hadoop/shaded/org/jline/'),
                ('META-INF/maven/org.eclipse.jetty/', 'META-INF/maven/org.eclipse.jetty.websocket/', 'META-INF/maven/org.jline/'),
                tuple(n for n in values if n.startswith('META-INF/services/') and ('jetty' in n or 'jline' in n)))
            details.append(dict(excluded='Hadoop HTTP/YARN interactive components', removed_entries=len(removed)))
        finish(values); write(path, values); changes[name] = details
    path = spark/'spark-core_2.13-4.2.0.jar'; values = entries(path)
    removed = remove(values, ('org/sparkproject/jetty/',),
        ('META-INF/maven/org.eclipse.jetty/', 'META-INF/maven/org.eclipse.jetty.ee10/', 'META-INF/maven/org.eclipse.jetty.compression/'),
        tuple(n for n in values if n.startswith('META-INF/services/') and 'jetty' in n))
    for module in JETTY_MODULES:
        source = verified[module+'-12.1.14.jar']
        merge(values, relocated(source, 'org/eclipse/jetty', 'org/sparkproject/jetty', tool=tool, java=java), source.stem)
    finish(values); write(path, values)
    changes[path.name] = dict(removed_entries=len(removed), modules=list(JETTY_MODULES), version='12.1.14')
    path = spark/'hive-storage-api-2.8.1.jar'
    patch_storage(path, verified['hive-storage-api-2.8.1-sources.jar'], verified['commons-lang3-3.21.0.jar'], java)
    excluded = []
    for path in spark.glob('*.jar'):
        if ((path.name.startswith('hive-') and not path.name.startswith('hive-storage-api-'))
                or path.name.startswith(('spark-hive', 'libthrift-', 'libfb303-', 'commons-lang-', 'spire'))):
            excluded.append(path.name); path.unlink()
    # Keep CatBoost's real types: the upstream process builder declares them in
    # method signatures and Py4J resolves those even for ordinary reductions.
    # CatBoost algorithms remain outside the product's process allowlist.
    value = dict(profile='native-spark-4.2-v1', changes=changes, excluded_jars=sorted(excluded),
                 outputs={path.name:digest(path) for path in [*spark.glob('*.jar'), *fatroot.glob('*.jar')]})
    Path(report).write_text(json.dumps(value, indent=2)+'\n')
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('fatroot', 'spark', 'buildroot', 'directroot', 'java', 'report'):
        parser.add_argument('--'+name, required=True, type=Path)
    args = parser.parse_args()
    rebuild(**vars(args))


if __name__ == '__main__': main()
