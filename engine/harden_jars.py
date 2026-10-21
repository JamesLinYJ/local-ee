"""Remove actual vulnerable duplicate classes, then install locked replacements."""
import hashlib,json,shutil,zipfile,os
from pathlib import Path
fatroot=Path(os.environ.get('GEE_JARS','/opt/jars'));spark=Path(os.environ.get('GEE_SPARK_JARS','/usr/local/lib/python3.11/site-packages/pyspark/jars'));locked=Path(os.environ.get('GEE_SECURITY_JARS','/opt/security-jars'))
class_prefixes=('io/netty/','org/apache/log4j/','org/apache/logging/log4j/','org/apache/commons/compress/','org/sqlite/')
meta_prefixes=('META-INF/maven/io.netty/','META-INF/maven/log4j/','META-INF/maven/org.apache.logging.log4j/','META-INF/maven/org.apache.commons/commons-compress/','META-INF/maven/org.xerial/sqlite-jdbc/','META-INF/org/apache/logging/log4j/')
removed={}
for jar in fatroot.glob('*.jar'):
    temp=jar.with_suffix('.patched');names=[]
    with zipfile.ZipFile(jar) as src,zipfile.ZipFile(temp,'w',zipfile.ZIP_DEFLATED) as dst:
        for item in src.infolist():
            n=item.filename
            if n.startswith(class_prefixes+meta_prefixes) or (n.startswith('META-INF/versions/') and any('/'+p in n for p in class_prefixes)):
                names.append(n);continue
            if n.startswith('META-INF/') and n.upper().endswith(('.SF','.RSA','.DSA')):continue
            dst.writestr(item,src.read(n))
    temp.replace(jar);removed[jar.name]={'entries':len(names),'class_entries':sum(n.endswith('.class') for n in names)}
replacements={}
for item in json.loads(Path(os.environ.get('GEE_SECURITY_JAR_LOCK','/opt/security-jar-lock.json')).read_text()):
    p=locked/item['file']
    if hashlib.sha256(p.read_bytes()).hexdigest()!=item['sha256']:raise RuntimeError('Dependency digest mismatch: '+p.name)
    artifact=p.name.rsplit('-',1)[0] # versions containing hyphens are handled below
    for prefix in ['netty-','log4j-','commons-compress-','sqlite-jdbc-','bcprov-jdk18on-','jersey-client-','jersey-common-','lz4-java-']:
        if p.name.startswith(prefix):break
    # Netty and log4j families are removed once as whole families to avoid old optional native copies.
    replacements[p.name]=p
for p in list(spark.glob('*.jar')):
    if p.name.startswith(('netty-','log4j-','commons-compress-','sqlite-jdbc-','bcprov-jdk18on-','jersey-client-','jersey-common-','lz4-java-','derby','jackson-core-asl-','jackson-mapper-asl-')):
        p.unlink()
for name,p in replacements.items():shutil.copy2(p,spark/name)
# Spark Connect ships independent aggregated class copies and is not part of this local batch product.
connect=spark.parent/'python/lib'
for parent in [spark.parent]:
    for p in parent.rglob('connect-repl'):shutil.rmtree(p)
Path(os.environ.get('GEE_JAR_REPORT','/opt/jar-hardening.json')).write_text(json.dumps({'removed_fat_entries':removed,'replacement_jars':sorted(replacements)},indent=2))
print(json.dumps(removed))
