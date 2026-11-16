"""Tests for the NEW reference-preparation utility, not evidence of human review."""
import copy
import csv
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import yaml

from archgraphbench import boutique
from archgraphbench.io import read_json, sha256, write_json, write_csv, YamlSource
from archgraphbench.reference_builder import (build_candidate, write_candidate, verify_reference,
    compare_references, finalize, review_rows, REVIEW_FIELDS, validate_profile, witness, safe_destination)

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT/'data'
SOURCE = DATA/'public_case/source/kubernetes-manifests.yaml'
PROFILE = ROOT/'profiles/online_boutique.json'


class ReferenceBuilderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.base = Path(cls.tmp.name)
        cls.candidate_dir = cls.base/'candidate'
        cls.before = sha256(SOURCE)
        cls.result = write_candidate(SOURCE, PROFILE, cls.candidate_dir)
        cls.candidate = cls.candidate_dir/'reference.json'
        cls.ref = read_json(cls.candidate)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def local(self, name):
        return self.base/self._testMethodName/name

    def test_shape_and_pending_status(self):
        self.assertEqual((len(self.ref['nodes']),len(self.ref['edges']),len(self.ref['queries'])),(24,28,8))
        self.assertEqual(self.ref['reference_metadata']['status'],'candidate_pending_review')
        self.assertFalse(self.ref['reference_metadata']['independent_validation'])

    def test_no_historical_reference_read_or_M2_call(self):
        from archgraphbench import reference_builder as rb
        reads = []
        real = rb.read_json
        def only_profile(path):
            reads.append(Path(path).resolve())
            if Path(path).resolve() != PROFILE.resolve():
                raise AssertionError('Generator attempted to read a reference or a result')
            return real(path)
        with patch.object(rb,'read_json',side_effect=only_profile), \
             patch.object(boutique,'extract',side_effect=AssertionError('No copying M2 predictions')):
            generated,_ = build_candidate(SOURCE,PROFILE)
        self.assertEqual(len(generated['edges']),28)
        self.assertEqual(reads,[PROFILE.resolve()])

    def test_exact_legacy_semantics_but_not_byte_identity(self):
        result=compare_references(self.candidate, DATA/'public_case/reference.json',self.local('comparison'))
        self.assertTrue(result['all_match'])
        self.assertNotEqual(result['candidate_sha256'],result['historical_sha256'])

    def test_each_node_and_edge_has_real_source_witnesses(self):
        source=YamlSource(SOURCE,SOURCE.name)
        for record in self.ref['nodes']+self.ref['edges']:
            self.assertTrue(record['support'])
            for loc in record['support']:
                self.assertEqual(loc, source.locate(loc['kind'],loc['name'],loc['field'],loc['namespace']))

    def test_full_masked_labels_computed(self):
        byid={q['id']:q for q in self.ref['queries']}
        self.assertEqual([q['full'] for q in self.ref['queries']],list('TTTTTTFF'))
        self.assertEqual([q['masked'] for q in self.ref['queries']],list('TUTUTTFF'))
        evidence=read_json(self.candidate_dir/'query_evidence.json')
        q2=next(r for r in evidence if r['condition']=='full' and r['query']=='Q2')
        self.assertEqual(len(q2['witness']),3)
        self.assertTrue(q2['source_witnesses'])

    def test_repeated_build_is_deterministic(self):
        again,_=build_candidate(SOURCE,PROFILE)
        self.assertEqual(self.ref,again)

    def test_input_unchanged(self):
        self.assertEqual(self.before,sha256(SOURCE))

    def test_review_all_pending_no_fake_review(self):
        with (self.candidate_dir/'review.csv').open(newline='') as f:rows=list(csv.DictReader(f))
        self.assertEqual(len(rows),70) # scope + nodes + edges + 16 condition answers + exclusion
        self.assertTrue(all(r['decision']=='PENDING' and not r['reviewer'] for r in rows))
        self.assertTrue(all(r['candidate_sha256']==sha256(self.candidate) for r in rows))

    def test_unreviewed_reference_requires_flag(self):
        with self.assertRaisesRegex(ValueError,'unreviewed'):
            verify_reference(SOURCE,self.candidate)
        self.assertEqual(verify_reference(SOURCE,self.candidate,allow_unreviewed=True)['status'],'MECHANICAL_CHECKS_PASSED')

    def test_changed_yaml_rejected_even_whitespace(self):
        source=self.local('kubernetes-manifests.yaml');source.parent.mkdir(parents=True)
        source.write_bytes(SOURCE.read_bytes()+b'\n')
        with self.assertRaisesRegex(ValueError,'SHA-256'):
            verify_reference(source,self.candidate,allow_unreviewed=True)

    def test_changed_answer_rejected(self):
        ref=copy.deepcopy(self.ref);ref['queries'][1]['masked']='F'
        path=self.local('reference.json');write_json(path,ref)
        with self.assertRaisesRegex(ValueError,'Masked support'):
            verify_reference(SOURCE,path,allow_unreviewed=True)

    def test_changed_locator_rejected(self):
        ref=copy.deepcopy(self.ref);ref['edges'][0]['support'][0]['lines']=[1,2]
        path=self.local('reference.json');write_json(path,ref)
        with self.assertRaisesRegex(ValueError,'Source location'):
            verify_reference(SOURCE,path,allow_unreviewed=True)

    def test_expected_answers_rejected_in_profile(self):
        p=read_json(PROFILE);p['queries'][0]['full']='T'
        with self.assertRaisesRegex(ValueError,'expected/full/masked'):
            validate_profile(p)

    def test_profile_duplicate_and_empty_queries(self):
        p=read_json(PROFILE);p['queries'].append(p['queries'][0])
        with self.assertRaisesRegex(ValueError,'Duplicate query'):validate_profile(p)
        p['queries']=[]
        with self.assertRaisesRegex(ValueError,'nonempty'):validate_profile(p)

    def test_invalid_query_weights(self):
        for weight in [0,-1,True,float('inf')]:
            p=read_json(PROFILE);p['queries'][0]['weight']=weight
            with self.subTest(weight=weight),self.assertRaises(ValueError):validate_profile(p)

    def test_mask_must_match_one_existing_value(self):
        p=read_json(PROFILE);p['mask']['resource']='nonexistent'
        path=self.local('profile.json');write_json(path,p)
        with self.assertRaisesRegex(ValueError,'Mask matched 0'):
            build_candidate(SOURCE,path)

    def test_query_profile_must_match_application(self):
        p=read_json(PROFILE);p['queries'][0]['target']='nonexistent'
        path=self.local('profile.json');write_json(path,p)
        with self.assertRaisesRegex(ValueError,'absent nodes'):
            build_candidate(SOURCE,path)

    def test_duplicate_yaml_key_rejected(self):
        path=self.local('bad.yaml');path.parent.mkdir(parents=True)
        path.write_text('kind: Deployment\nkind: Service\nmetadata:\n  name: a\n')
        with self.assertRaisesRegex(ValueError,'Duplicate YAML'):
            build_candidate(path,PROFILE)

    def test_non_default_namespace_rejected(self):
        objects=list(yaml.safe_load_all(SOURCE.read_text()))
        objects[0]['metadata']['namespace']='different'
        path=self.local('source.yaml');path.parent.mkdir(parents=True)
        path.write_text(yaml.safe_dump_all(objects))
        with self.assertRaisesRegex(ValueError,'default namespace'):
            build_candidate(path,PROFILE)

    def test_unsupported_kind_rejected(self):
        path=self.local('source.yaml');path.parent.mkdir(parents=True)
        path.write_text(SOURCE.read_text()+'\n---\nkind: ConfigMap\nmetadata:\n  name: extra\n')
        with self.assertRaisesRegex(ValueError,'Unsupported kind'):
            build_candidate(path,PROFILE)

    def test_resource_reordering_semantics(self):
        objects=list(yaml.safe_load_all(SOURCE.read_text()))
        path=self.local('source.yaml');path.parent.mkdir(parents=True)
        path.write_text(yaml.safe_dump_all(list(reversed(objects))))
        ref,_=build_candidate(path,PROFILE)
        key=lambda r:{(e['source'],e['relation'],e['target']) for e in r['edges']}
        self.assertEqual(key(ref),key(self.ref))
        self.assertEqual(ref['queries'],self.ref['queries'])

    def test_real_yaml_change_changes_reference(self):
        text=SOURCE.read_text().replace('paymentservice:50051','shippingservice:50051')
        self.assertNotEqual(text,SOURCE.read_text())
        path=self.local('source.yaml');path.parent.mkdir(parents=True);path.write_text(text)
        changed,_=build_candidate(path,PROFILE)
        self.assertNotEqual(changed['edges'],self.ref['edges'])
        self.assertEqual(next(q for q in changed['queries'] if q['id']=='Q2')['full'],'F')

    def test_identity_edges_cannot_create_flow_path(self):
        edges={('a','assigned_service_account','b')}
        self.assertIsNone(witness(edges,{'kind':'path','source':'a','target':'b'}))
        self.assertIsNotNone(witness(edges,{'kind':'identity','source':'a','target':'b'}))

    def test_output_directory_protected(self):
        with self.assertRaisesRegex(ValueError,'not empty'):
            write_candidate(SOURCE,PROFILE,self.candidate_dir)
        with self.assertRaisesRegex(ValueError,'frozen input'):
            safe_destination(DATA/'forbidden_reference',[SOURCE])
        self.assertFalse((DATA/'forbidden_reference').exists())

    def test_finalize_refuses_pending_rows(self):
        with self.assertRaisesRegex(ValueError,'needs APPROVE'):
            finalize(self.candidate,self.candidate_dir/'review.csv',self.local('reviewed'),'test reviewer','test only')

    def completed_review(self):
        rows=review_rows(self.ref,sha256(self.candidate))
        for r in rows:
            r.update(decision='APPROVE',reviewer='Fictional unit-test reviewer',notes='Synthetic approval for testing only; not a real research review.')
        path=self.local('review.csv');write_csv(path,rows,REVIEW_FIELDS)
        return path,rows

    def test_finalize_records_not_certifies_review(self):
        path,rows=self.completed_review()
        output=self.local('reviewed')
        result=finalize(self.candidate,path,output,'Unit test','Synthetic workflow test only')
        self.assertEqual(result['status'],'REVIEW_RECORDED')
        ref=read_json(output/'reference.json')
        self.assertFalse(ref['reference_metadata']['independent_validation'])
        self.assertFalse(ref['reference_metadata']['review']['identity_or_independence_verified_by_software'])
        self.assertEqual(verify_reference(SOURCE,output/'reference.json')['reference_status'],'review_recorded')
        self.assertEqual(read_json(self.candidate)['reference_metadata']['status'],'candidate_pending_review')

    def test_finalize_rejects_altered_item_or_hash(self):
        path,rows=self.completed_review();rows[0]['candidate_sha256']='bad'
        write_csv(path,rows,REVIEW_FIELDS)
        with self.assertRaisesRegex(ValueError,'differs'):
            finalize(self.candidate,path,self.local('reviewed'),'Unit test','Synthetic test')

    def test_finalize_rejects_duplicate_missing_records(self):
        path,rows=self.completed_review();rows[-1]=rows[0]
        write_csv(path,rows,REVIEW_FIELDS)
        with self.assertRaisesRegex(ValueError,'exactly once'):
            finalize(self.candidate,path,self.local('reviewed'),'Unit test','Synthetic test')

    def test_processing_accepts_explicit_candidate_and_keeps_metrics(self):
        out=self.local('results')
        command=[sys.executable,str(ROOT/'process.py'),'--data',str(DATA),'--study','boutique',
                 '--source',str(SOURCE),'--reference',str(self.candidate),'--allow-unreviewed-reference',
                 '--out',str(out)]
        r=subprocess.run(command,capture_output=True,text=True)
        self.assertEqual(r.returncode,0,r.stdout+r.stderr)
        data=read_json(out/'summary.json')['boutique']
        self.assertEqual(data['reference_mode'],'generated_unreviewed_candidate')
        self.assertEqual(next(x for x in data['cases'] if x['condition']=='masked' and x['method']=='M2-CW')['UCR_q'],.25)
        self.assertTrue(read_json(out/'run.json')['override_inputs_unchanged'])

    def test_processing_refuses_silent_unreviewed_candidate(self):
        r=subprocess.run([sys.executable,str(ROOT/'process.py'),'--data',str(DATA),'--study','boutique',
                          '--reference',str(self.candidate),'--out',str(self.local('results'))],capture_output=True,text=True)
        self.assertNotEqual(r.returncode,0)
        self.assertIn('unreviewed',r.stderr)

    def test_processing_requires_matching_reference_with_source(self):
        r=subprocess.run([sys.executable,str(ROOT/'process.py'),'--data',str(DATA),'--study','boutique',
                          '--source',str(SOURCE),'--out',str(self.local('results'))],capture_output=True,text=True)
        self.assertNotEqual(r.returncode,0)
        self.assertIn('requires --reference',r.stderr)

    def test_malformed_yaml_cli_error_is_clear(self):
        path=self.local('bad.yaml');path.parent.mkdir(parents=True);path.write_text('kind: [unterminated')
        r=subprocess.run([sys.executable,str(ROOT/'build_reference.py'),'--input',str(path),
                          '--out',str(self.local('generated'))],capture_output=True,text=True)
        self.assertEqual(r.returncode,2)
        self.assertIn('ERROR:',r.stderr)
        self.assertNotIn('Traceback',r.stderr)

    def test_verify_cli(self):
        r=subprocess.run([sys.executable,str(ROOT/'build_reference.py'),'verify','--input',str(SOURCE),
                          '--reference',str(self.candidate)],capture_output=True,text=True)
        self.assertEqual(r.returncode,0,r.stderr)
        self.assertIn('MECHANICAL_CHECKS_PASSED',r.stdout)

    def test_candidate_query_subset_with_zero_acceptance(self):
        profile=read_json(PROFILE);profile['queries']=[profile['queries'][1]]
        profile_path=self.local('profile.json');write_json(profile_path,profile)
        generated=self.local('generated');write_candidate(SOURCE,profile_path,generated)
        out=self.local('results')
        r=subprocess.run([sys.executable,str(ROOT/'process.py'),'--data',str(DATA),'--study','boutique',
                          '--source',str(SOURCE),'--reference',str(generated/'reference.json'),
                          '--allow-unreviewed-reference','--out',str(out)],capture_output=True,text=True)
        self.assertEqual(r.returncode,0,r.stdout+r.stderr)
        self.assertIn('N/A',r.stdout)
        rows=read_json(out/'boutique/metrics.json')
        zero=[x for x in rows if x['accepted']==0]
        self.assertTrue(zero)
        self.assertTrue(all(x['UCR_q'] is None for x in zero))


if __name__=='__main__': unittest.main()
