import os
from dataclasses import dataclass
from pathlib import Path

@dataclass(frozen=True)
class Settings:
    data_dir: Path
    token: str
    mode: str
    selenium_url: str
    daily_limit: int
    apollo_key: str
    sheet_id: str
    google_credentials: str
    browser_advisor: str = "none"
    typesafe_key: str = ""

    @classmethod
    def from_env(cls):
        mode = os.getenv('WORKBENCH_MODE', 'demo')
        if mode not in ('demo', 'live'):
            raise ValueError('WORKBENCH_MODE must be demo or live')
        token = os.getenv('WORKBENCH_TOKEN', '')
        if len(token) < 24 or token == 'replace-with-a-random-token-of-at-least-24-characters':
            raise ValueError('Run python scripts/setup.py to generate WORKBENCH_TOKEN')
        advisor = os.getenv('BROWSER_ADVISOR', 'none')
        if advisor not in ('none', 'jev'):
            raise ValueError('BROWSER_ADVISOR must be none or jev')
        key = os.getenv('TYPESAFE_API_KEY', '')
        if mode == 'live' and advisor == 'jev' and not key:
            raise ValueError('Set TYPESAFE_API_KEY to your own TypeSafe API key, or set BROWSER_ADVISOR=none')
        limit = int(os.getenv('DAILY_SEND_LIMIT', '10'))
        if not 1 <= limit <= 100:
            raise ValueError('DAILY_SEND_LIMIT must be between 1 and 100')
        return cls(Path(os.getenv('WORKBENCH_DATA', './data')), token, mode,
                   os.getenv('SELENIUM_URL', 'http://browser:4444'), limit,
                   os.getenv('APOLLO_API_KEY', ''), os.getenv('GOOGLE_SHEET_ID', ''),
                   os.getenv('GOOGLE_APPLICATION_CREDENTIALS', ''), advisor, key)
