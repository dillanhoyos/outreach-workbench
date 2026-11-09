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

    @classmethod
    def from_env(cls):
        mode = os.getenv('WORKBENCH_MODE', 'demo')
        if mode not in ('demo', 'live'):
            raise ValueError('WORKBENCH_MODE must be demo or live')
        token = os.getenv('WORKBENCH_TOKEN', '')
        if len(token) < 24:
            raise ValueError('Run python scripts/setup.py to generate WORKBENCH_TOKEN')
        limit = int(os.getenv('DAILY_SEND_LIMIT', '10'))
        if not 1 <= limit <= 100:
            raise ValueError('DAILY_SEND_LIMIT must be between 1 and 100')
        return cls(Path(os.getenv('WORKBENCH_DATA', './data')), token, mode,
                   os.getenv('SELENIUM_URL', 'http://browser:4444'), limit,
                   os.getenv('APOLLO_API_KEY', ''), os.getenv('GOOGLE_SHEET_ID', ''),
                   os.getenv('GOOGLE_APPLICATION_CREDENTIALS', ''))
