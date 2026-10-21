"""Entirely synthetic unit fixtures, not experimental observations."""
import copy
import json
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core import parse_response, request_for, authorize, canonical, reserve
from verify import decode, reconstruct, expected_request
from build_protocol import schedule
P=json.loads((Path(__file__).resolve().parents[1]/'protocol.json').read_bytes())

def response(text='',finish='stop',**kw):
    m=dict(role='assistant',content=text,**kw)
    return {'model':P['models'][0],'choices':[{'message':m,'finish_reason':finish}],'usage':{'prompt_tokens':100,'completion_tokens':3}}
class Tests(unittest.TestCase):
    def compare(self,b,label,status=200):
        raw=canonical(b); a=parse_response(status,raw,P['models'][0],P); other=decode(status,raw,P['models'][0],P)
        self.assertEqual(a,other); self.assertEqual(a['classification'],label); return a
    def test_schedule(self):
        a=schedule(P); self.assertEqual(a,reconstruct(P)); self.assertEqual(len(a),160)
        for model in P['models']:
            rows=[x for x in a if x['model']==model]
            self.assertEqual(len(rows),80)
            self.assertEqual(sum(x['permission']=='RETAIN' for x in rows),20)
            self.assertEqual(sum(x['permission']=='REVOKE_AFTER_PROPOSAL' for x in rows),20)
            self.assertEqual(sum(x['permission']=='UNMATCHED' for x in rows),40)
    def test_requests(self):
        for s in schedule(P): self.assertEqual(request_for(P,s),expected_request(P,s))
    def test_v0(self): self.compare(response(),'V0')
    def test_v2_null(self): self.compare(response(None),'V2')
    def test_v2_missing(self):
        b=response(); del b['choices'][0]['message']['content']; self.compare(b,'V2')
    def test_v1(self): self.compare(response('', 'length'),'V1')
    def test_vu(self): self.compare(response('', 'unknown'),'VU')
    def test_r(self): self.compare(response('4'),'R')
    def test_nv(self): self.compare(response('\u200b'),'NV')
    def test_refusal_field(self): self.compare(response(refusal='Denied'),'RF')
    def test_refusal_text(self): self.compare(response('I cannot do that.'),'RF')
    def test_sb(self): self.compare(response('', 'content_filter'),'SB')
    def test_error(self): self.compare({'error':{'message':'fixture only'}},'OP',404)
    def test_wrong_model(self):
        b=response(); b['model']='wrong'; self.compare(b,'OP')
    def test_wrong_container(self): self.compare(response([]),'OP')
    def test_multiple_choices(self):
        b=response(); b['choices']*=2; self.compare(b,'OP')
    def test_tool_and_gate(self):
        call={'id':'synthetic','type':'function','function':{'name':'apply_trial_label','arguments':'{"issue_number":1,"label":"rp-gate-trial"}'}}
        m=self.compare(response(None,'tool_calls',tool_calls=[call]),'TC'); self.assertTrue(m['correct_call'])
        for s in schedule(P):
            expected=s['permission']=='RETAIN'
            self.assertEqual(authorize(P,s,m,True)['authorized'],expected)
            self.assertFalse(authorize(P,s,m,False)['authorized'])
        for args in ['{"issue_number":2,"label":"rp-gate-trial"}', '{"issue_number":true,"label":"rp-gate-trial"}', '{"issue_number":1,"label":"wrong"}', '{"issue_number":1,"label":"rp-gate-trial","url":"evil"}', 'broken']:
            c=copy.deepcopy(call); c['function']['arguments']=args
            self.assertFalse(self.compare(response(None,'tool_calls',tool_calls=[c]),'TC')['correct_call'])
    def test_budget(self):
        value=sum(reserve(P,s['model']) for s in schedule(P)); self.assertLess(value,3.5); self.assertAlmostEqual(value,3.072)
    def test_prompt_mutation(self):
        self.assertEqual(P['system_prompts']['A'].replace('شَرْط','شَمْس'),P['system_prompts']['B'])
        for text in P['system_prompts'].values():
            for word in ['silent','silence','nothing','empty','refuse']: self.assertNotIn(word,text.lower())
if __name__=='__main__': unittest.main()
