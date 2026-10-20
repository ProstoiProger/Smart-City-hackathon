"""Public Wikidata identity metadata, Commons rights and official storm warnings."""
import hashlib
import json
import re
import requests
from scripts.download_sources import download,HEADERS
from scripts.build_dataset import RAW,OUT,NOW,load,save

def main():
    directory=RAW/'supplementary';directory.mkdir(exist_ok=True)
    pois=[json.loads(x) for x in (OUT/'pois.jsonl').read_text(encoding='utf-8').splitlines()]
    qids=sorted({q for p in pois for q in re.findall(r'Q\d+',p.get('raw_osm_tags',{}).get('wikidata',''))})
    report=[]
    if qids:
        try:
            params={'action':'wbgetentities','format':'json','ids':'|'.join(qids),'props':'labels|descriptions|claims','languages':'ru|kk|en'}
            doc=json.loads(download('https://www.wikidata.org/w/api.php',directory/'wikidata.json',params,timeout=30))
            files=[]
            for e in doc.get('entities',{}).values():
                for claim in e.get('claims',{}).get('P18',[])[:2]:
                    value=claim.get('mainsnak',{}).get('datavalue',{}).get('value')
                    if value:files.append('File:'+value)
            if files:
                download('https://commons.wikimedia.org/w/api.php',directory/'commons_images.json',{'action':'query','format':'json','prop':'imageinfo','titles':'|'.join(dict.fromkeys(files)),'iiprop':'url|extmetadata','iiurlwidth':1000},timeout=30)
            report.append({'source':'Wikidata + Commons','requested_entities':len(qids),'image_files':len(files)})
        except Exception as exc:report.append({'source':'Wikidata + Commons','error':str(exc)})
    path=directory/'storm_astana.json'
    try:
        if not path.exists():
            endpoint='https://www.kazhydromet.kz/ajax_storm.php'
            params={'date':'','region':'20','year':'','lang':'ru','page':1,'isInArchive':0}
            r=requests.post(endpoint,data=params,headers=HEADERS,timeout=(10,30));r.raise_for_status();doc=r.json()
            save(path,{'endpoint':endpoint,'params':params,'collected_at':NOW,'response':doc})
            save(path.with_suffix('.json.meta.json'),{'url':endpoint,'collected_at':NOW,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
        else:doc=load(path,{})['response']
        report.append({'source':'Kazhydromet storm API','keys':list(doc),'count':doc.get('count'),'region_filter':doc.get('filters'),'sample':doc.get('items',[])[:1]})
    except Exception as exc:report.append({'source':'Kazhydromet storm API','error':str(exc)})
    save(OUT/'supplementary_fetch_report.json',report)
    print(json.dumps(report,ensure_ascii=False,indent=2)[:4500])

if __name__=='__main__':main()
