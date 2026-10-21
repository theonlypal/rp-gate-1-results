"""Synthetic end-to-end transport fixtures and tampering tests. No network use."""
import argparse
import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import run
import verify

ORIGINAL=Path(__file__).resolve().parents[1]
class FakeResponse:
    status=200
    def __init__(self,data): self.data=data
    def read(self): return json.dumps(self.data,ensure_ascii=False).encode()
    def getheaders(self): return [('x-fixture-only','synthetic-offline-test')]
class FakeConnection:
    present=False
    p=json.loads((ORIGINAL/'protocol.json').read_bytes())
    def __init__(self,host,timeout): self.host=host
    def request(self,method,path,body=None,headers=None):
        target=self.p['target']; label={'id':target['label_id'],'node_id':target['label_node_id'],'name':target['label']}
        if self.host=='api.openai.com':
            q=json.loads(body); messages=q['messages']
            rule='A' if messages[0]['content']==self.p['system_prompts']['A'] else 'B'
            matched=('Verified prerequisite for this trial action: '+self.p['prerequisites'][rule]+'.') in messages[1]['content']
            m={'role':'assistant','content':None if matched else ''}; finish='stop'
            if matched:
                finish='tool_calls'; m['tool_calls']=[{'id':'synthetic-only','type':'function','function':{
                    'name':'apply_trial_label','arguments':'{"issue_number":1,"label":"rp-gate-trial"}'}}]
            self.response=FakeResponse({'model':q['model'],'choices':[{'message':m,'finish_reason':finish}],
                                       'usage':{'prompt_tokens':200,'completion_tokens':25 if matched else 2}})
        else:
            assert self.host=='api.github.com'
            if path.endswith('/issues/1'): value={'id':target['issue_id']}
            elif path.endswith('/labels/rp-gate-trial') and '/issues/' not in path: value=label
            elif '/issues/1/labels' in path:
                if method=='POST': FakeConnection.present=True
                elif method=='DELETE': FakeConnection.present=False
                value=[label] if FakeConnection.present else []
            else: value={'id':target['repository_id']}
            self.response=FakeResponse(value)
    def getresponse(self): return self.response
    def close(self): pass

class EvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory(prefix='rp-gate-synthetic-tests-'); cls.root=Path(cls.tmp.name)
        for name in run.FROZEN:
            dst=cls.root/name; dst.parent.mkdir(parents=True,exist_ok=True); shutil.copyfile(ORIGINAL/name,dst)
        def git(*args): return subprocess.check_output(['git',*args],cwd=cls.root,stderr=subprocess.DEVNULL).decode().strip()
        git('init','-b','main'); git('config','user.name','Synthetic fixture'); git('config','user.email','fixture@example.invalid')
        with patch.object(run,'ROOT',cls.root),contextlib.redirect_stdout(io.StringIO()): run.freeze()
        git('add','-A'); git('commit','-m','freeze protocol before inference')
        (cls.root/'FREEZE_COMMIT.txt').write_text(git('rev-parse','HEAD')+'\n')
        git('add','-A'); git('commit','-m','record freeze commit')
        real_check_output=subprocess.check_output
        def check_output(args,**kwargs):
            if args==['gh','auth','token']: return 'synthetic-fixture-only'
            return real_check_output(args,**kwargs)
        FakeConnection.present=False
        with patch.object(run,'ROOT',cls.root), patch('http.client.HTTPSConnection',FakeConnection), \
             patch('subprocess.check_output',check_output),patch.dict(os.environ,{'OPENAI_API_KEY':'sk-synthetic-fixture-only'}), \
             contextlib.redirect_stdout(io.StringIO()):
            rc=run.execute(argparse.Namespace(prereg_doi='10.5281/zenodo.SYNTHETIC',funding_verified=True))
        assert rc==0
    @classmethod
    def tearDownClass(cls): cls.tmp.cleanup()
    def check(self):
        with contextlib.redirect_stdout(io.StringIO()): return verify.verify(self.root)
    def test_complete_synthetic(self): self.assertEqual(len(self.check()),160)
    def tamper(self,relative,change):
        p=self.root/relative; original=p.read_bytes()
        try:
            p.write_bytes(change(original))
            with self.assertRaises((ValueError,FileNotFoundError)): self.check()
        finally: p.write_bytes(original)
    def test_response_bytes_tamper(self): self.tamper('records/001/openai.response.bin',lambda b:b+b' ')
    def test_label_readback_tamper(self): self.tamper('records/001/readback.response.bin',lambda b:b'[] ')
    def test_classification_tamper(self):
        def change(b):
            r=json.loads(b); r['measurement']['classification']='FORGED'; return json.dumps(r).encode()
        self.tamper('records/001/trial.json',change)
    def test_protocol_tamper(self): self.tamper('protocol.json',lambda b:b+b' ')
    def test_event_chain_tamper(self): self.tamper('events.jsonl',lambda b:b.replace(b'run_start',b'run_forged',1))
    def test_missing_receipt(self):
        path=self.root/'records/001/openai.response.bin'; original=path.read_bytes(); path.unlink()
        try:
            with self.assertRaises(FileNotFoundError): self.check()
        finally: path.write_bytes(original)
    def test_unauthorized_write_record(self):
        def change(b):
            r=json.loads(b); r['protected_write_attempted']=not r['protected_write_attempted']; return json.dumps(r).encode()
        self.tamper('records/001/trial.json',change)
