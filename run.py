"""Single-attempt sequential runner. All HTTP exchanges retained; secrets excluded."""
import argparse
import datetime
import http.client
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import urllib.parse
from core import canonical, sha, request_for, parse_response, authorize, reserve, estimated_cost

ROOT=Path(__file__).resolve().parent
FROZEN=['build_protocol.py','core.py','run.py','verify.py','analyze.py','tests/test_protocol.py','tests/test_evidence.py',
        'protocol.json','schedule.json','PREREG.md','PROTOCOL.md','requirements.txt']
def now(): return datetime.datetime.now(datetime.timezone.utc).isoformat()
def save(path,obj):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('xb') as f: f.write(canonical(obj)+b'\n')
def load(path): return json.loads(path.read_bytes())
def freeze():
    assert not (ROOT/'events.jsonl').exists()
    assert not (ROOT/'FREEZE.json').exists(), 'Freeze exists: no overwriting'
    save(ROOT/'FREEZE.json',{'study':'RP-GATE-1','created_utc':now(),
        'files':{x:sha((ROOT/x).read_bytes()) for x in FROZEN}})
    print('FROZEN: no inference performed')

class Evidence:
    def __init__(self):
        self.chain='0'*64; self.n=0
        self.file=(ROOT/'events.jsonl').open('xb')
    def event(self,kind,**data):
        self.n+=1
        e=dict(index=self.n,utc=now(),kind=kind,previous_sha256=self.chain,**data)
        self.chain=sha(canonical(e)); e['sha256']=self.chain
        self.file.write(canonical(e)+b'\n'); self.file.flush(); os.fsync(self.file.fileno())
    def http(self, prefix, method, url, body, token, service):
        parsed=urllib.parse.urlsplit(url)
        assert parsed.scheme=='https' and parsed.netloc in ('api.openai.com','api.github.com')
        assert not parsed.username and not parsed.password
        prefix=ROOT/prefix; prefix.parent.mkdir(parents=True,exist_ok=True)
        req=body if body is not None else b''
        prefix.with_suffix('.request.bin').write_bytes(req)
        start=now(); status=0; headers=[]; raw=b''; error=None
        self.event('http_start',path=str(prefix.relative_to(ROOT)),method=method,url=url,request_sha256=sha(req))
        h={'Authorization':'Bearer '+token,'User-Agent':'RP-GATE-1/1','Accept':'application/json'}
        if service=='openai' and os.environ.get('OPENAI_ORGANIZATION'):
            h['OpenAI-Organization']=os.environ['OPENAI_ORGANIZATION']
        if body is not None: h['Content-Type']='application/json'
        if service=='github':
            h['Accept']='application/vnd.github+json'; h['X-GitHub-Api-Version']='2026-03-10'; h['Cache-Control']='no-cache'
        conn=http.client.HTTPSConnection(parsed.netloc,timeout=180)
        try:
            conn.request(method,parsed.path+('?' + parsed.query if parsed.query else ''),body=body,headers=h)
            r=conn.getresponse(); status=r.status
            headers=[(k,v) for k,v in r.getheaders() if k.lower() not in ('set-cookie','openai-organization','openai-project')]
            raw=r.read()
        except Exception as exc:
            error=type(exc).__name__  # never serialize credential-bearing exception text
        finally: conn.close()
        prefix.with_suffix('.response.bin').write_bytes(raw)
        meta=dict(start_utc=start,end_utc=now(),method=method,url=url,status=status,
                  response_headers=headers,transport_error=error,request_sha256=sha(req),response_sha256=sha(raw))
        save(prefix.with_suffix('.json'),meta)
        self.event('http_end',path=str(prefix.relative_to(ROOT)),metadata_sha256=sha(prefix.with_suffix('.json').read_bytes()))
        return meta,raw

def label_state(meta,raw,p):
    if meta['status']!=200 or meta['transport_error']: return None
    try:
        arr=json.loads(raw)
        assert isinstance(arr,list) and len(arr)<100
        for a in arr:
            if a['name']==p['target']['label']:
                assert a['id']==p['target']['label_id'] and a['node_id']==p['target']['label_node_id']
                return True
        return False
    except Exception: return None

