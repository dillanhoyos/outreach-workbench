"""Safe, user-visible provider errors; never include provider bodies or secrets."""
class ProviderError(RuntimeError):
    pass


class ProfileIdentityError(ProviderError):
    """One candidate could not be confirmed; never use the redirected evidence."""
    def __init__(self, requested_url, observed_url):
        super().__init__('LinkedIn redirected this profile. Its identity could not be confirmed; skipped and continuing research.')
        self.requested_url=requested_url
        self.observed_url=observed_url


def check_response(response, provider):
    if response.status_code == 429:
        raise ProviderError(f'{provider} rate limit reached. Stopped without retry; wait for the provider limit to reset.')
    if response.status_code in (401,403):
        raise ProviderError(f'{provider} authentication or permission denied. Check your connection settings.')
    if not 200 <= response.status_code < 300:
        raise ProviderError(f'{provider} returned HTTP {response.status_code}. No automatic retry.')
    return response.json()
