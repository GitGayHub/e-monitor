"""Bridge a normal runner handoff only when no monitor/settings job is queued.

One bounded dispatch, no retry after an ambiguous POST, no state/Telegram writes.
The existing concurrency group remains the sole production writer.
"""
import base64
import json
import os
import re
import urllib.request

RELEVANT = {'e-monitor.yml','mobile-sync.yml'}
BUSY = {'queued','pending','waiting','requested','in_progress'}


def decide(mode, runs, current_id):
    if mode.strip()!='normal':return 'mode_not_normal'
    for row in runs:
        if str(row.get('id'))==str(current_id):continue
        path=str(row.get('path','')).split('@',1)[0].rsplit('/',1)[-1]
        if path in RELEVANT and row.get('status') in BUSY:
            return 'already_queued'
    return 'dispatch'


def followup(get, post, current_id, dry_run=False):
    # Read the current main mode, not the job's potentially old checkout.
    mode=base64.b64decode(get('contents/mode.txt?ref=main')['content']).decode('utf8')
    if mode.strip()!='normal':return {'action':'mode_not_normal'}
    # Fifty most recent runs normally cover many hours. A full response is
    # conservative: don't guess no pending work beyond an incomplete page.
    runs=get('actions/runs?per_page=50').get('workflow_runs',[])
    decision=decide(mode,runs,current_id)
    if decision=='dispatch' and len(runs)>=50:
        # Focused status queries prevent old completed QA runs hiding a job.
        for status in ('queued','pending','waiting','in_progress'):
            data=get('actions/runs?per_page=100&status='+status)
            if data.get('total_count',0)>100:return {'action':'queue_unknown'}
            decision=decide(mode,data.get('workflow_runs',[]),current_id)
            if decision!='dispatch':break
    if decision=='dispatch' and not dry_run:
        post('actions/workflows/e-monitor.yml/dispatches',{'ref':'main'})
        return {'action':'dispatch_requested'}
    return {'action':decision,'dryRun':dry_run}


def main():
    repo=os.environ['GITHUB_REPOSITORY']
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',repo):raise ValueError('Invalid repository')
    token=os.environ['GITHUB_TOKEN'];api='https://api.github.com/repos/'+repo+'/'
    def request(path,data=None):
        req=urllib.request.Request(api+path,data=json.dumps(data).encode() if data is not None else None,
            headers={'Authorization':'Bearer '+token,'Accept':'application/vnd.github+json','Content-Type':'application/json'})
        with urllib.request.urlopen(req,timeout=15) as response:
            body=response.read()
            return json.loads(body) if body else {}
    print(json.dumps(followup(request,request,os.environ['GITHUB_RUN_ID'])))


if __name__=='__main__':main()
