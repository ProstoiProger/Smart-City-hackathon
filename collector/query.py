"""Inspect the local dataset, or explicitly request live 2GIS results."""
import argparse
import json
from pathlib import Path
import sqlite3
import sys
from scripts.build_dataset import distance

def main():
    sys.stdout.reconfigure(encoding='utf-8')
    ap=argparse.ArgumentParser()
    ap.add_argument('--text',default='')
    ap.add_argument('--category')
    ap.add_argument('--lat',type=float)
    ap.add_argument('--lon',type=float)
    ap.add_argument('--limit',type=int,default=5)
    ap.add_argument('--from-poi',help='Show stored candidate walking routes from this POI ID')
    ap.add_argument('--2gis',dest='use_dgis',action='store_true',help='One live Places API query, without saving provider results')
    ap.add_argument('--2gis-id',dest='dgis_id',help='Fetch one live 2GIS place by its external ID')
    ap.add_argument('--radius',type=int,default=2000,help='Live 2GIS search radius in metres')
    args=ap.parse_args()
    if args.use_dgis or args.dgis_id:
        if args.from_poi or args.category:
            ap.error('Live 2GIS mode uses --text or --2gis-id, not local category/route filters.')
        from scripts.dgis_live import search_live,details_live
        from scripts.dgis_client import DgisError
        try:
            if args.dgis_id:
                result=details_live(args.dgis_id)
            else:
                if args.lat is None or args.lon is None:ap.error('--2gis requires --lat and --lon')
                result=search_live(args.text,args.lat,args.lon,min(args.limit,10),args.radius)
        except (DgisError,ValueError,RuntimeError) as exc:
            ap.exit(1,str(exc)+'\n')
        print(json.dumps(result,ensure_ascii=False,indent=2))
        return
    db=sqlite3.connect(Path(__file__).resolve().parent/'data/processed/smart_city.sqlite')
    if args.from_poi:
        for row in db.execute('SELECT payload_json FROM walking_routes WHERE from_poi_id=? ORDER BY walking_distance_m LIMIT ?',(args.from_poi,args.limit)):
            r=json.loads(row[0]);r.pop('path_node_ids',None)
            print(json.dumps(r,ensure_ascii=False,indent=2))
        return
    sql='SELECT p.payload_json FROM pois p';values=[];conditions=[]
    if args.text:
        sql+=' JOIN poi_search s ON s.poi_id=p.poi_id'
        # Treat user text as literal words, not arbitrary FTS operators.
        query=' AND '.join('"'+word.replace('"','""')+'"' for word in args.text.split())
        conditions.append('poi_search MATCH ?');values.append(query)
    if args.category:conditions.append('p.category=?');values.append(args.category)
    if conditions:sql+=' WHERE '+' AND '.join(conditions)
    rows=[json.loads(row[0]) for row in db.execute(sql,values)]
    rows=[p for p in rows if p.get('operational_status') not in ('temporarily_closed','permanently_closed','temporarily_closed_as_reported_by_2gis','opening_soon_as_reported_by_2gis','removed_from_provider_catalog')]
    if args.lat is not None and args.lon is not None:
        for p in rows:p['straight_line_distance_m']=round(distance((args.lat,args.lon),(p['latitude'],p['longitude'])),1)
        rows.sort(key=lambda p:p['straight_line_distance_m'])
    for p in rows[:args.limit]:
        print(json.dumps({k:p.get(k) for k in ('poi_id','display_name','category','address','latitude','longitude','straight_line_distance_m','opening_hours','opening_hours_by_day','short_description','description_type','source_url','operational_status','power_outlets','quiet_place','quiet_place_scope','rating','ratings_count','rating_source','wifi_available','laptop_friendly','wheelchair_accessible','adult_ticket_price','child_ticket_price','reservation_available')},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
