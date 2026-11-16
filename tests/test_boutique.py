"""18 focused checks of Online Boutique's input-to-evidence computation."""
import copy,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from archgraphbench import boutique as b
from archgraphbench.io import YamlSource,read_json,sha256
ROOT=Path(__file__).resolve().parents[1];DATA=ROOT/'data'
class BoutiqueTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();cls.out=Path(cls.tmp.name)
        cls.config=read_json(DATA/'experiment_config.json');cls.source=YamlSource(DATA/'public_case/source/kubernetes-manifests.yaml')
        cls.before=sha256(cls.source.path);cls.result=b.run(DATA,cls.out,cls.config)
        cls.metrics={(r['condition'],r['method']):r for r in cls.result['cases']}
        cls.queries=read_json(cls.out/'boutique/queries.json');cls.graphs=read_json(cls.out/'boutique/graphs.json')
    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()
    def test_01_inventory(self):
        from collections import Counter
        self.assertEqual(Counter(o['kind'] for o in self.source.objects),{'Deployment':12,'Service':12,'ServiceAccount':11})
    def test_02_nodes(self):self.assertTrue(all(r['nodes']==24 and r['node_f1']==1 for r in self.metrics.values()))
    def test_03_full_m1(self):self.assertEqual([self.metrics['full','M1'][k] for k in ('edges','edge_f1_exact','Ds','De','accepted')],[27,'54/55',.375,.5,4])
    def test_04_full_m2(self):self.assertEqual([self.metrics['full','M2'][k] for k in ('edges','edge_f1','Ds','De','accepted')],[28,1,0,0,8])
    def test_05_masked_m1(self):self.assertEqual([self.metrics['masked','M1'][k] for k in ('edges','edge_f1_exact','Ds','De','accepted')],[26,'26/27',.5,.375,3])
    def test_06_masked_m2(self):self.assertEqual([self.metrics['masked','M2'][k] for k in ('edges','Ds','De','accepted')],[27,.25,0,6])
    def test_07_masked_closed_world(self):self.assertEqual([self.metrics['masked','M2-CW'][k] for k in ('edges','Ds','De','accepted','UCR_q')],[27,.25,.25,8,.25])
    def test_08_same_graph(self):self.assertEqual(self.graphs['masked/M2']['edges'],self.graphs['masked/M2-CW']['edges'])
    def test_09_unknowns(self):self.assertEqual([r['query'] for r in self.queries if r['condition']=='masked' and r['method']=='M2' and r['evidence_prediction']=='U'],['Q2','Q4'])
    def test_10_unsupported(self):self.assertEqual([r['query'] for r in self.queries if r['method']=='M2-CW' and r['unsupported']],['Q2','Q4'])
    def test_11_witness(self):
        row=next(r for r in self.queries if r['condition']=='full' and r['method']=='M2' and r['query']=='Q2')
        self.assertEqual([row['witness'][0][0]]+[e[2] for e in row['witness']],['entry:frontend-external','frontend','checkoutservice','paymentservice'])
    def test_12_source_locators(self):
        for row in self.queries:
            for edge in row['witness_sources']:
                for loc in edge['locators']:self.assertTrue(1<=loc['lines'][0]<=loc['lines'][1]<=len(self.source.path.read_text().splitlines()))
    def test_13_single_mask_immutable(self):
        before=copy.deepcopy(self.source.objects);masked,rec=b.mask_input(before,self.config['boutique_mask'])
        self.assertEqual(rec['change_count'],1);self.assertEqual(before,self.source.objects);self.assertNotEqual(masked,before)
    def test_14_no_reference_read(self):
        with patch.object(b,'read_json',side_effect=AssertionError('Extraction cannot read references')):g=b.extract(self.source.objects,'M2')
        self.assertEqual(len(g['edges']),28)
    def test_15_order_invariance(self):self.assertEqual(b.extract(self.source.objects,'M2'),b.extract(list(reversed(self.source.objects)),'M2'))
    def test_16_entry_rename(self):
        modified=copy.deepcopy(self.source.objects)
        for o in modified:
            if o['kind']=='Service' and o['metadata']['name']=='frontend-external':o['metadata']['name']='other-entry'
        g=b.extract(modified,'M2');self.assertIn(('entry:other-entry','declared_entry','frontend'),g['edges']);self.assertNotIn(('entry:frontend-external','declared_entry','frontend'),g['edges'])
    def test_17_exclusions(self):self.assertTrue(all(r['excluded_endpoints']==1 for r in self.metrics.values()))
    def test_18_source_integrity_and_scope(self):
        self.assertEqual(sha256(self.source.path),self.before)
        self.assertFalse(self.result['source_comparison']['byte_identical']);self.assertTrue(self.result['source_comparison']['scoped_fields_identical'])
