"""Behavior and numerical regression checks for the uploaded submission candidate.

Expected reported values live here, not in production graph builders or scorers.
The unresolved raw-direction threshold assertion is not disguised as a pass.
"""
import copy,csv,json,tempfile,unittest
from fractions import Fraction
from pathlib import Path
from archgraphbench import membership,replay,calibration,backends
from archgraphbench.io import read_json,inventory
ROOT=Path(__file__).resolve().parents[1];DATA=ROOT/'data'

class SubmissionStudiesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();cls.out=Path(cls.tmp.name)
        cls.before=inventory(DATA);c=read_json(DATA/'experiment_config.json')
        cls.m=membership.run(DATA,cls.out,c);cls.r=replay.run(DATA,cls.out,c);cls.c=calibration.run(DATA,cls.out,c)
    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()
    def test_01_membership_population(self):
        self.assertEqual((self.m['applications'],self.m['pairs'],self.m['positive_pairs'],self.m['cardinality_queries']),(4,249,27,50))
    def test_02_review_footprint(self):
        self.assertEqual((self.m['service_selector_records'],self.m['workload_label_records'],self.m['positive_witnesses']),(25,28,27))
    def test_03_bookinfo_name(self):
        r=next(x for x in self.m['methods'] if x['project']=='bookinfo' and x['method']=='M1')
        self.assertEqual((r['f1'],r['query_mismatches']),(0,5))
    def test_04_prefix_bookinfo(self):
        r=next(x for x in self.m['methods'] if x['project']=='bookinfo' and x['method']=='MP')
        self.assertEqual((r['tp'],r['fp'],r['fn'],r['query_mismatches']),(6,0,0,0))
    def test_05_prefix_sockshop(self):
        r=next(x for x in self.m['methods'] if x['project']=='sockshop' and x['method']=='MP')
        self.assertEqual((r['tp'],r['fp'],r['fn'],r['query_mismatches']),(14,8,0,8))
    def test_06_selectors(self):
        for r in self.m['methods']:
            if r['method']=='M2':self.assertEqual((r['fp'],r['fn'],r['query_mismatches']),(0,0,0))
    def test_07_pooled_briers(self):
        b=self.m['baselines']
        for key,target in [('fitted',.0453),('hard_name',.0241),('fixed_09',.0293),('prevalence',.1201)]:
            self.assertEqual(round(b[key]['pair_weighted_brier'],4),target)
    def test_08_equal_system_means(self):
        for key,target in [('fitted',.0591),('hard_name',.0625),('fixed_09',.0600)]:
            self.assertEqual(round(self.m['baselines'][key]['equal_system_brier'],4),target)
    def test_09_bookinfo_threshold(self):
        r=next(x for x in self.m['per_application']['bookinfo']['thresholds'] if x['threshold']==.95)
        self.assertEqual((r['accepted'],r['accepted_negative'],r['errors'],r['withheld_true_edges']),(18,18,0,6))
    def test_10_app_excluded_from_fit(self):
        folds=read_json(self.out/'membership/confidence_folds.json')
        for app,fold in folds.items():self.assertNotIn(app,fold['training_projects'])
        self.assertEqual(folds['bookinfo']['training_pairs'],225)
    def test_11_empty_selector_remains_in_universe(self):
        inp=backends.load_inputs(DATA/'study/data/bookinfo/manifest.yaml');s='default/details'
        inp.services[s]['selector']={}
        self.assertEqual(len(backends.pairs(inp)),24)
        self.assertEqual(backends.extract(inp,include_prefix=True)['selector'][s],[])
    def test_12_prefix_delimiter_not_arbitrary_start(self):
        self.assertEqual(backends.stratum('default/cart','default/cart-db'),'prefix')
        self.assertEqual(backends.stratum('default/cart','default/carts'),'other')
    def test_13_namespaces_do_not_cross(self):
        inp=backends.load_inputs(DATA/'study/data/bookinfo/manifest.yaml')
        inp.workloads['another/details-v1']=copy.deepcopy(inp.workloads['default/details-v1'])
        self.assertNotIn(('default/details','another/details-v1'),backends.pairs(inp))
    def test_14_replay_population(self):
        a=self.r['annotated'];self.assertEqual((a['records'],a['applications'],a['ordered_pair_evaluations']),(27,17,3150))
    def test_15_path_error_populations(self):
        a=self.r['annotated'];self.assertEqual((a['records_with_errors'],a['applications_with_errors']),(23,15))
    def test_16_missing_not_empty(self):
        missing=read_json(self.out/'replay/missing_records.json');self.assertEqual(len(missing),7)
        self.assertTrue(all(x['tool']=='MicroDepGraph' for x in missing))
    def test_17_ranking_reversals(self):
        a=self.r['annotated'];self.assertEqual(a['ranking_reversals'],2)
        apps={x['application'] for x in a['rankings'] if x['ranking_reversed']}
        self.assertEqual(apps,{'microservice-kafka','spring-boot-microservices'})
    def test_18_tied_f1_different_paths(self):
        a=next(x for x in self.r['annotated']['rankings'] if x['application']=='spring-cloud-netflix-example')
        self.assertTrue(a['F1_tied']);self.assertEqual((a['C_errors'],a['M_errors'],a['queries']),(8,16,90))
    def test_19_primary_excludes_FN(self):
        rows=read_json(self.out/'replay/annotation_records.json')
        self.assertTrue(all(not x['included_in_prediction'] for x in rows if x['status']=='FN'))
        self.assertTrue(all(x['included_in_prediction'] for x in rows if x['status'] in ('TP','FP')))
    def test_20_selfloops_and_extras_retained(self):
        gs=read_json(self.out/'replay/annotated_graphs.json')
        g=next(x for x in gs if x['system']=='microservice' and x['tool']=='Code2DFD')
        self.assertIn(['order','order'],g['prediction_edges'])
        j=next(x for x in gs if x['system']=='java-microservice' and x['tool']=='Code2DFD')
        self.assertIn(['github_repository','config_server'],j['prediction_edges'])
    def test_21_raw_replay_sensitive(self):
        self.assertEqual(self.r['raw_normalized']['different_from_annotated'],12)
        self.assertEqual(self.r['raw_normalized']['ranking_reversals'],0)
    def test_22_raw_alias_is_explicit(self):
        self.assertIn('raw_published_aliases',self.r)
        self.assertEqual(self.r['raw_published_aliases']['ranking_reversals'],0)
    def test_23_positive_proposal_population(self):
        c=self.c['annotated'];self.assertEqual((c['proposals'],c['correct_proposals'],c['reference_edges']),(244,225,245))
    def test_24_other_nine_applications(self):
        folds=read_json(self.out/'calibration/annotated/folds.json')
        self.assertEqual(len(folds),10)
        for f in folds:
            self.assertEqual(len(f['training_applications']),9);self.assertNotIn(f['test_application'],f['training_applications'])
    def test_25_proposal_briers(self):
        c=self.c['annotated'];self.assertEqual(round(c['brier'],4),.0728);self.assertEqual(round(c['fixed_09_brier'],4),.0723)
    def test_26_ece_bin_sensitivity(self):
        e=self.c['annotated']['ece']
        for k,v in [('fitted_10',.0543),('fixed_09_10',.0221),('fitted_5',.0102),('fixed_09_5',.0221)]:
            self.assertEqual(round(e[k],4),v)
    def test_27_proposal_threshold_08(self):
        r=next(x for x in self.c['annotated']['thresholds'] if x['method']=='fitted' and x['threshold']==.8)
        self.assertEqual((r['accepted'],r['correct']),(234,215))
    def test_28_proposal_threshold_095(self):
        r=next(x for x in self.c['annotated']['thresholds'] if x['method']=='fitted' and x['threshold']==.95)
        self.assertEqual((r['accepted'],r['correct'],r['applications']),(113,113,10))
    def test_29_fixed09_accepts_none_at095(self):
        r=next(x for x in self.c['annotated']['thresholds'] if x['method']=='fixed_09' and x['threshold']==.95)
        self.assertEqual(r['accepted'],0);self.assertIsNone(r['precision'])
    def test_30_low_proposal_p_not_confident_negative(self):
        rows=[{'c_exact':'1/20','gold':0,'system':'s','source':'a','target':'b','stratum':'micro_only'}]
        r,_,_,_=calibration.evaluate(rows,1,[.8],Fraction(9,10))
        self.assertEqual(next(x for x in r['thresholds'] if x['method']=='fitted')['accepted'],0)
    def test_31_heldout_labels_rejected_by_predictor(self):
        with self.assertRaises(ValueError):calibration.fit_predict([{'stratum':'both','gold':1}],[{'stratum':'both','gold':1}])
    def test_32_fit_depends_on_training_labels(self):
        f=[{'stratum':'both','system':'test','source':'a','target':'b'}]
        a=calibration.fit_predict([{'stratum':'both','gold':0}],f)[1]
        b=calibration.fit_predict([{'stratum':'both','gold':1}],f)[1]
        self.assertNotEqual(a[0]['c'],b[0]['c'])
    def test_33_bin_boundary(self):
        e,b=calibration.reliability_bins([{'c_exact':'9/10','gold':1}],10,'c_exact')
        self.assertEqual(b[8]['count'],1);self.assertEqual(b[9]['count'],0)
        self.assertAlmostEqual(e,.1)
    def test_34_bad_probability(self):
        with self.assertRaises(ValueError):calibration.reliability_bins([{'c_exact':'11/10','gold':1}],10,'c_exact')
    def test_35_edge_changes_path(self):
        n={'a','b','c'};g={('a','b'),('b','c')}
        a=replay.evaluate('x','C',n,g,g,'test')[0];b=replay.evaluate('x','C',n,g,{('a','b')},'test')[0]
        self.assertEqual(a['wrong_answers'],0);self.assertGreater(b['wrong_answers'],0)
    def test_36_source_projection_traceable(self):
        r=read_json(DATA/'replay/annotated_connections.json')['records']
        self.assertEqual(len(r),27)
        self.assertTrue(all(x['source_url'].startswith('https://raw.githubusercontent.com/') for x in r))
        self.assertTrue(all(c['upstream_line']>0 and c['source_text'] for x in r for c in x['connections']))
    def test_37_current_inputs_unchanged(self):self.assertEqual(self.before,inventory(DATA))
    def test_38_empty_bin_explicit(self):
        e,b=calibration.reliability_bins([{'c_exact':'1','gold':1}],5,'c_exact')
        self.assertEqual(e,0);self.assertIsNone(b[0]['mean_probability']);self.assertEqual(b[0]['ece_contribution'],0)
    def test_39_raw_threshold_actual_not_forced(self):
        # This intentionally checks honest generation, not the manuscript's
        # unreproduced statement that raw-direction sensitivity accepts none.
        for mode in ('raw_normalized','raw_published_aliases'):
            path=self.out/f'calibration/{mode}/proposals.csv'
            with path.open() as f:rows=list(csv.DictReader(f))
            count=sum(Fraction(r['c_exact'])>=Fraction(95,100) for r in rows)
            recorded=next(x for x in self.c[mode]['thresholds'] if x['method']=='fitted' and x['threshold']==.95)
            self.assertEqual(count,recorded['accepted'])
    def test_40_no_support_labels_for_replay(self):
        with (self.out/'replay/annotated_scores.csv').open() as f:rows=list(csv.DictReader(f))
        self.assertTrue(all(not r['UCR'] for r in rows))
