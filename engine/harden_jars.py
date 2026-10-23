"""Replace actual component code with verified, locked compatible artifacts."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import zipfile

REPLACED = ('netty-', 'log4j-', 'commons-compress-', 'sqlite-jdbc-',
            'bcprov-jdk18on-', 'jersey-client-', 'jersey-common-', 'lz4-java-',
            'jackson-core-', 'jackson-databind-', 'commons-lang3-', 'vertx-', 'jline-')
STRIPPED = [
    (('io/netty/', 'META-INF/native/libnetty'), ('META-INF/maven/io.netty/',)),
    (('org/apache/log4j/', 'org/apache/logging/log4j/'),
     ('META-INF/maven/log4j/', 'META-INF/maven/org.apache.logging.log4j/', 'META-INF/org/apache/logging/log4j/')),
    (('org/apache/commons/compress/',), ('META-INF/maven/org.apache.commons/commons-compress/',)),
    (('org/sqlite/',), ('META-INF/maven/org.xerial/sqlite-jdbc/',)),
]


def component_matches(name, prefixes):
    if name.startswith(prefixes):return True
    parts=name.split('/',3)
    return (len(parts)==4 and parts[:2]==['META-INF','versions'] and parts[2].isdigit()
            and parts[3].startswith(prefixes))


def class_matches(name, prefixes):
    return name.endswith('.class') and component_matches(name,prefixes)


def replacements(locked, manifest):
    result={};artifacts=set()
    for item in json.loads(Path(manifest).read_text()):
        name=item['file']
        match=re.fullmatch(r'(.+)-(\d[^/]*)\.jar',name)
        if (Path(name).name!=name or not name.startswith(REPLACED) or not match
                or name in result or match[1] in artifacts):
            raise ValueError('Invalid or duplicate replacement component')
        path=Path(locked)/name
        if hashlib.sha256(path.read_bytes()).hexdigest()!=item['sha256']:
            raise RuntimeError('Dependency digest mismatch: '+name)
        with zipfile.ZipFile(path) as source:
            if not any(entry.endswith('.class') for entry in source.namelist()):
                raise ValueError('Replacement has no component classes: '+name)
        artifacts.add(match[1]);result[name]=path
    return result


def strip_fat(jar):
    with zipfile.ZipFile(jar) as source:
        entries=source.infolist()
        active=[(classes,metadata) for classes,metadata in STRIPPED
                if any(component_matches(entry.filename,classes)
                       and entry.filename.endswith(('.class','.so','.dylib','.jnilib','.dll')) for entry in entries)]
        if not active:return {'entries':0,'class_entries':0}
        remove={entry.filename for entry in entries
                if any(component_matches(entry.filename,classes) or entry.filename.startswith(metadata)
                       for classes,metadata in active)}
        temporary=jar.with_suffix('.patched')
        try:
            with zipfile.ZipFile(temporary,'w',zipfile.ZIP_DEFLATED) as destination:
                for entry in entries:
                    name=entry.filename
                    if name in remove or (name.startswith('META-INF/') and name.upper().endswith(('.SF','.RSA','.DSA'))):continue
                    destination.writestr(entry,source.read(name))
            temporary.replace(jar)
        finally:temporary.unlink(missing_ok=True)
    return {'entries':len(remove),'class_entries':sum(name.endswith('.class') for name in remove)}


def harden(fatroot,spark,locked,manifest,report):
    # Validate the entire replacement set before mutating either runtime.
    verified=replacements(locked,manifest)
    removed={jar.name:strip_fat(jar) for jar in Path(fatroot).glob('*.jar')}
    spark=Path(spark)
    for path in list(spark.glob('*.jar')):
        if path.name.startswith((*REPLACED,'derby','jackson-core-asl-','jackson-mapper-asl-')):
            path.unlink()
    for name,path in verified.items():shutil.copy2(path,spark/name)
    # Spark Connect is not part of the local batch product.
    for path in spark.parent.rglob('connect-repl'):shutil.rmtree(path)
    value={'removed_fat_entries':removed,'replacement_jars':sorted(verified)}
    Path(report).write_text(json.dumps(value,indent=2)+'\n')
    return value


def main():
    print(json.dumps(harden(
        Path(os.environ.get('GEE_JARS','/opt/jars')),
        Path(os.environ.get('GEE_SPARK_JARS','/usr/local/lib/python3.11/site-packages/pyspark/jars')),
        Path(os.environ.get('GEE_SECURITY_JARS','/opt/security-jars')),
        Path(os.environ.get('GEE_SECURITY_JAR_LOCK','/opt/security-jar-lock.json')),
        Path(os.environ.get('GEE_JAR_REPORT','/opt/jar-hardening.json')))))


if __name__=='__main__':main()
