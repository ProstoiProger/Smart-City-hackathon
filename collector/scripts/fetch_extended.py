"""Bounded, cached public-page collection for missing checklist fields."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import requests
from io import BytesIO
from datetime import datetime,timezone
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
from scripts.download_sources import download, RAW, ROOT,HEADERS

SEEDS=[
 'https://cts.gov.kz/ru/',
 'https://cts.gov.kz/ru/transport/',
 'https://qazaqconcert.kz/ru',
 'https://astanaopera.kz/ru',
 'https://topbilet.kz/ru/city/astana',
 'https://ticketon.kz/astana',
 'https://ailand.kz/ru/',
 'https://ailand.kz/ru/attractions/ocean-ru/',
 'https://astanabotsad.kz/ru',
 'https://qazexpocongress.kz/ru/',
 'https://astana.citypass.kz/ru/attractions/',
 'https://nmrk.kz/ru/',
 'https://astanaballet.com/ru',
 'https://kazhydromet.kz/ru/storm_warning',
]

def fetch(url):
    path=RAW/'extended'/(hashlib.sha256(url.encode()).hexdigest()[:20]+'.html')
    try:
        if urlparse(url).path.lower().endswith('.pdf'):
            from pypdf import PdfReader
            path=path.with_suffix('.pdf');path.parent.mkdir(exist_ok=True)
            if not path.exists():
                response=requests.get(url,headers=HEADERS,timeout=(10,40));response.raise_for_status()
                if not response.content.startswith(b'%PDF'):raise ValueError('Expected PDF response, received a different content type')
                path.write_bytes(response.content)
                path.with_suffix('.pdf.meta.json').write_text(json.dumps({'url':response.url,'collected_at':datetime.now(timezone.utc).isoformat(),'sha256':hashlib.sha256(response.content).hexdigest()},ensure_ascii=False,indent=2),encoding='utf-8')
            reader=PdfReader(path);pages=[p.extract_text(extraction_mode='layout') or '' for p in reader.pages]
            preview=path.with_suffix('.text.txt');preview.write_text('\n\n'.join(pages),encoding='utf-8')
            print(json.dumps({'url':url,'pdf_pages':len(pages),'text_chars':sum(map(len,pages))},ensure_ascii=False),flush=True)
            return {'url':url,'path':path.relative_to(ROOT).as_posix(),'text_path':preview.relative_to(ROOT).as_posix(),'title':urlparse(url).path.rsplit('/',1)[-1],'content_type':'application/pdf','page_count':len(pages),'text_chars':sum(map(len,pages)),'links':[],'json_ld':[]}
        body=download(url,path,timeout=25)
        if 'Ð' in body or 'Ñ' in body:
            try:body=body.encode('latin1').decode('utf-8')
            except UnicodeError:pass
        soup=BeautifulSoup(body,'html.parser')
        links=[]
        for a in soup.select('a[href]'):
            target=urljoin(url,a['href']).split('#')[0]
            if urlparse(target).scheme in ('http','https'):
                links.append({'url':target,'label':a.get_text(' ',strip=True)[:160]})
        ld=[]
        for script in soup.select('script[type="application/ld+json"]'):
            try:ld.append(json.loads(script.string or script.get_text()))
            except (ValueError,TypeError):pass
        for node in soup(['script','style','nav','footer','header']):node.decompose()
        text=soup.get_text('\n',strip=True)
        preview=path.with_suffix('.text.txt');preview.write_text(text,encoding='utf-8')
        row={'url':url,'path':path.relative_to(ROOT).as_posix(),'text_path':preview.relative_to(ROOT).as_posix(),'title':soup.title.get_text(' ',strip=True) if soup.title else None,'text_chars':len(text),'links':links,'json_ld':ld}
        print(json.dumps({'url':url,'title':row['title'],'chars':len(text),'links':len(links),'ld':len(ld)},ensure_ascii=False),flush=True)
        return row
    except Exception as exc:
        print(json.dumps({'url':url,'error':str(exc)},ensure_ascii=False),flush=True)
        return {'url':url,'error':str(exc)}

def main():
    p=argparse.ArgumentParser();p.add_argument('--urls-file');args=p.parse_args()
    urls=json.loads((ROOT/args.urls_file).read_text(encoding='utf-8')) if args.urls_file else SEEDS
    index_path=RAW/'extended_index.json'
    previous=json.loads(index_path.read_text(encoding='utf-8')) if index_path.exists() else []
    byurl={r['url']:r for r in previous}
    with ThreadPoolExecutor(max_workers=4) as pool:
        for row in pool.map(fetch,dict.fromkeys(urls)):byurl[row['url']]=row
    index_path.write_text(json.dumps(list(byurl.values()),ensure_ascii=False,indent=2),encoding='utf-8')

if __name__=='__main__':main()
