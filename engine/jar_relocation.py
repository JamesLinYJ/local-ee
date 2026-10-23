"""Deterministic assembly of real shaded classes, services and origin metadata.

Jar Jar (pinned separately) rewrites JVM bytecode using ASM. This module handles
resource names and retains each replacement's original Maven and license data.
It never rewrites version metadata to claim that old code is a newer component.
"""
from pathlib import Path
import re
import subprocess
import tempfile
import zipfile


def entries(path):
    with zipfile.ZipFile(path) as source:
        names = source.namelist()
        if len(names) != len(set(names)):
            raise ValueError('Duplicate ZIP member: '+str(path))
        return {entry.filename: source.read(entry) for entry in source.infolist() if not entry.is_dir()}


def write(path, values):
    path = Path(path)
    temporary = path.with_suffix('.assembling')
    try:
        with zipfile.ZipFile(temporary, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as out:
            for name, content in sorted(values.items()):
                entry = zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
                entry.compress_type = zipfile.ZIP_DEFLATED
                entry.external_attr = 0o100644 << 16
                out.writestr(entry, content)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def under(name, prefix):
    return name.startswith(prefix) or bool(re.match(r'META-INF/versions/\d+/'+re.escape(prefix), name))


def remove(values, prefixes=(), metadata=(), services=()):
    """Remove whole actual component families together with their registration."""
    removed = []
    for name in list(values):
        if (any(under(name, prefix) for prefix in prefixes) or name.startswith(metadata)
                or name in services):
            removed.append(name)
            del values[name]
    return removed


def remap_resource(value, mappings):
    for old, new in mappings:
        # Jar Jar may already have relocated this resource or provider string.
        value = value.replace(new, '\x00').replace(old, new).replace('\x00', new)
    return value


def relocated(source, original, target, *, tool, java, rules_original=None, rules_target=None, preserve=()):
    """Return one fully relocated component without its standalone module descriptor."""
    original, target = original.rstrip('/'), target.rstrip('/')
    rules_original = rules_original or original
    rules_target = rules_target or target
    mappings = [(original+'/', target+'/'), (original.replace('/', '.')+'.', target.replace('/', '.')+'.')]
    with tempfile.TemporaryDirectory(prefix='local-ee-relocate-') as directory:
        directory = Path(directory)
        rules = directory/'rules.txt'
        rules.write_text(''.join(f'rule {prefix.replace("/", ".")}.** {prefix.replace("/", ".")}.@1\n' for prefix in preserve)
                         + f'rule {rules_original.replace("/", ".")}.** {rules_target.replace("/", ".")}.@1\n')
        output = directory/'relocated.jar'
        subprocess.run([str(java), '-jar', str(tool), 'process', str(rules), str(source), str(output)],
                       check=True, capture_output=True, timeout=90)
        transformed = entries(output)
    result = {}
    for name, content in transformed.items():
        if name.endswith('module-info.class') or name == 'META-INF/MANIFEST.MF': continue
        if name.startswith('META-INF/') and name.upper().endswith(('.SF', '.RSA', '.DSA')): continue
        if name.startswith('META-INF/maven/'):
            result[name] = content
            continue
        if name.startswith('META-INF/services/'):
            name = remap_resource(name, mappings)
            content = remap_resource(content.decode('utf-8'), mappings).encode('utf-8')
        elif not name.endswith('.class'):
            name = remap_resource(name, mappings)
            if name.endswith(('.properties', '.xml', '.json')):
                content = remap_resource(content.decode('utf-8'), mappings).encode('utf-8')
        if name.endswith('.class') and not under(name, target+'/'):
            raise ValueError('Unrelocated component class: '+name)
        if name in result: raise ValueError('Relocation resource collision: '+name)
        result[name] = content
    expected = sum(name.endswith('.class') and not name.endswith('module-info.class') for name in entries(source))
    actual = sum(name.endswith('.class') for name in result)
    if expected != actual: raise ValueError('Relocation lost component classes')
    return result


def merge(values, component, label):
    for name, content in component.items():
        if name.startswith('META-INF/') and not name.startswith(('META-INF/services/', 'META-INF/maven/', 'META-INF/versions/')):
            # Preserve otherwise colliding LICENSE/NOTICE/build records per artifact.
            name = 'META-INF/local-ee/origins/'+label+'/'+name
        if name in values and values[name] != content:
            raise ValueError('Assembly collision: '+name)
        values[name] = content


def finish(values):
    for name in list(values):
        if name.startswith('META-INF/') and name.upper().endswith(('.SF', '.RSA', '.DSA')):
            del values[name]
    manifest = values.get('META-INF/MANIFEST.MF', b'Manifest-Version: 1.0\r\n\r\n')
    # New Jackson has JVM-specific classes; retaining them requires an MR manifest.
    if any(name.startswith('META-INF/versions/') and not name.endswith('module-info.class') for name in values):
        manifest = re.sub(br'(?im)^Multi-Release:.*\r?\n', b'', manifest)
        manifest = b'Multi-Release: true\r\n'+manifest
    values['META-INF/MANIFEST.MF'] = manifest
