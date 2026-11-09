from .linkedin import LinkedInBrowser


class LiveProvider:
    def __init__(self, settings, store):
        self.linkedin = LinkedInBrowser(settings, store)

    def send(self, lead):
        return self.linkedin.send(lead)

    def read(self, leads, limit=100):
        return self.linkedin.read(leads, limit)
