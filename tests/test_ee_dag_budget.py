"""Shared EE expressions must stay DAGs before reaching the graph node budget."""
import subprocess
import sys


def test_shared_ir_rebinding_and_source_discovery_are_bounded():
    # A timeout is a failure guard, not a throughput claim. Without memoization,
    # these 38 shared nodes expand to hundreds of billions of tree visits.
    code = '''
from dataclasses import replace
from gee.ee_translate import Source, Pixel, Graph, Image, Translator, UnsupportedEEError, _substitute
source = Source('sentinel-2-l2a', ('a','b'), ('nir',))
p = Pixel('band', (source, 'nir'))
for _ in range(38): p = Pixel('add', (p,p))
bound = _substitute(p, source, replace(source, ids=('a',)))
q = bound
for _ in range(38):
    assert q.args[0] is q.args[1]
    q = q.args[0]
assert q.args[0].ids == ('a',)
items = [{'id':i,'bbox':[0,0,2,2],'properties':{'system:time_start':1000}} for i in ('a','b')]
translator = Translator([], {'sentinel-2-l2a':items}, None)
graph = Graph(translator)
try:
    graph.image(Image([('nir', Pixel('reduce_t',(p,'mean')))], {}, source))
except UnsupportedEEError as error:
    assert '500 nodes' in str(error), error
else:
    assert len(graph.graph) <= 500
'''
    subprocess.run([sys.executable,'-c',code],check=True,timeout=8)
