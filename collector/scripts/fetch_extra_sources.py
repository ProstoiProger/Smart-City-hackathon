"""Fetch a small, explicit set of primary-source pages and catalogue metadata."""
import hashlib
import json
from urllib.parse import urlparse
from scripts.download_sources import download, RAW, ROOT

URLS=[
 'https://nmrk.kz/robots.txt',
 'https://nmrk.kz/ru/',
 'https://nmrk.kz/ru/press/museum-rules/',
 'https://nmrk.kz/ru/press/accessible-museum/',
 'https://nmrk.kz/ru/press/third-sunday/',
 'https://nmrk.kz/ru/press/rules-for-children/',
 'https://nmrk.kz/ru/press/affiche/',
 'https://nmrk.kz/ru/press/affiche/966/',
 'https://nmrk.kz/ru/press/affiche/963/',
 'https://nmrk.kz/ru/press/affiche/954/',
 'https://nmrk.kz/ru/press/affiche/953/',
 'https://nmrk.kz/ru/press/affiche/950/',
 'https://kazakhstan.travel/robots.txt',
 'https://kazakhstan.travel/ru/attractions/423',
 'https://data.egov.kz/datasets/view?index=parkter_turaly_akparat',
 'https://data.egov.kz/datasets/view?index=sayabaktar_turaly_derekter',
 'https://data.egov.kz/pages/samples',
 'https://visitastana.kz/ru/about-city/what-to-see/natsionalnyy-muzey-respubliki-kazakhstan/',
]

if __name__=='__main__':
    results=[]
    for url in URLS:
        path=RAW/'extra'/(hashlib.sha256(url.encode()).hexdigest()[:16]+'.html')
        try:
            text=download(url,path,timeout=30)
            results.append({'url':url,'path':path.relative_to(ROOT).as_posix(),'bytes':len(text)})
            print(url,len(text),flush=True)
        except Exception as exc:results.append({'url':url,'error':str(exc)})
    (RAW/'extra_index.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
