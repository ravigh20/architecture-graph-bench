"""36 checks of the current diagnostic implementation, not recovered historical logs."""
import copy,csv,json,tempfile,unittest
from pathlib import Path
from archgraphbench import diagnostics as d
from archgraphbench.core import support_reference,set_metrics,weighted_divergence,selection_metrics
from archgraphbench.io import read_json
ROOT=Path(__file__).resolve().parents[1]
class DiagnosticsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();cls.out=Path(cls.tmp.name)
        cls.config=read_json(ROOT/'data/experiment_config.json');cls.result=d.run(cls.out,cls.config)
    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()
    def pooled(self,policy,threshold=.8,scheme='equal'):
        return next(r for r in self.result['support_summary'] if r['policy_id']==policy and r['threshold']==threshold and r['weight_scheme']==scheme)
    def test_01_chain_ten(self):self.assertEqual(self.result['bridge'][0]['f1_exact'],'18/19')
    def test_02_chain_hundred(self):self.assertEqual(self.result['bridge'][1]['f1_exact'],'198/199')
    def test_03_chain_thousand(self):self.assertEqual(self.result['bridge'][2]['f1_exact'],'1998/1999')
    def test_04_bridge_divergence(self):self.assertTrue(all(r['Ds']==1 for r in self.result['bridge']))
    def test_05_four_changed(self):self.assertTrue(all(r['changed_queries']==4 for r in self.result['bridge']))
    def test_06_bridge_witnesses(self):
        r=read_json(self.out/'diagnostics/bridge_query_witnesses.json');self.assertEqual(len(r),12);self.assertTrue(all(x['reference_witness'] and x['prediction_witness'] is None for x in r))
    def test_07_table_v_delete(self):self.assertEqual([r['exact_f1'] for r in d.arithmetic_cases([8,9])[0]][:2],['14/15','16/17'])
    def test_08_table_v_insert(self):self.assertEqual([r['exact_f1'] for r in d.arithmetic_cases([8,9])[0]][2:4],['16/17','18/19'])
    def test_09_zone_only(self):self.assertEqual(d.arithmetic_cases([8,9])[0][-1]['exact_f1'],'1')
    def test_10_bad_arithmetic(self):
        with self.assertRaises(ValueError):d.arithmetic_cases([1])
    def test_11_population(self):self.assertEqual(self.result['support_configurations'],256)
    def test_12_policies(self):self.assertEqual(self.result['policy_count'],4)
    def test_13_output_population(self):self.assertEqual(self.result['configuration_policy_outputs_per_threshold'],1024)
    def test_14_proposition_population(self):self.assertEqual(self.result['proposition_policy_evaluations_per_threshold'],4096)
    def test_15_preserving(self):self.assertEqual((self.pooled('evidence_preserving')['accepted'],self.pooled('evidence_preserving')['De']), (512,0))
    def test_16_positive(self):self.assertEqual((self.pooled('positive_precedence')['accepted'],self.pooled('positive_precedence')['UCR_exact']),(768,'1/3'))
    def test_17_closed_world(self):self.assertEqual((self.pooled('closed_world')['accepted'],self.pooled('closed_world')['unsupported']),(1024,512))
    def test_18_always_unknown(self):self.assertIsNone(self.pooled('always_unknown')['UCR']);self.assertEqual(self.pooled('always_unknown')['De'],.75)
    def test_19_high_threshold(self):self.assertTrue(all(r['accepted']==0 and r['UCR'] is None for r in self.result['support_summary'] if r['threshold']==.95))
    def test_20_prethreshold_invariance(self):
        for policy in d.POLICY_NAMES:self.assertEqual(self.pooled(policy,.5)['De'],self.pooled(policy,.95)['De'])
    def test_21_weighted_means(self):
        for policy in d.POLICY_NAMES:self.assertEqual(self.pooled(policy)['De'],self.pooled(policy,scheme='weighted')['De'])
    def test_22_threshold_half(self):
        for policy in d.POLICY_NAMES:self.assertEqual(self.pooled(policy,.5)['accepted'],self.pooled(policy,.8)['accepted'])
    def test_23_lowering_confidence_changes_selection(self):self.assertEqual(selection_metrics(['T'],['T'],[.7],.8)['accepted'],0)
    def test_24_policy_maps_conflict(self):self.assertEqual([d.policy_answer('C',p) for p in d.POLICY_NAMES],['C','T','T','U'])
    def test_25_policy_maps_unknown(self):self.assertEqual([d.policy_answer('U',p) for p in d.POLICY_NAMES],['U','U','F','U'])
    def test_26_invalid_policy(self):
        with self.assertRaises(ValueError):d.policy_answer('T','missing')
    def test_27_transition_states(self):self.assertEqual([r['state'] for r in d.transition_examples()[0]],['T','U','C','F','U'])
    def test_28_transition_time_boundary(self):self.assertEqual(d.transition_examples()[1][-1]['audit'][0]['reason'],'outside_half_open_validity_interval')
    def test_29_weight_population(self):self.assertEqual(self.result['weight_settings'],81)
    def test_30_weight_rank_counts(self):self.assertEqual(self.result['weight_ranks'],{'A':66,'B':9,'Tie':6})
    def test_31_coordinate_count(self):self.assertEqual(self.result['distinct_plot_coordinates'],42)
    def test_32_multiplicities(self):
        with (self.out/'diagnostics/weight_points.csv').open() as f:rows=list(csv.DictReader(f))
        self.assertEqual(sum(int(r['multiplicity']) for r in rows),81);self.assertLessEqual(max(int(r['multiplicity']) for r in rows),4)
    def test_33_zero_denominator(self):self.assertIsNone(set_metrics(set(),set())['f1'])
    def test_34_bad_weight(self):
        with self.assertRaises(ValueError):weighted_divergence(['T'],['F'],[0])
    def test_35_bad_state(self):
        with self.assertRaises(ValueError):d.policy_answer('X','evidence_preserving')
    def test_36_deterministic_rerun(self):
        other=self.out/'repeat';r=d.run(other,self.config);self.assertEqual(r,self.result)
        self.assertEqual((other/'diagnostics/support_summary.csv').read_bytes(),(self.out/'diagnostics/support_summary.csv').read_bytes())