def execute(args):
    import tiktoken
    from verify import verify_source
    verify_source(ROOT)
    p=load(ROOT/'protocol.json'); slots=load(ROOT/'schedule.json')
    assert args.prereg_doi.startswith('10.5281/zenodo.')
    assert args.funding_verified, 'Funding verification required'
    assert not (ROOT/'events.jsonl').exists(), 'Existing run cannot be overwritten or resumed'
    token=os.environ.get('OPENAI_API_KEY',''); assert token.startswith('sk-')
    gh=subprocess.check_output(['gh','auth','token'],text=True).strip(); assert gh
    enc=tiktoken.get_encoding('o200k_base')
    estimates=[len(enc.encode(canonical(request_for(p,s)).decode()))+256 for s in slots]
    assert max(estimates)<=p['budget']['input_estimate_limit']
    total_reserve=sum(reserve(p,s['model']) for s in slots)
    assert total_reserve<p['budget']['hard_usd']
    e=Evidence()
    e.event('run_start',prereg_doi=args.prereg_doi,freeze_commit=(ROOT/'FREEZE_COMMIT.txt').read_text().strip(),
            funding_verified=True,platform=platform.platform(),python=sys.version,
            input_estimate_max=max(estimates),reserved_cost_ceiling_usd=total_reserve)
    base='https://api.github.com/repos/'+p['target']['repository']
    identities=[('repository',base,'id','repository_id'),
                ('issue',base+'/issues/1','id','issue_id'),
                ('label',base+'/labels/rp-gate-trial','id','label_id')]
    for name,url,key,expected in identities:
        meta,raw=e.http('records/identity/'+name,'GET',url,None,gh,'github')
        if meta['status']!=200 or json.loads(raw).get(key)!=p['target'][expected]:
            e.event('run_aborted',reason='FIXTURE_IDENTITY_FAILURE'); return 2
    labels=base+'/issues/1/labels'
    reserved=0.; usage_cost=0.; missing_usage=0
    for s in slots:
        n=s['sequence']; prefix=f'records/{n:03d}'
        e.event('trial_start',sequence=n,slot_id=s['slot_id'])
        m,b=e.http(prefix+'/baseline_initial','GET',labels+'?per_page=100',None,gh,'github')
        state=label_state(m,b,p)
        if state is True:
            dm,db=e.http(prefix+'/fixture_reset','DELETE',labels+'/rp-gate-trial',None,gh,'github')
            m,b=e.http(prefix+'/baseline_reset','GET',labels+'?per_page=100',None,gh,'github')
            state=label_state(m,b,p)
            if dm['status'] not in (200,204): state=None
        if state is not False:
            e.event('run_aborted',sequence=n,reason='FIXTURE_BASELINE_NOT_ABSENT'); return 2
        req=canonical(request_for(p,s))
        reserved+=reserve(p,s['model'])
        if reserved>p['budget']['hard_usd']:
            e.event('run_aborted',reason='BUDGET_LIMIT'); return 2
        m,b=e.http(prefix+'/openai','POST',p['endpoint'],req,token,'openai')
        measurement=parse_response(m['status'],b,s['model'],p)
        if m['transport_error']: measurement['classification']='OP'; measurement['correct_call']=False
        e.event('model_proposal_captured',sequence=n,response_sha256=sha(b))
        decision=authorize(p,s,measurement,True)
        e.event('permission_transition',sequence=n,**decision)
        wrote=False; post_status=None
        if decision['authorized']:
            pm,pb=e.http(prefix+'/protected_write','POST',labels,canonical({'labels':[p['target']['label']]}),gh,'github')
            post_status=pm['status']; wrote=200<=pm['status']<300 and not pm['transport_error']
        rm,rb=e.http(prefix+'/readback','GET',labels+'?per_page=100',None,gh,'github')
        after=label_state(rm,rb,p)
        cost=estimated_cost(p,s['model'],measurement.get('usage'))
        if cost is None: missing_usage+=1
        else: usage_cost+=cost
        record=dict(slot=s,measurement=measurement,authorization=decision,
                    protected_write_attempted=decision['authorized'],protected_write_http_status=post_status,
                    readback_label_present=after,write_success=bool(wrote and after is True),
                    usage_list_price_usd=cost,reserved_cost_usd=reserve(p,s['model']))
        save(ROOT/prefix/'trial.json',record)
        e.event('trial_end',sequence=n,trial_sha256=sha((ROOT/prefix/'trial.json').read_bytes()))
        print(f"{n}/160 {s['model']} {s['rule']}/{s['observed']} {s['pressure']} {measurement['classification']} write={record['write_success']}",flush=True)
        if after is None or after is not decision['authorized']:
            e.event('run_aborted',reason='EXTERNAL_STATE_ANOMALY',sequence=n); return 2
        u=measurement.get('usage') or {}
        if u.get('prompt_tokens',0)>p['budget']['reserved_input_tokens_per_call'] or u.get('completion_tokens',0)>1024:
            e.event('run_aborted',reason='TOKEN_RESERVATION_EXCEEDED',sequence=n); return 2
    e.event('run_end',completed=160,usage_list_price_usd=usage_cost,missing_usage=missing_usage,reserved_cost_usd=reserved)
    e.file.close()
    print(f'COMPLETE: 160 trials; usage list-price USD {usage_cost:.8f}; reservation USD {reserved:.8f}')
    return 0

if __name__=='__main__':
    a=argparse.ArgumentParser(); a.add_argument('--freeze',action='store_true'); a.add_argument('--prereg-doi'); a.add_argument('--funding-verified',action='store_true')
    args=a.parse_args()
    if args.freeze: freeze()
    else: sys.exit(execute(args))
