"""Trial end-to-end run: real handed-over activities + proposed bindings -> SP3 feasibility, planner, checker.

Synthetic student only. The SP3/SP2 code, rule catalog and baseline fixture are read from another checkout:
  python scripts/e2e_real_data_trial.py <path-to-SP3-branch-checkout>
After the branches are integrated, pass the repository root itself. Prints results; writes nothing.
"""
import sys,json
SP3_ROOT=sys.argv[1] if len(sys.argv)>1 else '.'
from copy import deepcopy
from collections import Counter
from datetime import datetime,timedelta
sys.path.insert(0,SP3_ROOT+'/src')
from sp3.feasibility import assess_feasibility, FeasibilityEvidence
from sp3.planner import build_plan
from sp3.plan_checker import check_plan
from sp3.projected_scorer import ProjectedScorer, InMemoryScoringData
from sp3.scorer_adapter import ScorerAdapter
fx=json.load(open(SP3_ROOT+'/tests/sp3/fixtures/main_flow_integration.json',encoding='utf-8'))
rules=json.load(open(SP3_ROOT+'/data/drl_rules.json',encoding='utf-8'))
acts=json.load(open('data/handover/activities_sp3.json',encoding='utf-8'))
side=json.load(open('data/handover/sidecar.json',encoding='utf-8'))
bind=json.load(open('data/handover/bindings.json',encoding='utf-8'))
ev={k:v for k,v in side['demo_evidence'].items() if k!='label'}
bref={b['activity_id']:b['binding_ref'] for b in bind['bindings']}
facts=deepcopy(fx['scoring_data']['baselines'][0]['facts'])
byid={r['rule_id']:r for r in rules['rules']}
for b in bind['bindings']:
    if b['operation']=='INCREMENT': facts.setdefault(b['field'],0)
sd={"label":"real-activities-synthetic-student","dataset_version":"sp1-store-v2","ruleset_version":fx['scoring_data']['ruleset_version'],"ruleset":rules,
    "baselines":[{"student_id":"synthetic-student-k24","baseline_ref":"synthetic-baseline-k24","facts":facts}],"activities":acts,"bindings":bind['bindings']}
def mk(): return ScorerAdapter(ProjectedScorer(InMemoryScoringData(sd))).score_plan
def intervals(mode):
    out=[];d=datetime.fromisoformat("2026-10-01T00:00:00+07:00");end=datetime.fromisoformat("2026-11-16T00:00:00+07:00")
    if mode=='all': return [{"start":d.isoformat(),"end":end.isoformat()}]
    while d<end:
        if d.weekday()>=5: out.append({"start":(d+timedelta(hours=7)).isoformat(),"end":(d+timedelta(hours=21)).isoformat()})
        else: out.append({"start":(d+timedelta(hours=17,minutes=30)).isoformat(),"end":(d+timedelta(hours=21)).isoformat()})
        d+=timedelta(days=1)
    return out
def run(mode,target=80):
    av=intervals(mode)
    req={"contract_version":"sp3-planner/0.2","request_id":"real-"+mode,"context":{"student_id":"synthetic-student-k24","term_id":"HK1_2026_2027","window_start":"2026-10-01T00:00:00+07:00","window_end":"2026-11-16T00:00:00+07:00","as_of":"2026-10-01T08:00:00+07:00","timezone":"Asia/Ho_Chi_Minh","baseline_ref":"synthetic-baseline-k24","dataset_version":"sp1-store-v2","ruleset_version":sd['ruleset_version'],"calendar_version":"synthetic-"+mode},
     "activities":[{"activity":a,"score_binding_ref":bref.get(a['activity_id']),"participation":{"registration":"NOT_REGISTERED","progress":"NOT_STARTED"}} for a in acts],"available_intervals":av}
    fe=assess_feasibility(req,evidence=FeasibilityEvidence(**ev))
    st=Counter(c['feasibility']['status'] for c in fe['candidates'])
    opts=deepcopy(fx['planner']); opts['goals']={"total_target":target,"category_targets":{}}; opts['preferences']={"preferred_domains":[],"preferred_modes":[]}
    pi={"contract_version":fe['contract_version'],"request_id":"real-"+mode,"context":deepcopy(fe['context']),**opts,"candidates":deepcopy(fe['candidates']),"conflict_pairs":deepcopy(fe['conflict_pairs']),"available_intervals":deepcopy(av),"previous_plan":None,"keep_requests":[]}
    snap=deepcopy(pi); plan=build_plan(pi,mk()); viol=check_plan(pi,plan,mk(),input_snapshot=snap)
    return st,plan,viol,fe
if __name__=="__main__":
    for mode,target in (('all',80),('evenings_weekends',80),('evenings_weekends',100)):
        st,plan,viol,fe=run(mode,target)
        ss=plan['score_summary']
        print('==',mode,'target',target,dict(st),'| status',plan['status'],'| checker violations',len(viol),'|',plan['feasibility_conclusion'])
        print('   score',json.dumps(ss,ensure_ascii=False)[:420])
        for x in plan['selected_activities']: print('   +',x['activity_id'],x['scheduled_blocks'][0]['start'][:16],x['scheduled_blocks'][0]['end'][11:16],'|',json.dumps({k:x[k] for k in x if k not in ('scheduled_blocks','activity_id')},ensure_ascii=False)[:160])
        print('   excluded',Counter(e.get('code') for e in plan['excluded_candidates']), [w['code'] for w in plan['warnings']], plan['errors'][:2])
