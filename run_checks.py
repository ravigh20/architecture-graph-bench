#!/usr/bin/env python3
"""Execute current implementation tests and retain actual test outcomes."""
import argparse,io,sys,unittest
from pathlib import Path
from datetime import datetime,timezone
from archgraphbench.io import write_json
ROOT=Path(__file__).resolve().parent
class RecordedResult(unittest.TextTestResult):
    def __init__(self,*a,**kw):super().__init__(*a,**kw);self.records=[]
    def addSuccess(self,test):super().addSuccess(test);self.records.append({'test':test.id(),'status':'PASS'})
    def addFailure(self,test,err):super().addFailure(test,err);self.records.append({'test':test.id(),'status':'FAIL'})
    def addError(self,test,err):super().addError(test,err);self.records.append({'test':test.id(),'status':'ERROR'})
    def addSkip(self,test,reason):super().addSkip(test,reason);self.records.append({'test':test.id(),'status':'SKIP','reason':reason})
def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,required=True)
    a=p.parse_args(argv)
    if a.out.exists():p.error('Choose a new checks output folder')
    a.out.mkdir(parents=True)
    suite=unittest.defaultTestLoader.discover(str(ROOT/'tests'))
    log=io.StringIO();r=unittest.TextTestRunner(stream=log,verbosity=2,resultclass=RecordedResult).run(suite)
    (a.out/'tests.log').write_text(log.getvalue(),encoding='utf-8')
    groups={}
    for row in r.records:
        group=row['test'].split('.')[0];groups.setdefault(group,{'tests':0,'passed':0,'failed':0,'skipped':0})
        groups[group]['tests']+=1;groups[group]['passed']+=row['status']=='PASS'
        groups[group]['failed']+=row['status'] in ('FAIL','ERROR');groups[group]['skipped']+=row['status']=='SKIP'
    report={'recorded_at':datetime.now(timezone.utc).isoformat(),'tests_run':r.testsRun,'successful':r.wasSuccessful(),
            'failures':len(r.failures),'errors':len(r.errors),'skipped':len(r.skipped),'groups':groups,'tests':r.records,
            'provenance':'New execution of current implementation tests; not reconstructed historical execution logs.'}
    write_json(a.out/'test_results.json',report)
    print('Tests run:',r.testsRun,'failures:',len(r.failures),'errors:',len(r.errors),'skipped:',len(r.skipped))
    for group,values in groups.items():print(group,values)
    if not r.wasSuccessful():print(log.getvalue(),file=sys.stderr)
    return 0 if r.wasSuccessful() else 1
if __name__=='__main__':raise SystemExit(main())
