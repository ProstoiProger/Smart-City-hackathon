"""Probe and collect public-transport routes for fixed public demo landmarks."""
import hashlib
import json
import time
import requests
from scripts.dgis_client import load_key
from scripts.build_dataset import RAW,OUT,NOW,save

ANCHORS={
 'mega':{'name':'MEGA Silk Way','lat':51.0890,'lon':71.4070},
 'airport':{'name':'Astana airport passenger terminal','lat':51.0276,'lon':71.4668},
 'bayterek':{'name':'Bayterek','lat':51.1282882,'lon':71.4304546},
 'museum':{'name':'National Museum','lat':51.1188,'lon':71.4692},
 'opera':{'name':'Astana Opera','lat':51.1354512,'lon':71.410753},
 'ailand':{'name':'Ailand','lat':51.1481229,'lon':71.4167693},
 'alem':{'name':'alem.ai','lat':51.0904,'lon':71.4182},
}

def main():
    key=load_key();directory=RAW/'dgis_transit';directory.mkdir(exist_ok=True)
    endpoint='https://routing.api.2gis.com/public_transport/2.0'
    report={'collected_at':NOW,'source_url':'https://docs.2gis.com/api/navigation/routing/start','requests':0,'cached':0,'errors':[],'successful_pairs':0,'pairs':[]}
    fatal=False
    for a,b in [('mega','airport'),('bayterek','airport'),('museum','airport'),('opera','airport'),('mega','bayterek'),('mega','museum'),('mega','opera'),('mega','ailand'),('bayterek','museum'),('opera','museum'),('ailand','museum'),('alem','bayterek')]:
        for start,end in [(a,b),(b,a)]:
            body={'source':{'point':{k:ANCHORS[start][k] for k in ('lat','lon')}},'target':{'point':{k:ANCHORS[end][k] for k in ('lat','lon')}},'transport':['bus'],'locale':'ru'}
            path=directory/(hashlib.sha256(json.dumps(body,sort_keys=True).encode()).hexdigest()[:20]+'.json')
            if path.exists():
                wrapper=json.loads(path.read_text(encoding='utf-8'));report['cached']+=1
            else:
                try:
                    report['requests']+=1
                    response=requests.post(endpoint,params={'key':key},json=body,timeout=(8,15))
                    try:doc=response.json()
                    except ValueError:doc={}
                    status=doc if isinstance(doc,dict) else {}
                    if response.status_code!=200 or status.get('status') not in ('OK',None) or status.get('type')=='error' or status.get('meta',{}).get('code',200)!=200:
                        report['errors'].append({'http_status':response.status_code,'api_status':status.get('status'),'api_type':status.get('type'),'api_meta_code':status.get('meta',{}).get('code'),'message':str(status.get('message') or status.get('error') or status.get('meta',{}).get('error') or '')[:500].replace(key,'[REDACTED]')});fatal=True;break
                    wrapper={'endpoint':endpoint,'params':body,'collected_at':NOW,'from_anchor':start,'to_anchor':end,'response':doc}
                    path.write_text(json.dumps(wrapper,ensure_ascii=False,indent=2).replace(key,'[REDACTED]'),encoding='utf-8');time.sleep(.2)
                except requests.RequestException:
                    report['errors'].append({'from_anchor':start,'to_anchor':end,'message':'Network request failed; URL with credential omitted'});continue
            report['successful_pairs']+=1;report['pairs'].append({'from_anchor':start,'to_anchor':end,'path':str(path.relative_to(RAW.parent.parent)).replace('\\','/')})
            print('Transit route',start,'->',end,'cached' if path.exists() else '',flush=True)
        if fatal:break
    save(OUT/'dgis_transit_access.json',report)
    save(OUT/'demo_landmarks.json',ANCHORS)
    print(json.dumps({k:v for k,v in report.items() if k!='pairs'},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
