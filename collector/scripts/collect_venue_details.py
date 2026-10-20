"""Refresh every linked provider ID in documented batches, without logging credentials."""
import hashlib
import json
import time
import re
from scripts.build_dataset import RAW,OUT,NOW,load,save
from scripts.dgis_client import DgisClient,DgisError

FIELDS='items.point,items.flags,items.is_deleted,items.dates,items.attribute_groups,items.contact_groups,items.access_comment,items.access,items.is_paid'

def main():
    ps=[json.loads(x) for x in (OUT/'pois.jsonl').read_text(encoding='utf-8').splitlines()]
    ids=sorted({m[1] for p in ps if (m:=re.search(r'(?:firm/)?(\d{10,})',str(p.get('external_ids',{}).get('2gis',''))))})
    raw=RAW/'venue_details';raw.mkdir(exist_ok=True);client=DgisClient(max_requests=500)
    pending=ids[:];size=100;report={'started_at':NOW,'requested_unique_ids':len(ids),'returned_unique_ids':[],'batches':[],'errors':[],'complete':False}
    returned=set()
    while pending:
        batch=pending[:size];params={'id':','.join(batch),'locale':'ru_KZ','fields':FIELDS}
        path=raw/(hashlib.sha256(json.dumps(params,sort_keys=True).encode()).hexdigest()[:24]+'.json')
        try:
            if path.exists():wrapper=load(path)
            else:
                doc=client.request('items/byid',**params)
                wrapper={'endpoint':'https://catalog.api.2gis.com/3.0/items/byid','params':params,'collected_at':NOW,'response':doc}
                path.write_text(json.dumps(wrapper,ensure_ascii=False,indent=2).replace(client._key,'[REDACTED]'),encoding='utf-8');time.sleep(.4)
            items=wrapper.get('response',{}).get('result',{}).get('items',[])
            found={str(x['id']).split('_')[0] for x in items if x.get('id')};returned|=found
            report['batches'].append({'path':path.relative_to(RAW.parent.parent).as_posix(),'requested_ids':batch,'returned_ids':sorted(found),'missing_ids':sorted(set(batch)-found)})
            pending=pending[len(batch):]
        except DgisError as exc:
            if 'API 400' in str(exc) and size>10:size=10;continue
            if 'network request failed' in str(exc) and size>1:
                size=max(1,size//2);print('Reducing batch size to',size,'after network failure',flush=True);continue
            report['errors'].append(str(exc));break
        report.update({'returned_unique_ids':sorted(returned),'pending_ids':pending,'requests_made':client.requests_made})
        save(OUT/'venue_details_collection_report.json',report)
        if len(report['batches'])%10==0:print('Venue details checked',len(ids)-len(pending),'/',len(ids),'returned',len(returned),'requests',client.requests_made,flush=True)
    report.update({'returned_unique_ids':sorted(returned),'pending_ids':pending,'requests_made':client.requests_made,'complete':not pending,'finished_at':NOW})
    save(OUT/'venue_details_collection_report.json',report)
    print(json.dumps({'requested':len(ids),'returned':len(returned),'pending':len(pending),'requests':client.requests_made,'complete':not pending,'errors':report['errors']},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
