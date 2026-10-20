import concurrent.futures
import json
from pathlib import Path
import sys
import requests

sys.stdout.reconfigure(encoding='utf-8')
ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / 'data' / 'raw'
RAW.mkdir(parents=True, exist_ok=True)
session = requests.Session()
session.headers['User-Agent'] = 'AstanaWalkHackathon/1.0 (public-data research)'

def fetch(item):
    name, url, params = item
    try:
        r = session.get(url, params=params, timeout=90)
        (RAW / (name + '.txt')).write_text(r.text, encoding='utf-8')
        return {'name': name, 'status': r.status_code, 'url': r.url, 'length': len(r.content), 'preview': r.text[:250]}
    except Exception as exc:
        return {'name': name, 'error': str(exc)}

jobs = [
    ('osm_probe', 'https://overpass-api.de/api/interpreter', {'data':'[out:json][timeout:60];rel["boundary"="administrative"]["name:en"="Astana"];out tags bb;'}),
    ('visit_robots', 'https://visitastana.kz/robots.txt', None),
    ('visit_home', 'https://visitastana.kz/ru/', None),
    ('visit_sitemap', 'https://visitastana.kz/sitemap.xml', None),
    ('weather', 'https://api.open-meteo.com/v1/forecast', {'latitude':51.1282,'longitude':71.4304,'current':'temperature_2m,apparent_temperature,precipitation,weather_code,wind_speed_10m','hourly':'temperature_2m,apparent_temperature,precipitation_probability,precipitation,wind_speed_10m','daily':'sunset,sunrise','timezone':'Asia/Almaty','forecast_days':7}),
    ('egov_robots', 'https://data.egov.kz/robots.txt', None),
]
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
    for result in pool.map(fetch, jobs):
        print(json.dumps(result, ensure_ascii=False), flush=True)
