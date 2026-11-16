"""Six focused Bookinfo checks including the final-paper train/test split."""
import tempfile,unittest
from pathlib import Path
from archgraphbench import bookinfo as b
from archgraphbench.io import read_json
ROOT=Path(__file__).resolve().parents[1]
class BookinfoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();cls.out=Path(cls.tmp.name)
        cls.result=b.run(ROOT/'data',cls.out,read_json(ROOT/'data/experiment_config.json'))
    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()
    def test_01_inventory_and_reference_witnesses(self):
        r=next(r for r in self.result['inventory'] if r['project']=='bookinfo')
        self.assertEqual([r[k] for k in ('services','workload_templates','candidate_pairs','positive_pairs')],[4,6,24,6])
        self.assertEqual(self.result['review_footprint']['bookinfo'],{'field_records':10,'positive_edge_witnesses':6,'queries':8})
    def test_02_name_method(self):
        r=next(r for r in self.result['methods'] if r['method']=='name');self.assertEqual((r['edge_f1'],r['wrong_answers'],r['queries'],r['Ds']),(0,5,8,.625))
    def test_03_selector_and_saved_prediction(self):
        for r in self.result['methods']:
            if r['method']!='name':self.assertEqual((r['tp'],r['fp'],r['fn'],r['wrong_answers']),(6,0,0,0))
    def test_04_no_test_label_leakage(self):
        fit=read_json(self.out/'bookinfo/confidence_fit.json');self.assertEqual(fit['fit_pair_count'],225);self.assertNotIn('bookinfo',fit['training_projects'])
        rows=[{'service':'a','workload':'a-v1','stratum':'prefix'}];a=b.apply_fit(rows,fit['strata']);self.assertEqual(a[0]['p'],.1)
        with self.assertRaises(ValueError):b.apply_fit([{**rows[0],'gold':1}],fit['strata'])
        self.assertEqual(self.result['review_footprint']['confidence_fitting'],{'field_records':43,'positive_edge_witnesses':21})
    def test_05_brier(self):
        r=self.result['confidence'];self.assertEqual(r['test_pairs'],24);self.assertAlmostEqual(r['brier'],.20251913070094887);self.assertEqual(r['hard_name_brier'],.25)
    def test_06_thresholds_and_abstention(self):
        r=self.result['confidence']['thresholds'];self.assertEqual([(x['threshold'],x['accepted'],x['errors'],x['withheld_true_edges']) for x in r],[(.8,24,6,0),(.95,18,0,6)])
        fits={'x':{'p_exact':'1/2'}};p=b.apply_fit([{'service':'s','workload':'w','stratum':'x'}],fits)
        result,_,_=b.transfer_results(p,{('s','w'):1},[.5]);self.assertEqual(result['thresholds'][0]['accepted'],0)
