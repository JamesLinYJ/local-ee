"""Bounded local EE export options and result finalization.

Names are immediate files inside the owning job, never paths supplied by JS.
"""
import csv
import io
import re

from ..artifacts import artifact_path, output_dir
from ..ee_translate import UnsupportedEEError


def export_options(action, options, bands):
    if action == 'export_image' and options.get('selectors') is not None:
        raise UnsupportedEEError('selectors is an Export.table parameter')
    prefix = options.get('fileNamePrefix')
    if prefix is not None:
        if not isinstance(prefix, str) or not re.fullmatch(r'[^\x00-\x1f/\\]{1,100}', prefix) or prefix.startswith('.') or prefix.endswith((' ', '.')):
            raise ValueError('fileNamePrefix must be a 1..100 character file name without paths or control characters')
    selectors = options.get('selectors')
    if selectors is not None:
        selectors = selectors.split(',') if isinstance(selectors, str) else selectors
        if not isinstance(selectors, list) or not selectors or any(not isinstance(x,str) or x not in bands for x in selectors) or len(set(selectors)) != len(selectors):
            raise UnsupportedEEError('Local CSV selectors must be distinct output column names: '+', '.join(bands))
    return {'file_prefix': prefix or '', 'selectors': selectors}


def _select_csv(path, selectors):
    if path.stat().st_size > 1048576:
        raise ValueError('CSV exceeds 1 MB')
    # The file is already bounded. Support a valid large single cell without
    # leaving Python's process-wide CSV limit changed after finalization.
    previous_limit = csv.field_size_limit(1048576)
    try:
        with path.open(encoding='utf-8', newline='') as stream:
            source = csv.DictReader(stream)
            if any(x not in (source.fieldnames or []) for x in selectors):
                raise ValueError('Result columns do not match requested selectors')
            rows = list(source)
    except (csv.Error, UnicodeError) as error:
        raise ValueError('Invalid UTF-8 CSV result') from error
    finally:
        csv.field_size_limit(previous_limit)
    text = io.StringIO(newline='')
    writer = csv.DictWriter(text, fieldnames=selectors, extrasaction='ignore')
    writer.writeheader()
    writer.writerows(rows)
    with path.open('w', encoding='utf-8', newline='') as stream:
        stream.write(text.getvalue())


def finalize_export(root, row):
    context = row.get('context', {})
    if context.get('protocol') != 'earthengine' or context.get('result_kind') != 'export': return
    folder = output_dir(root, row['id'])
    files = sorted((artifact_path(root,row['id'],p.name) for p in folder.iterdir() if p.suffix.lower() in {'.tif','.tiff','.nc','.csv'}), key=lambda x:x.name)
    selectors = context.get('selectors')
    if selectors is not None:
        for path in files:
            if path.suffix.lower() != '.csv': raise ValueError('Selectors require CSV output')
            _select_csv(path, selectors)
    prefix = context.get('file_prefix')
    if prefix:
        # Revalidate persisted options before they reach a physical operation.
        export_options('export_image', {'fileNamePrefix':prefix}, [])
        targets = [folder/(prefix+('' if len(files)==1 else '_'+str(i+1))+p.suffix) for i,p in enumerate(files)]
        if any(t != p and t.exists() for p,t in zip(files,targets)): raise ValueError('Export file name collision')
        for source,target in zip(files,targets):
            if source != target: source.rename(target)
