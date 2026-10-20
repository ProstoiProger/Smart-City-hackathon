"""Download bounded public OSM extracts and the official tourism directory."""
import concurrent.futures
import hashlib
import json
from pathlib import Path
import sys
from datetime import datetime, timezone
import os
from urllib.parse import urljoin, urlparse, urlencode, parse_qs
import time
import re
import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / 'data/raw'
RAW.mkdir(parents=True, exist_ok=True)
sys.stdout.reconfigure(encoding='utf-8')
HEADERS = {'User-Agent': 'AstanaWalkHackathon/1.0 (public city dataset)'}
BBOX = '50.98,71.18,51.34,71.75'
ENDPOINTS = ['https://overpass.kumi.systems/api/interpreter', 'https://overpass-api.de/api/interpreter', 'https://overpass.private.coffee/api/interpreter']

def now():
    return datetime.now(timezone.utc).isoformat()

def download(url, target, params=None, timeout=50):
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    meta = target.with_suffix(target.suffix + '.meta.json')
    if target.exists() and meta.exists() and os.environ.get('ASTANA_REFRESH')!='1':
        return target.read_text(encoding='utf-8')
    r = requests.get(url, params=params, headers=HEADERS, timeout=timeout)
    r.raise_for_status()
    target.write_text(r.text, encoding='utf-8')
    meta.write_text(json.dumps({'url':r.url, 'collected_at':now(), 'status':r.status_code, 'sha256':hashlib.sha256(target.read_bytes()).hexdigest(), 'response_sha256':hashlib.sha256(r.content).hexdigest()},ensure_ascii=False,indent=2),encoding='utf-8')
    return r.text

def osm(name, body):
    target = RAW / f'osm_{name}.json'
    if target.exists() and os.environ.get('ASTANA_REFRESH')!='1':
        return {'name':name,'cached':True}
    query = f'[out:json][timeout:180];({body});out meta center;'
    if name == 'network':
        query = f'[out:json][timeout:180];way[highway]({BBOX});(._;>;);out meta;'
    errors=[]
    for endpoint in ENDPOINTS:
        try:
            text = download(endpoint, target, {'data':query}, timeout=210)
            doc=json.loads(text)
            if doc.get('remark'):
                raise ValueError(doc['remark'])
            print(f'OSM {name}: {len(doc["elements"])} elements',flush=True)
            return {'name':name,'elements':len(doc['elements'])}
        except Exception as exc:
            errors.append(str(exc))
            if target.exists():
                target.unlink()
    return {'name':name,'errors':errors}

def tourism():
    seeds=['https://visitastana.kz/ru/about-city/what-to-see/', 'https://visitastana.kz/ru/about-city/where-to-eat/', 'https://visitastana.kz/ru/coworking/', 'https://visitastana.kz/ru/exhibition-areas/', 'https://visitastana.kz/ru/wellness/', 'https://visitastana.kz/ru/map/', 'https://visitastana.kz/ru/information/transport/']
    pages={}
    queue=list(seeds)
    while queue and len(pages)<450:
        url=queue.pop(0)
        if url in pages: continue
        key=hashlib.sha256(url.encode()).hexdigest()[:16]
        try:
            text=download(url,RAW/'visitastana'/f'{key}.html')
            soup=BeautifulSoup(text,'html.parser')
            pages[url]=(RAW/'visitastana'/f'{key}.html').relative_to(ROOT).as_posix()
            if re.search(r'(?i)(snowbet|slot gacor|togel|mahjong ways|promaxwin)',soup.get_text(' ',strip=True)):
                continue
            if urlparse(url).path=='/ru/about-city/what-to-see/':
                for button in soup.select('[data-category]'):
                    category=button.get('data-category')
                    if category and re.fullmatch('[a-z-]+',category):
                        filtered='https://visitastana.kz/ru/about-city/what-to-see/?'+urlencode({'category':category})
                        if filtered not in pages and filtered not in queue:queue.append(filtered)
                more=soup.select_one('.list__more[data-max]')
                if more:
                    filters={k:v[0] for k,v in parse_qs(urlparse(url).query).items() if k=='category'}
                    for number in range(2,min(int(more['data-max']),30)+1):
                        paged='https://visitastana.kz/ru/about-city/what-to-see/?'+urlencode(filters|{'PAGEN_1':number})
                        if paged not in pages and paged not in queue:queue.append(paged)
            for a in soup.select('a[href]'):
                link=urljoin(url,a['href']).split('#')[0]
                parsed=urlparse(link)
                valid_path=False
                for seed in seeds[:5]:
                    base=urlparse(seed).path
                    if parsed.path.startswith(base):
                        suffix=parsed.path[len(base):].strip('/')
                        valid_path=not suffix or ('/' not in suffix and not parsed.query)
                        if parsed.query:
                            valid_path=not suffix and bool(re.fullmatch(r'PAGEN_\d+=(?:[2-9]|[1-9]\d+)',parsed.query))
                        if valid_path:break
                if parsed.netloc in {'visitastana.kz','www.visitastana.kz'} and valid_path:
                    if link not in pages and link not in queue:
                        queue.append(link)
            print(f'Tourism {len(pages)} queued={len(queue)} {url}',flush=True)
        except Exception as exc:
            print(f'Tourism error {url}: {exc}',flush=True)
        time.sleep(.3)
    (RAW/'tourism_index.json').write_text(json.dumps(pages,ensure_ascii=False,indent=2),encoding='utf-8')
    return {'name':'tourism','pages':len(pages),'remaining':len(queue)}

if __name__=='__main__':
    jobs = [
        ('pois', f'nwr[amenity~"^(cafe|restaurant|fast_food|food_court|bar|pub|ice_cream|biergarten|theatre|cinema|arts_centre|library|community_centre|coworking_space|planetarium|nightclub|social_centre|public_bath|place_of_worship)$"]({BBOX});nwr[tourism]({BBOX});nwr[leisure]({BBOX});nwr[shop~"^(mall|bakery|coffee|confectionery)$"]({BBOX});nwr[historic]({BBOX});'),
        ('infrastructure',f'nwr[highway=bus_stop]({BBOX});nwr[public_transport]({BBOX});nwr[amenity~"^(toilets|shelter|bench|parking|drinking_water)$"]({BBOX});node[entrance]({BBOX});nwr[barrier]({BBOX});'),
        ('network',''),
    ]
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        futures=[pool.submit(osm,*job) for job in jobs[:2]]+[pool.submit(tourism)]
        results=[f.result() for f in futures]
    results.append(osm(*jobs[2]))
    (RAW/'download_report.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(results,ensure_ascii=False,indent=2))
