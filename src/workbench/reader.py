"""Incremental reply ingestion with durable progress and no automated responses."""
import time
from .store import now
from .errors import ProviderError

def run_reader(store,provider,limit,stop=None):
    started=time.monotonic();seen=set()
    report={'phase':'reading','started_at':now(),'limit':limit,'added':0,'duplicates':0,
            'unique_conversations_checked':0,'matched_contacts':0,'unmatched_conversations':0,
            'incoming_messages_observed':0,'review_cases':[]}
    def progress(detail=None):
        if detail:report.update(detail)
        report['seconds']=round(time.monotonic()-started,1)
        store.setting('last_reader_report',report)
    def ingest(row):
        if row['ident'] in seen:return
        seen.add(row['ident'])
        report['incoming_messages_observed']=len(seen)
        if store.reply(**row):report['added']+=1
        else:report['duplicates']+=1
        progress()
    progress()
    try:
        rows=provider.read(store.list('leads'),limit,on_reply=ingest,on_progress=progress,stop=stop)
        for row in rows:ingest(row) # Demo/fixture providers may return a whole batch.
        report.update(phase='completed',ended_at=now())
        if not report.get('reason'):report['reason']='completed'
        progress()
        return report
    except Exception as exc:
        report.update(phase='failed',ended_at=now(),reason=str(exc) if isinstance(exc,ProviderError) else 'Reader failed: '+type(exc).__name__)
        progress()
        raise
