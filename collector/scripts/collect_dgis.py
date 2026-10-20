"""Resumable 2GIS city POI collection using documented Places API pagination."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import time
import sys
from scripts.dgis_client import DgisClient,DgisError,ROOT
sys.stdout.reconfigure(encoding='utf-8')

RAW=ROOT/'data/raw/dgis'
OUT=ROOT/'data/processed'
QUERIES=['Кофейни','Кафе','Пекарни','Рестораны','Быстрое питание','Семейные рестораны','Парки','Скверы','Набережные','Ботанический сад','Достопримечательности','Памятники','Музеи','Галереи','Театры','Концертные залы','Кинотеатры','Виртуальная реальность','Развлекательные центры','Детские игровые залы','Детские площадки','Катки','Бассейны','Спортивные комплексы','Торговые центры','Фуд-корты','Смотровые площадки','Библиотеки','Коворкинги','Бары','Ночные клубы','Общественные туалеты','Остановки общественного транспорта']
FIELDS='items.point,items.address,items.full_address_name,items.rubrics,items.schedule,items.schedule_special,items.reviews,items.attribute_groups,items.dates,items.description,items.name_ex,items.org,items.links,items.flags'
BBOX=(50.98,71.18,51.34,71.75)

def now():return datetime.now(timezone.utc).isoformat()

def write(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--max-requests',type=int,default=950)
    parser.add_argument('--page-size',type=int,default=10)
    parser.add_argument('--refresh',action='store_true')
    parser.add_argument('--strict-rubrics',action='store_true',help='Use exact category IDs discovered in returned source records')
    args=parser.parse_args()
    RAW.mkdir(parents=True,exist_ok=True);OUT.mkdir(parents=True,exist_ok=True)
    client=DgisClient(max_requests=args.max_requests)
    report={'started_at':now(),'scope':'33 checklist-related search categories within the Astana study rectangle','bbox':BBOX,'queries':[],'errors':[],'complete':True,'request_cap':args.max_requests,'key_type':'demo_user_reported','records_file':'data/processed/dgis_records.jsonl','license':'2GIS proprietary; not ODbL','credential_logged':False}
    records={};stopped=False;page_size=min(args.page_size,10)
    # Retain earlier successful results even if a later collection uses narrower filters.
    for cached_path in RAW.glob('*.json'):
        cached=json.loads(cached_path.read_text(encoding='utf-8'))
        for item in cached.get('response',{}).get('result',{}).get('items',[]):
            if not item.get('id'):continue
            object_id=str(item['id']).split('_')[0];q=cached['params'].get('q','')
            if object_id not in records:records[object_id]={'dgis_id':object_id,'data':item,'matched_queries':[q],'collected_at':cached['collected_at'],'source_url':f'https://2gis.kz/astana/firm/{object_id}','source_name':'2GIS Places API','license':'2GIS proprietary'}
            elif q not in records[object_id]['matched_queries']:records[object_id]['matched_queries'].append(q)
    rubric_path=ROOT/'data/raw/dgis_rubric_ids.json'
    rubric_ids=json.loads(rubric_path.read_text(encoding='utf-8')) if rubric_path.exists() else {}
    rubric_aliases={'Общественные туалеты':'Туалеты','Памятники':'Памятники и скульптуры','Коворкинги':'Коворкинг','Галереи':'Художественные выставки','Виртуальная реальность':'Центры виртуальной реальности'}
    queue=[{'query':q,'bbox':BBOX,'depth':0} for q in QUERIES]
    report['search_tasks']=[]
    # Reuse successful cached responses, so interrupted runs do not spend quota again.
    while queue:
        work=queue.pop(0);query=work['query'];bbox=work['bbox'];depth=work['depth']
        task={'query':query,'bbox':bbox,'depth':depth,'pages_collected':0,'api_total':None,'unique_ids':set(),'complete':True}
        page=1;max_pages=1
        while page<=max_pages:
            params={'q':query,'point1':f'{bbox[1]},{bbox[2]}','point2':f'{bbox[3]},{bbox[0]}','type':'branch','locale':'ru_KZ','page_size':page_size,'page':page,'fields':FIELDS}
            if args.strict_rubrics:
                rubric_id=rubric_ids.get(rubric_aliases.get(query,query))
                if rubric_id:params.update({'region_id':68,'rubric_id':rubric_id})
            fingerprint=hashlib.sha256(json.dumps(params,sort_keys=True,ensure_ascii=False).encode()).hexdigest()[:24]
            path=RAW/(fingerprint+'.json')
            try:
                if path.exists() and not args.refresh:
                    cached=json.loads(path.read_text(encoding='utf-8'));data=cached['response'];stamp=cached['collected_at']
                else:
                    for attempt in range(3):
                        try:
                            data=client.request('items',**params);break
                        except DgisError as error:
                            if 'network request failed' not in str(error) or attempt==2:raise
                            time.sleep(attempt+1)
                    stamp=now()
                    # No credential-bearing request URL is ever stored.
                    payload=json.dumps({'endpoint':'https://catalog.api.2gis.com/3.0/items','params':params,'collected_at':stamp,'response':data},ensure_ascii=False,indent=2).replace(client._key,'[REDACTED]')
                    path.write_text(payload,encoding='utf-8')
                    time.sleep(.12)
                result=data.get('result',{});items=result.get('items') or []
                total=result.get('total',len(items));task['api_total']=total
                max_pages=max(1,math.ceil(total/page_size))
                task['pages_collected']+=1
                for item in items:
                    if not item.get('id'):continue
                    object_id=str(item['id']).split('_')[0];task['unique_ids'].add(object_id)
                    previous=records.get(object_id)
                    if previous:
                        previous['matched_queries']=sorted(set(previous['matched_queries']+[query]))
                        if len(item)>len(previous['data']):previous['data']=item;previous['collected_at']=stamp
                    else:records[object_id]={'dgis_id':object_id,'data':item,'matched_queries':[query],'collected_at':stamp,'source_url':f'https://2gis.kz/astana/firm/{object_id}','source_name':'2GIS Places API','license':'2GIS proprietary'}
                if page==1 and total>page_size*5 and depth<12:
                    # Query documented geographic filters to cover dense areas. Each query
                    # stays inside the key's permitted page and global request limits.
                    south,west,north,east=bbox;midlat=(south+north)/2;midlon=(west+east)/2
                    children=[(south,west,midlat,midlon),(south,midlon,midlat,east),(midlat,west,north,midlon),(midlat,midlon,north,east)]
                    queue.extend({'query':query,'bbox':b,'depth':depth+1} for b in children)
                    task['subdivided']=True
                    break
                if max_pages>5:
                    task['complete']=False;task['stop_reason']='density_exceeds_five_page_window_at_max_depth';break
                if not items and page<max_pages:
                    task['complete']=False;task['stop_reason']='empty_page_before_reported_total';break
                page+=1
            except DgisError as exc:
                message=str(exc)
                if 'API 404' in message:
                    task['api_total']=0
                    write(path,{'endpoint':'https://catalog.api.2gis.com/3.0/items','params':params,'collected_at':now(),'empty_search_observed':True,'response':{'result':{'total':0,'items':[]}}})
                    break
                # A permitted smaller page size is a documented request option, not an auth workaround.
                if page==1 and page_size==50 and ('API 400' in message or 'API 403' in message):
                    page_size=10;continue
                task['complete']=False;task['stop_reason']=message
                report['errors'].append({'query':query,'page':page,'error':message})
                report['complete']=False;stopped=True;break
        task['unique_ids']=len(task['unique_ids'])
        report['search_tasks'].append(task)
        if depth==0:report['queries'].append(task)
        if depth==0 or len(report['search_tasks'])%20==0 or stopped:
            print(f'2GIS {query} depth={depth}: {task["unique_ids"]} IDs, pages={task["pages_collected"]}, total={task["api_total"]}; overall={len(records)}; requests={client.requests_made}; queued={len(queue)}',flush=True)
        if not task['complete']:report['complete']=False
        report['requests_made_this_run']=client.requests_made;report['unique_records']=len(records);report['last_updated_at']=now();report['unstarted_queries']=QUERIES[len(report['queries']):];report['pending_tasks']=queue
        write(OUT/'dgis_collection_report.json',report)
        if stopped or not queue or len(report['search_tasks'])%20==0:
            with (OUT/'dgis_records.jsonl').open('w',encoding='utf-8') as stream:
                for record in records.values():stream.write(json.dumps(record,ensure_ascii=False,separators=(',',':'))+'\n')
        if stopped:break
    report['finished_at']=now();report['page_size_used']=page_size
    write(OUT/'dgis_collection_report.json',report)
    print(json.dumps({'records':len(records),'requests_made':client.requests_made,'queries_finished':len(report['queries']),'complete':report['complete'],'errors':report['errors']},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
