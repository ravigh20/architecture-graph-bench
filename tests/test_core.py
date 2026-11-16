import copy
import math
from pathlib import Path
import unittest
from archgraphbench.core import (Assertion, EvidenceBundle, support_state, set_metrics, weighted_divergence,
    query_weights, query_witness, graph_answer, selection_metrics, support_reference, evaluate_contract)
from archgraphbench.io import read_json

ROOT=Path(__file__).resolve().parents[1]

class CoreTests(unittest.TestCase):
    def test_exact_sets(self): self.assertEqual(set_metrics({1,2},{1,2})['f1'],1)
    def test_empty_both(self): self.assertIsNone(set_metrics(set(),set())['f1'])
    def test_empty_one(self): self.assertEqual(set_metrics({1},set())['f1'],0)
    def test_extra_edge(self): self.assertEqual(set_metrics({1},{1,2})['f1_exact'],'2/3')
    def test_duplicate_edges(self): self.assertEqual(set_metrics([1,1],[1])['tp'],1)
    def test_divergence(self): self.assertEqual(weighted_divergence(['T','F'],['F','F'],[3,1]),.75)
    def test_divergence_scaling(self): self.assertEqual(weighted_divergence([1,0],[0,0],[2,3]),weighted_divergence([1,0],[0,0],[4,6]))
    def test_divergence_rejects_empty(self):
        with self.assertRaises(ValueError): weighted_divergence([],[],[])
    def test_divergence_rejects_misaligned(self):
        with self.assertRaises(ValueError): weighted_divergence([1],[1,2],[1])
    def test_divergence_rejects_bad_weights(self):
        for value in [0,-1,float('nan'),float('inf'),True]:
            with self.subTest(value=value), self.assertRaises(ValueError): weighted_divergence([1],[0],[value])
    def test_families_normalized(self):
        q=[{'id':'a','family':'x'},{'id':'b','family':'x'},{'id':'c','family':'y'}]
        self.assertEqual(query_weights(q,{'x':4,'y':3}),[2,2,3])
    def test_duplicate_query_ids(self):
        with self.assertRaises(ValueError): query_weights([{'id':'a'},{'id':'a'}])
    def test_family_weight_collision(self):
        with self.assertRaises(ValueError): query_weights([{'id':'a','family':'x','weight':1}],{'x':1})
    def test_identity_not_traversed(self):
        e={('a','configured_dependency','b'),('b','assigned_service_account','c')}
        self.assertIsNone(query_witness(e,{'kind':'path','source':'a','target':'c'}))
    def test_identity_direct(self):
        e={('b','assigned_service_account','c')}
        self.assertEqual(query_witness(e,{'kind':'identity','source':'b','target':'c'}),list(e))
    def test_positive_length_path(self):
        self.assertIsNone(query_witness(set(),{'kind':'path','source':'a','target':'a'}))
        self.assertIsNotNone(query_witness({('a','configured_dependency','a')},{'kind':'path','source':'a','target':'a'}))
    def test_unknown_upper_path(self):
        q={'kind':'path','source':'a','target':'b'}
        a=graph_answer(set(),{('a','configured_dependency','b')},q,complete=True)
        self.assertEqual(a['evidence'],'U'); self.assertIsNotNone(a['possible_witness'])
    def test_missing_evidence_not_negative(self):
        q={'kind':'path','source':'a','target':'b'}
        self.assertEqual(graph_answer(set(),set(),q,complete=False)['evidence'],'U')
    def test_closed_world_not_justified_negative(self):
        q={'kind':'path','source':'a','target':'b'}
        a=graph_answer(set(),{('a','configured_dependency','b')},q,complete=True,closed_world=True)
        self.assertEqual(a['evidence'],'F');self.assertFalse(a['bounded_negative'])
    def test_bounded_negative(self):
        q={'kind':'path','source':'a','target':'b'}
        self.assertTrue(graph_answer(set(),set(),q,complete=True)['bounded_negative'])
    def test_four_states(self):
        self.assertEqual([support_state(a,b) for a,b in [(1,0),(0,1),(0,0),(1,1)]],['T','F','U','C'])
    def test_no_singletons(self):
        s=selection_metrics(['T','F'],['U','C']);self.assertEqual(s['coverage'],0);self.assertIsNone(s['ucr'])
    def test_unknown_negative_unsupported(self):
        s=selection_metrics(['U'],['F']);self.assertEqual(s['unsupported'],1);self.assertEqual(s['ucr'],1)
    def test_conflict_suppression(self): self.assertEqual(selection_metrics(['C'],['T'])['ucr'],1)
    def test_unreported_confidence_not_accepted_at_threshold(self):
        s=selection_metrics(['T'],['T'],[None],.8);self.assertEqual(s['accepted'],0)
    def test_threshold_boundary(self): self.assertEqual(selection_metrics(['T'],['T'],[.9],.9)['accepted'],1)
    def test_unadjudicated_full_ucr(self):
        s=selection_metrics(['T'],['T'],justification=[None]);self.assertIsNone(s['ucr']);self.assertEqual(s['unadjudicated_accepted'],1)
    def test_assertion(self):
        a=Assertion('s','p','o','flow',[], 'inferred',None,(None,None));self.assertIsNone(a.record()['confidence'])
    def test_bad_assertion(self):
        with self.assertRaises(ValueError): Assertion('s','p','o','flow',[], 'observed',1.1,(0,10))
    def test_bad_assertion_interval(self):
        with self.assertRaises(ValueError): Assertion('s','p','o','flow',[], 'observed',None,(5,5))
    def records(self):
        return [{'proposition':'q','source':'s','polarity':'+','admissible':True,'start':0,'end':10,'release':'r'}]
    def test_validity_start(self): self.assertEqual(support_reference(['q'],self.records(),target_time=0,release='r')[0]['q'],'T')
    def test_validity_end(self): self.assertEqual(support_reference(['q'],self.records(),target_time=10,release='r')[0]['q'],'U')
    def test_wrong_release(self): self.assertEqual(support_reference(['q'],self.records(),target_time=2,release='r2')[0]['q'],'U')
    def test_removed_source(self): self.assertEqual(support_reference(['q'],self.records(),target_time=2,release='r',removed_sources={'s'})[0]['q'],'U')
    def test_inadmissible(self):
        r=self.records();r[0]['admissible']=False
        self.assertEqual(support_reference(['q'],r,target_time=2,release='r')[0]['q'],'U')
    def test_unknown_derivation(self):
        r=self.records();r[0]['derivation']='inference'
        self.assertEqual(support_reference(['q'],r,target_time=2,release='r')[0]['q'],'U')
        self.assertEqual(support_reference(['q'],r,target_time=2,release='r',admitted_derivations={'inference'})[0]['q'],'T')
    def test_explicit_precedence(self):
        r=self.records();r.append({**r[0],'source':'s2','polarity':'-'})
        self.assertEqual(support_reference(['q'],r,target_time=2,release='r')[0]['q'],'C')
        self.assertEqual(support_reference(['q'],r,target_time=2,release='r',precedence=['s2','s'])[0]['q'],'F')
    def test_outside_scope_unadjudicated(self):
        labels,audit=support_reference(['other'],self.records(),target_time=2,release='r')
        self.assertEqual(labels['other'],'U');self.assertEqual(audit[0]['reason'],'outside_scope_unadjudicated')
    def test_core_example(self):
        case=read_json(ROOT/'examples/contract_case.json');result=evaluate_contract(case)
        self.assertEqual(result['Ds'],0);self.assertEqual(result['De'],.5)
        self.assertEqual(result['queries'][1]['support_reference'],'C')
    def test_threshold_does_not_change_de(self):
        case=read_json(ROOT/'examples/contract_case.json');a=evaluate_contract(case);case['threshold']=.95;b=evaluate_contract(case)
        self.assertEqual(a['De'],b['De']);self.assertEqual(b['query_selection']['accepted'],0)
    def test_dual_reference_mask_does_not_change_architecture(self):
        case=read_json(ROOT/'examples/contract_case.json');a=evaluate_contract(case);case['removed_sources']=['binding'];b=evaluate_contract(case)
        self.assertEqual(a['edge_metrics'],b['edge_metrics']);self.assertEqual(a['Ds'],b['Ds'])
        self.assertEqual(b['queries'][0]['support_reference'],'U')
