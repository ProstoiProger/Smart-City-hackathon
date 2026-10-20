"""Normalize saved 2GIS records and merge conservative identity matches into POIs."""
import collections
import difflib
import json
import re
import sqlite3
from pathlib import Path
from scipy.spatial import cKDTree
from scripts.build_dataset import ROOT,OUT,RAW,POI_FIELDS,NOW,blank,name_key,xy,distance,jsonl,save,load

DAYS={'Mon':'Mo','Tue':'Tu','Wed':'We','Thu':'Th','Fri':'Fr','Sat':'Sa','Sun':'Su'}
RULES=[
 (r'^(кофейн|точки кофе|кафе|ресторан|пекар|кондитер|быстрое питание|столовые|кулинарии|фуд-корт|пиццери|суши)', 'food_drink'),
 (r'^(бары|пабы|ночные клубы|караоке)', 'nightlife'),
 (r'^(музеи|театры|галереи|художественные выставки|концертные залы|филармони)', 'culture'),
 (r'^(библиотеки|коворкинг)', 'quiet_spaces'),
 (r'^(парки|скверы|ботанические сады|набережные)', 'nature'),
 (r'^(детские игровые|детские площадки|детские развлекательные)', 'children'),
 (r'^(кинотеатры|центры виртуальной реальности|развлекательные центры|аттракционы|боулинг|бильярд|батут|океанариум|цирк)', 'entertainment'),
 (r'^(бассейны|катки|спортивные комплексы|спорткомплексы|фитнес|тренажёрные|тренажерные|стадионы)', 'sport'),
 (r'^(торговые центры|торгово-развлекательные)', 'shopping'),
 (r'^(памятники и скульптуры|достопримечательности|смотровые площадки|мемориальные комплексы)', 'sightseeing'),
 (r'^(туалеты|общественные туалеты|парковки|паркинги)', 'infrastructure'),
 (r'^(сауны|бани|spa|спа)', 'wellness'),
]

def classify(item):
    rubrics=sorted(item.get('rubrics') or [],key=lambda r:r.get('kind')!='primary')
    for rubric in rubrics:
        label=rubric.get('name','')
        for pattern,category in RULES:
            if re.search(pattern,label.casefold()):return category,label
    if not rubrics and re.search(r'ботанический сад.*оранжерея',item.get('name',''),re.I):return 'nature','Оранжерея'
    return 'other',rubrics[0]['name'] if rubrics else 'unknown'

def schedule_fields(schedule):
    if not schedule:return None,None,None
    if schedule.get('is_24x7') is True:return '24/7',{d:[['00:00','24:00']] for d in DAYS.values()},True
    weekly={};parts=[]
    for source,target in DAYS.items():
        day=schedule.get(source)
        if day is None:weekly[target]=None;continue
        intervals=[[x.get('from'),x.get('to')] for x in day.get('working_hours',[]) if x.get('from') and x.get('to')]
        weekly[target]=intervals or None
        if intervals:parts.append(target+' '+','.join('-'.join(x) for x in intervals))
    return '; '.join(parts) or None,weekly if parts else None,False if parts else None

