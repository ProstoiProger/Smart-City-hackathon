"""2GIS client. Credentials stay in memory and never enter logs or cache URLs."""
from pathlib import Path
import os
import requests

ROOT = Path(__file__).resolve().parents[1]
API_BASE = 'https://catalog.api.2gis.com/3.0/'

def load_key(env_path=None):
    key = os.environ.get('DGIS_API_KEY', '').strip()
    path = Path(env_path) if env_path else ROOT / '.env'
    if not key and path.exists():
        for line in path.read_text(encoding='utf-8-sig').splitlines():
            name, sep, value = line.strip().removeprefix('export ').partition('=')
            if sep and name.strip() == 'DGIS_API_KEY':
                key = value.strip().strip('\"').strip("'")
    if not key or key in {'your_key_here', 'твой_ключ'}:
        raise RuntimeError('DGIS_API_KEY is missing or contains a placeholder.')
    return key

class DgisError(RuntimeError):
    pass

class DgisClient:
    def __init__(self, key=None, max_requests=5):
        self._key = key or load_key()
        self.max_requests = max_requests
        self.requests_made = 0
        self.session = requests.Session()
        self.session.headers['User-Agent'] = 'AstanaWalkHackathon/1.0'

    def request(self, method, **params):
        if method not in {'items', 'items/byid'}:
            raise DgisError('Unsupported API method.')
        if self.requests_made >= self.max_requests:
            raise DgisError('Local request cap reached; no further requests sent.')
        self.requests_made += 1
        try:
            response = self.session.get(API_BASE + method, params={**params, 'key': self._key}, timeout=(10, 30))
        except requests.RequestException as exc:
            # requests exceptions can contain the full URL and its secret key.
            raise DgisError(f'2GIS network request failed ({type(exc).__name__}); credential-bearing URL omitted.') from None
        try:
            data = response.json()
        except ValueError:
            raise DgisError(f'2GIS returned non-JSON data (HTTP {response.status_code}).') from None
        code = data.get('meta', {}).get('code', response.status_code)
        if response.status_code != 200 or code != 200:
            error = data.get('meta', {}).get('error', {})
            error_type = error.get('type', 'unknown') if isinstance(error, dict) else 'unknown'
            safe_type = str(error_type).replace(self._key, '[REDACTED]')[:100]
            detail = str(error.get('message','') if isinstance(error,dict) else '').replace(self._key,'[REDACTED]')[:350]
            raise DgisError(f'2GIS access failed: HTTP {response.status_code}, API {code}, type={safe_type}. {detail}')
        return data
