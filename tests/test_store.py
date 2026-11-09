import pytest
from workbench.store import Store, profile_key
from workbench.demo import DemoProvider


def seed(tmp_path):
    store=Store(tmp_path)
    for x in DemoProvider().discover('finance'):store.add_lead(x)
    return store


def test_duplicate_url_and_invalid_hosts(tmp_path):
    s=seed(tmp_path)
    person=DemoProvider().discover('finance')[0]
    person['url']+='/?trk=test'
    assert not s.add_lead(person)
    assert len(s.list('leads'))==10
    for u in ['https://evil.com/in/person','https://www.linkedin.com.evil.com/in/person','https://user@linkedin.com/in/person','https://linkedin.com/company/foo']:
        with pytest.raises(ValueError):profile_key(u)


def test_reservation_requires_approval_and_never_replays(tmp_path):
    s=seed(tmp_path);lead=s.list('leads')[0]
    with pytest.raises(ValueError):s.reserve(lead['id'],10)
    s.approve(lead['id'],'Hello. Would you like to connect?')
    s.reserve(lead['id'],10)
    with pytest.raises(ValueError):s.reserve(lead['id'],10)
    restarted=Store(tmp_path)
    assert restarted.list('deliveries')[0]['status']=='uncertain'
    with pytest.raises(ValueError):restarted.approve(lead['id'],'Try again')


def test_daily_limit_and_company_hold(tmp_path):
    s=seed(tmp_path);a,b=s.list('leads')[:2]
    for x in (a,b):s.approve(x['id'],'Hello')
    s.reserve(a['id'],1)
    with pytest.raises(ValueError,match='Daily'):s.reserve(b['id'],1)
    with s.db() as db:db.execute('INSERT INTO holds VALUES(?,?)',(b['company'].casefold(),'Already replied'))
    with pytest.raises(ValueError,match='hold'):s.reserve(b['id'],100)


def test_demo_replies_idempotent(tmp_path):
    s=seed(tmp_path);p=DemoProvider();lead=s.list('leads')[0]
    s.approve(lead['id'],'Hello');reserved=s.reserve(lead['id'],10)
    receipt=p.send(reserved);s.delivery(lead['id'],**receipt)
    rows=p.read(s.list('leads'))
    assert len(rows)==1
    assert s.reply(**rows[0])
    assert not s.reply(**rows[0])
    assert len(s.list('replies'))==1