def normalize(record):
    item=record['data'];point=item.get('point') or {};lat=point.get('lat');lon=point.get('lon')
    p=blank('dgis:'+record['dgis_id']);category,subcategory=classify(item)
    hours,weekly,is24=schedule_fields(item.get('schedule'))
    reviews=item.get('reviews') or {}
    p.update({'name':item.get('name'),'display_name':item.get('name') or record['dgis_id'],'name_ru':item.get('name'),'latitude':lat,'longitude':lon,'address':item.get('full_address_name') or item.get('address_name'),'external_ids':{'2gis':record['dgis_id']},'category':category,'subcategory':subcategory,'tags':[],'source_url':record['source_url'],'last_updated_at':record['collected_at'],'source_updated_at':(item.get('dates') or {}).get('updated_at'),'opening_hours':hours,'opening_hours_by_day':weekly,'opening_hours_raw_2gis':item.get('schedule'),'is_24_7':is24,'holiday_hours':item.get('schedule_special'),'rating':reviews.get('general_rating') if reviews.get('general_rating') is not None else reviews.get('rating'),'ratings_count':reviews.get('general_review_count_with_stars'),'reviews_count':reviews.get('general_review_count') if reviews.get('general_review_count') is not None else reviews.get('review_count'),'rating_source':'2GIS' if reviews.get('general_rating') is not None or reviews.get('rating') is not None else None,'raw_2gis_reviews':reviews or None,'operational_status':'listed_in_2gis_catalog','coordinate_method':'2GIS_object_point','coordinate_is_verified_entrance':False,'description_type':'derived_template','sources':[{'name':'2GIS Places API','url':record['source_url'],'collected_at':record['collected_at'],'license':'2GIS proprietary'}],'derived_fields':['category','subcategory','short_description','tags'],'matched_queries':record['matched_queries'],'in_checklist_scope':category!='other','raw_osm_tags':{},'image_candidates':None})
    if p['rating']==0:
        p['rating']=None;p['rating_source']=None
        p['rating_unavailable_reason']='provider returned zero; raw value retained in raw_2gis_reviews, not interpreted as a 1-to-5 rating'
    attributes=[a for group in item.get('attribute_groups') or [] for a in group.get('attributes') or []]
    p['raw_2gis_attributes']=attributes
    attr={a.get('tag'):a for a in attributes if a.get('tag')}
    p['tags']=[a.get('name') for a in attributes if a.get('name')]+[r['name'] for r in item.get('rubrics') or [] if r.get('name')]
    bool_rules={
      'wifi_available':['additionally_services_freewifi','additionally_services_wifi','sauna_wifi'],
      'laptop_friendly':['food_service_cafe_working'],
      'wheelchair_accessible':['accessible_entrance_accessible_entrance'],
      'ramps':['accessible_entrance_inclusive_environment_ramp_inclusive'],
      'elevators':['accessible_entrance_inclusive_environment_elevator_inclusive'],
      'restrooms':['accessible_entrance_inclusive_environment_wc_inclusive','ice_rink_toilet_ice_skating','additionalgarbage_availabilitytoilet_paid_toilet','additionalgarbage_availabilitytoilet_free_toilet'],
      'playground':['malls_kids_playground_mall','summer_infrastructure_infrastructure_playground','hotel_details_outdoor_playground'],
      'pet_friendly':['available_dog_friendly','food_service_dog_friendly_food'],
      'scenic_view':['food_service_infrastructure_panoramic_restaurant'],
    }
    p['attribute_evidence']={}
    for field,tags in bool_rules.items():
        present=[tag for tag in tags if tag in attr]
        if present:p[field]=True;p['attribute_evidence'][field]=[attr[tag] for tag in present]
    if p['wheelchair_accessible'] is True:p['wheelchair_accessibility_scope']='provider_tag_for_entrance; full interior route not verified'
    family=[a for a in attributes if a.get('tag') in {'food_service_details_food_kids_menu','food_service_infrastructure_kids_playroom','food_service_infrastructure_kids_room','food_service_infrastructure_children_entertainment','pool_kids','malls_kids_playground_mall'}]
    if family:p['family_friendly_signal']={'signals':family,'basis':'explicit_2gis_attributes','age_suitability_verified':False}
    price=attr.get('food_service_avg_price')
    if price:
        numbers=re.findall(r'\d[\d\s\u00a0]*',price.get('name',''))
        amounts=[int(re.sub(r'\s','',n)) for n in numbers if n.strip()]
        if amounts:p['estimated_visit_budget']={'amount_min':amounts[0],'amount_max':amounts[-1],'currency':'KZT','basis':'2gis_published_average_check','raw':price['name']}
    if is24 is True:p['night_access']=True;p['derived_fields'].append('night_access')
    if weekly:
        breaks={day:[[periods[i][1],periods[i+1][0]] for i in range(len(periods)-1)] for day,periods in weekly.items() if periods and len(periods)>1}
        if breaks:p['break_hours']=breaks;p['derived_fields'].append('break_hours')
    links=item.get('links') or {}
    if links.get('nearest_stations'):p['nearby_transit_stops']=[{'external_id':s.get('id'),'name':s.get('name'),'provider_distance_m':s.get('distance'),'distance_method':None,'route_types':s.get('route_types'),'source':'2GIS'} for s in links['nearest_stations']]
    if links.get('nearest_parking'):p['nearby_parking_2gis']=links['nearest_parking']
    if links.get('entrances'):p['entrances_exits']=[{'external_id':e.get('id'),'geometry':e.get('geometry'),'is_primary':e.get('is_primary'),'source':'2GIS','verified':False} for e in links['entrances']]
    for group in item.get('contact_groups') or []:
        for contact in group.get('contacts') or []:
            if contact.get('type')=='phone' and contact.get('value'):p['phone']=contact['value']
            if contact.get('type') in ('website','site') and contact.get('value'):p['website']=contact['value']
    description=item.get('description')
    if isinstance(description,str) and description.strip():p['short_description']=description.strip();p['description_type']='source_text';p['derived_fields'].remove('short_description')
    else:
        p['short_description']=f'{p["display_name"]} — {subcategory}.'
        if p['address']:p['short_description']+=' Адрес: '+p['address']+'.'
        evidence=[a['name'] for a in attributes if a.get('tag') in {'food_service_cafe_working','additionally_services_freewifi','additionally_services_wifi','food_service_details_food_kids_menu','food_service_infrastructure_kids_playroom','accessible_entrance_accessible_entrance','food_service_avg_price'}]
        if evidence:p['short_description']+=' По данным 2GIS: '+', '.join(evidence)+'.'
    return p

