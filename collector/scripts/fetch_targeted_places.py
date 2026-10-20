"""Small explicit set of landmark searches to resolve missing attraction identities."""
import hashlib
import json
import time
from scripts.collect_dgis import FIELDS
from scripts.dgis_client import DgisClient,DgisError
from scripts.build_dataset import RAW,OUT,NOW,save

QUERIES=['Музей Сингулярности','Оранжерейный комплекс','Океанариум','Джунгли','Музей железной дороги','Астанинский цирк','Нур Алем']
def main():
    client=DgisClient(max_requests=10);report=[]
    for query in QUERIES:
        params={'q':query,'region_id':68,'type':'branch','locale':'ru_KZ','page_size':10,'page':1,'fields':FIELDS}
        path=RAW/'dgis'/(hashlib.sha256(json.dumps(params,sort_keys=True,ensure_ascii=False).encode()).hexdigest()[:24]+'.json')
        try:
            if path.exists():wrapper=json.loads(path.read_text(encoding='utf-8'))
            else:
                doc=client.request('items',**params)
                wrapper={'endpoint':'https://catalog.api.2gis.com/3.0/items','params':params,'collected_at':NOW,'response':doc}
                path.write_text(json.dumps(wrapper,ensure_ascii=False,indent=2).replace(client._key,'[REDACTED]'),encoding='utf-8');time.sleep(.15)
            items=wrapper.get('response',{}).get('result',{}).get('items',[])
            report.append({'query':query,'returned_count':len(items),'items':[{'id':x.get('id'),'name':x.get('name'),'point':x.get('point')} for x in items]})
            print(query,[(x.get('id'),x.get('name')) for x in items],flush=True)
        except DgisError as exc:
            report.append({'query':query,'error':str(exc)})
            if 'API 404' not in str(exc):break
    save(OUT/'targeted_places_report.json',report)

if __name__=='__main__':main()
