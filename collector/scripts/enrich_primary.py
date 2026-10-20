"""Extract explicit facts from selected primary pages, retaining evidence text."""
from datetime import datetime, timezone
import json
import re
import sqlite3
from pathlib import Path
from bs4 import BeautifulSoup
from scripts.build_dataset import ROOT,RAW,OUT,NOW,load,save,jsonl,fact,FACTS,meta

def main():
    rows=[json.loads(x) for x in (OUT/'pois.jsonl').read_text(encoding='utf-8').splitlines()]
    byid={p['poi_id']:p for p in rows}
    museum=byid['osm:node:4894937300'];tower=byid['osm:way:230401645']
    changes=[];catalogues=[];extra_events=[]
    def set_field(p,field,value,m,evidence):
        source_name='POI official website' if 'nmrk.kz' in m['url'] else ('Visit Astana' if 'visitastana.kz' in m['url'] else 'Kazakhstan.travel')
        old=p.get(field)
        if old is not None and old!=value:
            changes.append({'poi_id':p['poi_id'],'field_name':field,'previous_value':old,'new_value':value,'chosen_source_url':m['url'],'reason':'explicit_primary_page_preferred; both claims retained in facts'})
        p[field]=value
        p.setdefault('sources',[])
        if not any(x['url']==m['url'] for x in p['sources']):p['sources'].append({'name':source_name,'url':m['url'],'collected_at':m['collected_at'],'license':None})
        fact(p,field,value,source_name,m['url'],m['collected_at'],method='explicit_text_regex_with_saved_evidence',score=.8,license=None)
        FACTS[-1]['evidence_text']=evidence
        FACTS[-1]['source_conflict']=old is not None and old!=value
    for item in load(RAW/'extra_index.json',[]):
        if not item.get('path'):continue
        path=ROOT/Path(item['path']);m=meta(path);s=BeautifulSoup(path.read_text(encoding='utf-8'),'html.parser')
        for element in s(['script','style']):element.decompose()
        text=s.get_text(' ',strip=True)
        if m['url']=='https://nmrk.kz/ru/' and '10:00 - 18:00 Вт-Вс' in text and 'Понедельник - выходной день' in text:
            set_field(museum,'opening_hours','Mo off; Tu-Su 10:00-18:00',m,'10:00 - 18:00 Вт-Вс; Понедельник - выходной день')
            set_field(museum,'website','https://nmrk.kz/ru/',m,'Official museum home page')
        if '/accessible-museum/' in m['url']:
            for field,pattern in [('ramps',r'установлены пандусы[^;]+'),('restrooms',r'имеются специально оборудованные туалеты[^;]+'),('wheelchair_accessible',r'передвигающихся на кресле-коляске')]:
                match=re.search(pattern,text,re.I)
                if match:set_field(museum,field,True,m,match[0])
        if '/museum-rules/' in m['url']:
            match=re.search(r'Проводить и/или проносить любых животных',text)
            if match:set_field(museum,'pet_friendly',False,m,'На территории музея запрещается: '+match[0])
        if '/rules-for-children/' in m['url']:
            match=re.search(r'в период каникул для школьников[^.]+',text,re.I)
            if match:set_field(museum,'discounts',[{'description':match[0],'eligibility':'schoolchildren who are citizens of Kazakhstan; during school holidays','valid_dates':None}],m,match[0])
            match=re.search(r'Дети[^.]+сопровожд[^.]+',text,re.I)
            if match:set_field(museum,'age_restrictions',{'description':match[0]},m,match[0])
        if '/natsionalnyy-muzey-respubliki-kazakhstan/' in m['url']:
            if 'интерактивное шоу' in text:
                set_field(museum,'interactive_exhibits',True,m,'Главный макет Астаны и медиа-пол создают яркое интерактивное шоу')
            if 'Последний Вторник месяца санитарный день' in text:
                set_field(museum,'holiday_hours',{'monthly_closure':'last Tuesday of each month','reason':'sanitary day','raw':'Последний Вторник месяца санитарный день'},m,'Последний Вторник месяца санитарный день')
        if '/attractions/423' in m['url']:
            for field,pattern in [('adult_ticket_price',r'Взрослый билет\s*-\s*(\d+)\s*тг'),('child_ticket_price',r'Детский билет\s*\(([^)]+)\)\s*-\s*(\d+)\s*тг')]:
                match=re.search(pattern,text)
                if match:
                    amount=int(match[match.lastindex]);value={'amount':amount,'currency':'KZT','valid_from':None,'valid_until':None}
                    if field=='child_ticket_price':value['age_group']=match[1]
                    set_field(tower,field,value,m,match[0])
            match=re.search(r'Льготный\s*\(([^)]+)\)\s*-\s*(\d+)\s*тг',text)
            if match:set_field(tower,'discounts',[{'eligibility':match[1],'amount':int(match[2]),'currency':'KZT'}],m,match[0])
        if 'data.egov.kz/datasets/view' in m['url']:
            catalogues.append({'source_url':m['url'],'collected_at':m['collected_at'],'archived':'В архиве' in text or 'Мұрағатта' in text,'used_for_current_poi_facts':False,'reason':'Archived metadata; not a current POI source. API records require a developer key.','title':s.title.get_text(' ',strip=True) if s.title else None})
        if '/affiche/966/' in m['url']:
            article=s.select_one('article.afisha-detail__text')
            if article:
                body=article.get_text(' ',strip=True)
                match=re.search(r'Срок проведения выставки:\s*(\d+) октября\s*[–-]\s*(\d+) ноября\s*(\d{4})',body)
                if match:
                    start=f'{match[3]}-10-{int(match[1]):02d}';end=f'{match[3]}-11-{int(match[2]):02d}'
                    extra_events.append({'event_id':'nmrk:966','event_name':'Отырар–Туркестан: средневековая ирригация и культура земледелия','event_start':start,'event_end':end,'date_precision':'day','timezone':'Asia/Qyzylorda','event_location':museum['display_name'],'event_coordinates':{'latitude':museum['latitude'],'longitude':museum['longitude']},'event_description':body,'event_category':'exhibition','event_price':None,'registration_url':None,'event_age_group':None,'event_status':None,'event_verified_at':None,'listing_period_status':'upcoming_or_ongoing' if end>=datetime.now(timezone.utc).date().isoformat() else 'past','source_url':m['url'],'collected_at':m['collected_at'],'license':None,'location_coordinate_method':'matched_to_OSM_National_Museum_record'})
    ev=[json.loads(x) for x in (OUT/'events.jsonl').read_text(encoding='utf-8').splitlines()]
    ev=[x for x in ev if x['event_id'] not in {e['event_id'] for e in extra_events}]+extra_events
    jsonl(OUT/'events.jsonl',ev);jsonl(OUT/'pois.jsonl',rows)
    with (OUT/'facts.jsonl').open('a',encoding='utf-8') as f:
        for row in FACTS:f.write(json.dumps(row,ensure_ascii=False,separators=(',',':'))+'\n')
    save(OUT/'government_catalogues.json',catalogues);save(OUT/'primary_source_updates.json',changes)
    db=sqlite3.connect(OUT/'smart_city.sqlite')
    db.executemany('UPDATE pois SET payload_json=? WHERE poi_id=?',[(json.dumps(p,ensure_ascii=False),p['poi_id']) for p in rows])
    db.executemany('INSERT INTO facts VALUES(?,?,?,?)',[(f['poi_id'],f['field_name'],f['source_name'],json.dumps(f,ensure_ascii=False)) for f in FACTS])
    for e in extra_events:db.execute('INSERT OR REPLACE INTO events VALUES(?,?)',(e['event_id'],json.dumps(e,ensure_ascii=False)))
    db.commit();db.close();print('Primary-source facts:',len(FACTS),'additional dated events:',len(extra_events))

if __name__=='__main__':main()