def main():
    path=OUT/'dgis_records.jsonl'
    if not path.exists():print('No saved 2GIS snapshot; nothing to merge.');return
    records=[json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]
    pois=[json.loads(line) for line in (OUT/'pois.jsonl').read_text(encoding='utf-8').splitlines()]
    # Reapplication is idempotent for 2GIS-only additions and source facts.
    pois=[p for p in pois if not p['poi_id'].startswith('dgis:')]
    normalized=[normalize(r) for r in records]
    tree=cKDTree([xy(p['latitude'],p['longitude']) for p in pois]);mapping=[];conflicts=[];facts=[];skipped=[]
    explicit={}
    for p in pois:
        value=p.get('external_ids',{}).get('2gis')
        if value:
            match=re.search(r'(?:firm/)?(\d{10,})',str(value))
            if match:explicit[match[1]]=p
    for source in normalized:
        pid=source['poi_id'];lat=source['latitude'];lon=source['longitude'];object_id=source['external_ids']['2gis']
        if lat is None or lon is None or not (50.98<=lat<=51.34 and 71.18<=lon<=71.75):skipped.append({'dgis_id':object_id,'reason':'missing_or_outside_study_bbox_coordinates'});continue
        if not source['in_checklist_scope']:skipped.append({'dgis_id':object_id,'reason':'category_outside_checklist; raw record retained'});continue
        target=explicit.get(object_id);method='explicit_external_id';candidates=[]
        if target is None:
            for i in tree.query_ball_point(xy(lat,lon),130):
                candidate=pois[i]
                existing_id=re.search(r'(?:firm/)?(\d{10,})',str(candidate.get('external_ids',{}).get('2gis','')))
                if existing_id and existing_id[1]!=object_id:continue
                if candidate['category']!=source['category']:continue
                names=[name_key(candidate.get(k)) for k in ('name','name_ru','name_kk','name_en') if candidate.get(k)]
                key=name_key(source['name']);similarity=max((difflib.SequenceMatcher(None,key,n).ratio() for n in names),default=0)
                if similarity>=.91:candidates.append((similarity,-distance((lat,lon),(candidate['latitude'],candidate['longitude'])),candidate))
            if candidates:
                candidates.sort(key=lambda x:(x[0],x[1]),reverse=True)
                # Ambiguous equal-name branches stay separate rather than being guessed.
                if len(candidates)==1 or candidates[0][0]-candidates[1][0]>.06:target=candidates[0][2];method='name_similarity_and_distance_under_130m'
        if target is None:
            target=source;pois.append(target);method='new_2gis_poi'
        else:
            target.setdefault('external_ids',{})['2gis']=object_id
            target['sources']=[s for s in target.get('sources',[]) if s.get('name')!='2GIS Places API']+source['sources']
            for field in POI_FIELDS+['opening_hours_by_day','opening_hours_raw_2gis','raw_2gis_reviews','raw_2gis_attributes','attribute_evidence','reviews_count','nearby_transit_stops','entrances_exits','nearby_parking_2gis','family_friendly_signal']:
                value=source.get(field)
                if value is None or field in ('poi_id','external_ids','source_url','latitude','longitude','category','subcategory','short_description','tags','last_updated_at'):continue
                old=target.get(field)
                if old is not None and old!=value:conflicts.append({'poi_id':target['poi_id'],'field_name':field,'previous_value':old,'chosen_value':value,'chosen_source_url':source['source_url'],'selection_method':'2gis_snapshot_selected_for_live_business_attributes; original claim retained in facts'})
                target[field]=value
            target['last_updated_at']=max(target['last_updated_at'],source['last_updated_at'])
            target['tags']=sorted(set(target.get('tags') or [])|set(source.get('tags') or []))
            target['raw_2gis_id']=object_id
        mapping.append({'dgis_id':object_id,'poi_id':target['poi_id'],'match_method':method,'manually_verified':False})
        for field in POI_FIELDS+['opening_hours_by_day','reviews_count','nearby_transit_stops','entrances_exits']:
            value=source.get(field)
            if value is None:continue
            facts.append({'poi_id':target['poi_id'],'field_name':field,'field_value':value,'source_name':'2GIS Places API','source_url':source['source_url'],'collected_at':source['last_updated_at'],'verified_at':None,'verification_method':'explicit_2gis_response_field_or_attribute','confidence_score':.7,'license':'2GIS proprietary','source_conflict':False,'stale_data':None,'derived_value':field in source.get('derived_fields',[]),'user_generated_opinion':field in ('rating','ratings_count','reviews_count'),'source_updated_at':source.get('source_updated_at'),'evidence':source.get('attribute_evidence',{}).get(field)})
    old_facts=[json.loads(line) for line in (OUT/'facts.jsonl').read_text(encoding='utf-8').splitlines()]
    old_facts=[f for f in old_facts if f['source_name']!='2GIS Places API']
    jsonl(OUT/'pois.jsonl',pois);jsonl(OUT/'facts.jsonl',old_facts+facts);jsonl(OUT/'dgis_pois.jsonl',normalized)
    save(OUT/'dgis_matches.json',mapping);save(OUT/'dgis_source_conflicts.json',conflicts);save(OUT/'dgis_excluded_records.json',skipped)
    summary={'created_at':NOW,'provider_records':len(records),'normalized_records':len(normalized),'merged_or_added':len(mapping),'matched_existing_pois':sum(m['match_method']!='new_2gis_poi' for m in mapping),'added_pois':sum(m['match_method']=='new_2gis_poi' for m in mapping),'excluded_from_recommendation_pois':len(skipped),'unified_poi_count':len(pois),'source_facts_added':len(facts),'conflicts':len(conflicts),'provider_field_coverage':{f:sum(p.get(f) is not None for p in normalized) for f in POI_FIELDS}}
    save(OUT/'dgis_enrichment_summary.json',summary)
    db=sqlite3.connect(OUT/'smart_city.sqlite')
    db.execute('CREATE TABLE IF NOT EXISTS dgis_places(dgis_id TEXT PRIMARY KEY,payload_json TEXT)')
    db.execute('DELETE FROM dgis_places')
    db.executemany('INSERT INTO dgis_places VALUES(?,?)',[(r['dgis_id'],json.dumps(r,ensure_ascii=False)) for r in records])
    db.execute('DELETE FROM pois');db.execute('DELETE FROM poi_search')
    db.executemany('INSERT INTO pois VALUES(?,?,?,?,?,?,?)',[(p['poi_id'],p['display_name'],p['category'],p['subcategory'],p['latitude'],p['longitude'],json.dumps(p,ensure_ascii=False)) for p in pois])
    db.executemany('INSERT INTO poi_search VALUES(?,?)',[(p['poi_id'],' '.join(str(p.get(k) or '') for k in ('display_name','name_ru','name_kk','name_en','short_description','category','subcategory','tags','address'))) for p in pois])
    db.commit();db.close()
    print(json.dumps({k:v for k,v in summary.items() if k!='provider_field_coverage'},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
