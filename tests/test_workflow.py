import copy,json,subprocess,sys,tempfile,unittest
from pathlib import Path
from archgraphbench.io import read_json,inventory,check_data_manifest,YamlSource
from archgraphbench import bookinfo,backends
ROOT=Path(__file__).resolve().parents[1];DATA=ROOT/'data'
class WorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.out=Path(cls.temp.name)/'evidence';cls.before=inventory(DATA)
        cls.execution=subprocess.run([sys.executable,str(ROOT/'run_all_evidence.py'),'--data',str(DATA),'--out',str(cls.out),'--no-plots'],capture_output=True,text=True)
        if cls.execution.returncode:raise RuntimeError(cls.execution.stdout+cls.execution.stderr)
    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()
    def test_01_completed(self):self.assertEqual(read_json(self.out/'workflow.json')['status'],'COMPLETED')
    def test_02_inputs_unchanged(self):self.assertEqual(self.before,inventory(DATA));self.assertTrue(check_data_manifest(DATA)['matches'])
    def test_03_final_tables(self):
        stems=['I_related_work','II_support_transitions','III_tasks','IV_conventions','V_structural_arithmetic','VI_support_controls','VII_boutique','VIII_membership','IX_replay']
        for stem in stems:self.assertTrue((self.out/'results'/f'table_{stem}.csv').is_file())
    def test_04_old_table_numbering_absent(self):
        for name in ['table_II_replay.csv','table_V_boutique.csv','table_VIII_claim_evidence.csv','table_IX_scope_status.csv']:
            self.assertFalse((self.out/'results'/name).exists())
    def test_05_locator_integrity(self):
        r=read_json(self.out/'results/evidence/coverage.json');self.assertEqual(r['source_locators']['unresolved'],0);self.assertGreater(r['source_locators']['resolved'],0)
    def test_06_data_not_output(self):
        run=subprocess.run([sys.executable,str(ROOT/'process.py'),'--out',str(DATA/'never_create')],capture_output=True,text=True)
        self.assertNotEqual(run.returncode,0);self.assertFalse((DATA/'never_create').exists())
    def test_07_output_not_overwritten(self):
        run=subprocess.run([sys.executable,str(ROOT/'run_all_evidence.py'),'--out',str(self.out),'--no-plots'],capture_output=True,text=True)
        self.assertNotEqual(run.returncode,0)
    def test_08_manifest_change_changes_extraction(self):
        src=backends.load_inputs(DATA/'study/data/bookinfo/manifest.yaml')
        before=backends.extract(src);src.services['default/details']['selector']={'nonexistent':'none'}
        after=backends.extract(src);self.assertNotEqual(before['selector'],after['selector'])
    def test_09_support_selection_table_size(self):
        import csv
        with (self.out/'results/diagnostics/support_summary.csv').open() as f:r=list(csv.DictReader(f))
        self.assertEqual(len(r),24)
    def test_10_fits_are_label_driven_not_scores(self):
        fit=bookinfo.fit_strata([{'stratum':'prefix','gold':0}],['prefix']);changed=bookinfo.fit_strata([{'stratum':'prefix','gold':1}],['prefix'])
        self.assertNotEqual(fit['prefix']['p'],changed['prefix']['p'])
    def test_11_heldout_labels_only_affect_evaluation(self):
        fits={'prefix':{'p_exact':'1/10'}};p=bookinfo.apply_fit([{'service':'s','workload':'w','stratum':'prefix'}],fits)
        a,_,_=bookinfo.transfer_results(p,{('s','w'):0},[.8]);b,_,_=bookinfo.transfer_results(p,{('s','w'):1},[.8])
        self.assertNotEqual(a['brier'],b['brier']);self.assertEqual(p[0]['p'],.1)
    def test_12_descriptions_not_empirical(self):
        entries=read_json(self.out/'results/evidence/evidence_index.json')
        self.assertEqual(next(r for r in entries if r['id']=='table_I')['kind'],'DESCRIPTIVE_FROM_MANUSCRIPT')
        self.assertEqual(next(r for r in entries if r['id']=='figure_6')['kind'],'COMPUTED_PLOT')
