"""Fetch public OSM transit relations, including ordered members and geometry."""
import json
from scripts.download_sources import RAW, BBOX, ENDPOINTS, download

def main():
    path=RAW/'osm_transit.json'
    query=f'[out:json][timeout:120];rel[route~"^(bus|trolleybus|tram|light_rail|subway)$"]({BBOX});out meta geom;'
    errors=[]
    for endpoint in ENDPOINTS:
        try:
            body=download(endpoint,path,{'data':query},timeout=140)
            doc=json.loads(body)
            if doc.get('remark'):raise RuntimeError(doc['remark'])
            print('OSM transit relations:',len(doc.get('elements',[])),flush=True)
            return
        except Exception as exc:errors.append(str(exc))
    raise RuntimeError('; '.join(errors))

if __name__=='__main__':main()
