import json
import subprocess
from pathlib import Path

from fastapi.testclient import TestClient
from workbench.app import create_app
from workbench.config import Settings


def test_complete_activity_log_and_summary_are_scoped_and_authenticated(tmp_path):
    app=create_app(Settings(tmp_path,'x'*32,'demo','',10,'',''))
    with app.state.store.db() as db:
        for i in range(125):
            db.execute('INSERT INTO research_events(run_id,kind,detail,created) VALUES(?,?,?,?)',
                ('run-a','web_search',json.dumps({'worker':1,'query':str(i)}),'2026-11-10T12:00:00+00:00'))
        db.execute('INSERT INTO research_events(run_id,kind,detail,created) VALUES(?,?,?,?)',
            ('run-b','visiting','{}','2026-11-10T12:01:00+00:00'))
    with TestClient(app) as client:
        assert client.get('/api/discovery/events?run_id=run-a').status_code==401
        client.headers['Authorization']='Bearer '+'x'*32
        rows=client.get('/api/discovery/events?run_id=run-a').json()
        assert len(rows)==125 and all(r['run_id']=='run-a' for r in rows)
        assert rows[0]['id']>rows[-1]['id']
        state=client.get('/api/discovery/state').json()
        assert len(state['events'])==80
        assert state['activity']['run_id']=='run-b'
        assert state['activity']['event_count']==1 and state['activity']['visited']==1
        assert state['activity']['lanes']['LinkedIn browser']['kind']=='visiting'
        assert client.get('/api/discovery/events?run_id=unknown').json()==[]


def test_health_distinguishes_progress_app_connectivity_and_terminal_runs():
    js=(Path(__file__).parents[1]/'src/workbench/static/workbench.js').read_text()
    functions=js[js.index('function activityAge'):js.index('function renderResearchHealth')]
    script="""
const assert=require('assert');
const now=Date.parse('2026-11-10T12:10:00Z');
let researchPollAt=now;
let researchState={active:true,server_time:new Date(now).toISOString(),
 activity:{started_at:'2026-11-10T12:00:00Z',last_event_at:'2026-11-10T12:09:55Z'}};
"""+functions+"""
assert.equal(researchHealth(now).title,'Recent progress recorded');
researchState.activity.last_event_at='2026-11-10T12:08:00Z';
assert.equal(researchHealth(now).title,'Waiting for the next step');
researchState.activity.last_event_at='2026-11-10T12:05:00Z';
assert.equal(researchHealth(now).title,'Progress needs attention');
researchPollAt=now-13000;
assert.equal(researchHealth(now).title,'Connection interrupted');
researchState.active=false;
assert.equal(researchHealth(now).title,'Run ended');
assert.equal(researchHealth(now).elapsed,300);
"""
    subprocess.run(['node','-e',script],check=True)
