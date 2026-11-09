from .discovery import ApolloDiscovery
from .linkedin import LinkedInBrowser

class LiveProvider:
    def __init__(self,settings,store):
        self.discovery=ApolloDiscovery(settings.apollo_key)
        self.linkedin=LinkedInBrowser(settings,store)
    def discover(self,*args,**kwargs):return self.discovery.discover(*args,**kwargs)
    def send(self,lead):return self.linkedin.send(lead)
    def read(self,leads,limit=100):return self.linkedin.read(leads,limit)
