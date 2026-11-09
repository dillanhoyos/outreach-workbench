"""Two read-only web producers; the calling thread alone owns LinkedIn and CRM saves."""
import copy
import threading
from concurrent.futures import ThreadPoolExecutor, Future, wait, FIRST_COMPLETED
from .errors import ProviderError


class CombinedStop:
    def __init__(self,*events):self.events=events
    def is_set(self):return any(e.is_set() for e in self.events)


class SourceCache:
    def __init__(self):self.lock=threading.Lock();self.entries={}
    def get(self,url,build):
        with self.lock:
            owner=url not in self.entries
            if owner:self.entries[url]=Future()
            future=self.entries[url]
        if owner:
            try:future.set_result(build())
            except BaseException as exc:future.set_exception(exc)
        return future.result()


class WebPool:
    def __init__(self,engine,plan,run_id,guard):
        self.engine=engine;self.plan=plan;self.run_id=run_id;self.guard=guard
        self.cancel=threading.Event();self.cache=SourceCache()
        self.executor=ThreadPoolExecutor(max_workers=2,thread_name_prefix='research-web')
        self.futures=[]
    def worker(self,index,plan):
        from .research_web import discover
        worker=copy.copy(self.engine)
        worker.browser=None
        worker.stop=CombinedStop(self.engine.stop,self.cancel)
        worker.event=lambda run_id,kind,detail:self.engine.event(run_id,kind,{**detail,'worker':index})
        def guard():
            if worker.stop.is_set():raise ProviderError('Web work canceled.')
            self.guard()
        worker.event(self.run_id,'web_worker_started',{'reason':f'Web worker {index} researching its assigned queries.'})
        try:
            guard()
            result=discover(worker,plan,self.run_id,guard,shared=self.cache)
            worker.event(self.run_id,'web_worker_finished',{'reason':f'Web worker {index} prepared {len(result)} candidates.'})
            return result
        except Exception as exc:
            worker.event(self.run_id,"web_worker_canceled",{"reason":f"Web worker {index} stopped."})
            if not worker.stop.is_set():
                self.engine._web_failure=exc if isinstance(exc,ProviderError) else ProviderError('Web worker failed. Research stopped without retry.')
                self.engine.stop.set()
            raise
    def batches(self,plan):
        queries=plan['queries']
        self.futures=[self.executor.submit(self.worker,i+1,{**plan,'queries':queries[i::2] or queries,
            'prompt':plan['prompt']+f'\nSearch lane {i+1}: '+('use the most direct official directory matches.' if i==0 else 'seek alternative qualifying companies and less obvious matches.')}) for i in range(2)]
        pending=set(self.futures)
        while pending:
            self.guard()
            done,pending=wait(pending,timeout=.3,return_when=FIRST_COMPLETED)
            for future in done:
                self.guard()
                yield future.result()
    def close(self):
        self.cancel.set()
        for future in self.futures:future.cancel()
        self.executor.shutdown(wait=True,cancel_futures=True)
