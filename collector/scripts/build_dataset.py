"""Normalize public source snapshots; never replace an unknown fact by False."""
import collections
from datetime import datetime, timezone
import difflib
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
import sys
from urllib.parse import urlparse, urljoin, parse_qs

from bs4 import BeautifulSoup
from scipy.spatial import cKDTree

ROOT=Path(__file__).resolve().parents[1]
RAW=ROOT/'data/raw'
OUT=ROOT/'data/processed'
OUT.mkdir(parents=True,exist_ok=True)
sys.stdout.reconfigure(encoding='utf-8')
NOW=datetime.now(timezone.utc).isoformat()
FACTS=[]
REJECTED=[]
DUPLICATES=[]
CONFLICTS=[]

def load(path,default=None):
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else default

def save(path,value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')

def jsonl(path,rows):
    with path.open('w',encoding='utf-8') as f:
        for row in rows: f.write(json.dumps(row,ensure_ascii=False,separators=(',',':'))+'\n')

def meta(path):
    return load(path.with_suffix(path.suffix+'.meta.json'),{'collected_at':datetime.fromtimestamp(path.stat().st_mtime,timezone.utc).isoformat(),'url':None})

def norm(text):
    return re.sub(r'[^\w]','',str(text or '').casefold())

def name_key(text):
    text=str(text or '').casefold().translate(str.maketrans('әғқңөұүһі','агкноуухи'))
    text=re.sub(r'\b(?:монумент|памятник|ресторан|кафе|театр|торгово|развлекательный|центр|трц)\b',' ',text)
    return norm(text)

def point(e):
    c=e.get('center',e)
    return c.get('lat'),c.get('lon')

def distance(a,b):
    lat1,lon1=a;lat2,lon2=b
    r1,r2=math.radians(lat1),math.radians(lat2)
    h=math.sin((r2-r1)/2)**2+math.cos(r1)*math.cos(r2)*math.sin(math.radians(lon2-lon1)/2)**2
    return 12742000*math.asin(min(1,math.sqrt(h)))

def xy(lat,lon):
    return (lon*111195*math.cos(math.radians(51.15)),lat*111195)

def truth(v):
    if v in ('yes','true','1','designated','permissive'):return True
    if v in ('no','false','0'):return False
    return None

def schema():
    text=(ROOT/'smart_city_parsing_checklist.md').read_text(encoding='utf-8-sig')
    section=None;out=[]
    for line in text.splitlines():
        if line.startswith('## '):section=line[3:]
        if line.startswith('- [ ]'):
            for field in re.findall(r'`([^`]+)`',line):
                out.append({'field':field,'section':section,'priority':next((p for p in ('P0','P1','P2') if p in line),None),'description':line[6:].strip()})
    return out

SCHEMA=schema()
POI_FIELDS=list(dict.fromkeys(x['field'] for x in SCHEMA if x['section'] and re.match(r'^[1-5]\. ',x['section'])))

def fact(p,field,value,source,url,collected,method='explicit_source_field',derived=False,score=.7,license='ODbL-1.0',source_updated=None):
    if value is None:return
    FACTS.append({'poi_id':p['poi_id'],'field_name':field,'field_value':value,'source_name':source,'source_url':url,'collected_at':collected,'verified_at':None,'verification_method':method,'confidence_score':score,'license':license,'source_conflict':False,'stale_data':None,'derived_value':derived,'user_generated_opinion':None if field=='short_description' and not derived else False,'source_updated_at':source_updated})

CATEGORY={
    'cafe':('food_drink','Кафе',40),'restaurant':('food_drink','Ресторан',60),'fast_food':('food_drink','Быстрое питание',25),'food_court':('food_drink','Фуд-корт',40),'bar':('nightlife','Бар',60),'pub':('nightlife','Паб',60),'nightclub':('nightlife','Ночной клуб',90),'biergarten':('food_drink','Пивной сад',60),'ice_cream':('food_drink','Мороженое',15),'bakery':('food_drink','Пекарня',20),'confectionery':('food_drink','Кондитерская',20),'coffee':('food_drink','Кофе',30),
    'park':('nature','Парк',60),'garden':('nature','Сад',45),'nature_reserve':('nature','Природная территория',90),'common':('nature','Зелёная зона',30),
    'playground':('children','Детская площадка',40),'pitch':('sport','Спортивная площадка',45),'sports_centre':('sport','Спортивный центр',60),'fitness_centre':('sport','Фитнес-центр',60),'fitness_station':('sport','Уличные тренажёры',30),'track':('sport','Беговая дорожка',30),'stadium':('sport','Стадион',60),'swimming_pool':('sport','Бассейн',60),'ice_rink':('sport','Каток',60),'sauna':('wellness','Сауна',90),'water_park':('entertainment','Аквапарк',120),
    'museum':('culture','Музей',90),'gallery':('culture','Галерея',45),'theatre':('culture','Театр',120),'cinema':('entertainment','Кинотеатр',120),'arts_centre':('culture','Центр искусств',60),'library':('quiet_spaces','Библиотека',60),'coworking_space':('quiet_spaces','Коворкинг',60),'community_centre':('culture','Общественный центр',60),
    'mall':('shopping','Торговый центр',90),'viewpoint':('sightseeing','Смотровая площадка',20),'attraction':('sightseeing','Достопримечательность',40),'artwork':('sightseeing','Арт-объект',15),'monument':('sightseeing','Монумент',20),'memorial':('sightseeing','Мемориал',20),'place_of_worship':('sightseeing','Религиозный объект',30),'information':('infrastructure','Туристическая информация',10),
    'hotel':('accommodation','Отель',None),'hostel':('accommodation','Хостел',None),'guest_house':('accommodation','Гостевой дом',None),'apartment':('accommodation','Апартаменты',None),'motel':('accommodation','Мотель',None)
}

def classify(tags):
    for k in ['amenity','tourism','leisure','shop','historic']:
        if k in tags:
            sub=tags[k]
            cat,label,dur=CATEGORY.get(sub,('other',sub,None))
            return cat,sub,label,dur
    return 'other','unknown','Объект',None

def blank(pid):
    return dict.fromkeys(POI_FIELDS)|{'poi_id':pid}

def osm_pois():
    path=RAW/'osm_pois.json';doc=load(path,{'elements':[]});stamp=meta(path)['collected_at']
    out=[]
    for e in doc['elements']:
        lat,lon=point(e)
        if lat is None or not (50.98<=lat<=51.34 and 71.18<=lon<=71.75):
            REJECTED.append({'source':'OSM','id':e['id'],'reason':'missing_or_outside_study_bbox_coordinates'});continue
        t=e.get('tags',{});pid=f'osm:{e["type"]}:{e["id"]}';p=blank(pid)
        cat,sub,label,duration=classify(t)
        name=t.get('name') or t.get('name:ru') or t.get('name:kk') or t.get('name:en')
        p.update({'external_ids':{'osm':f'{e["type"]}/{e["id"]}'},'name':name,'display_name':name or f'{label} ({e["type"]}/{e["id"]})','name_ru':t.get('name:ru'),'name_kk':t.get('name:kk'),'name_en':t.get('name:en'),'latitude':lat,'longitude':lon,'category':cat,'subcategory':sub,'tags':[f'{k}={v}' for k,v in sorted(t.items()) if k in {'amenity','tourism','leisure','shop','historic','cuisine','sport','diet:vegan','diet:vegetarian','wheelchair','internet_access','outdoor_seating','indoor','access'}],'address':t.get('addr:full') or (', '.join(filter(None,[t.get('addr:street'),t.get('addr:housenumber')])) or None),'website':t.get('contact:website') or t.get('website'),'phone':t.get('contact:phone') or t.get('phone'),'source_url':f'https://www.openstreetmap.org/{e["type"]}/{e["id"]}','last_updated_at':stamp,'source_updated_at':e.get('timestamp'),'opening_hours':t.get('opening_hours'),'is_24_7':True if t.get('opening_hours')=='24/7' else (False if t.get('opening_hours') else None),'hours_verified_at':None,'opening_hours_observed_at':stamp if t.get('opening_hours') else None,'suggested_visit_duration_min':duration,'raw_osm_tags':t,'sources':[{'name':'OpenStreetMap','url':f'https://www.openstreetmap.org/{e["type"]}/{e["id"]}','collected_at':stamp,'license':'ODbL-1.0'}],'description_type':None,'derived_fields':['category','subcategory','suggested_visit_duration_min','tags','display_name'],'image_candidates':None})
        p['short_description']=t.get('description:ru') or t.get('description')
        if p['short_description']:p['description_type']='source_text'
        else:
            p['short_description']=f'{label}: {name}.' if name else f'{label} в Астане.'
            if p['address']:p['short_description']+=f' Адрес по OSM: {p["address"]}.'
            p['description_type']='derived_template';p['derived_fields'].append('short_description')
        simple={'power_outlets':['socket','power_supply'],'playground':['playground'],'interactive_exhibits':['interactive'],'wheelchair_accessible':['wheelchair'],'ramps':['ramp','ramp:wheelchair'],'elevators':['elevator'],'restrooms':['toilets'],'parking':['parking'],'seating':['seats','seating'],'pet_friendly':['dog'],'stroller_accessible':['stroller'],'reservation_required':['reservation'],'booking_required':['reservation']}
        for field,keys in simple.items():
            v=next((t[k] for k in keys if k in t),None)
            p[field]=truth(v)
        if sub=='playground':p['playground']=True;p['derived_fields'].append('playground')
        if 'internet_access' in t:p['wifi_available']=True if t['internet_access']=='wlan' else (False if t['internet_access']=='no' else None)
        if 'indoor' in t:p['indoor_outdoor']='indoor' if truth(t['indoor']) is True else ('outdoor' if truth(t['indoor']) is False else None)
        if t.get('fee') in ('yes','no'):p['free_entry']=t['fee']=='no'
        if t.get('min_age') or t.get('max_age'):p['age_restrictions']={k:t[k] for k in ('min_age','max_age') if k in t}
        if t.get('seasonal') is not None:p['seasonal_availability']=t['seasonal']
        if t.get('access') is not None:p['access_restrictions']=t['access']
        if t.get('opening_hours')=='closed' or t.get('disused')=='yes':p['operational_status']='closed_or_disused_in_osm'
        if t.get('opening_hours')=='24/7':p['night_access']=True
        if t.get('wikimedia_commons') or t.get('image'):
            p['image_candidates']={'wikimedia_commons':t.get('wikimedia_commons'),'image':t.get('image'),'rights_verified':False}
        if t.get('contact:2gis'):p['external_ids']['2gis']=t['contact:2gis']
        for field in POI_FIELDS+['name','display_name','source_updated_at']:
            fact(p,field,p.get(field),'OpenStreetMap',p['source_url'],stamp,derived=field in p['derived_fields'],method='deterministic_rule_from_osm_tags' if field in p['derived_fields'] else 'explicit_osm_tag_or_element',score=.5 if field in p['derived_fields'] else .7,source_updated=e.get('timestamp'))
        p['coordinate_method']='OSM_node' if e['type']=='node' else 'OSM_bounding_box_center'
        p['coordinate_is_verified_entrance']=False
        out.append(p)
    return out

def deduplicate(pois):
    kept=[];buckets=collections.defaultdict(list)
    for p in sorted(pois,key=lambda p:-(len(p['raw_osm_tags']))):
        key=(norm(p['name']),p['category'],p['subcategory'])
        match=next((q for q in buckets[key] if key[0] and distance((p['latitude'],p['longitude']),(q['latitude'],q['longitude']))<=35),None)
        if match:
            DUPLICATES.append({'removed_poi_id':p['poi_id'],'canonical_poi_id':match['poi_id'],'reason':'same_normalized_name_category_within_35m','distance_m':round(distance((p['latitude'],p['longitude']),(match['latitude'],match['longitude'])),1)})
            match['external_ids'].setdefault('osm_aliases',[]).append(p['external_ids']['osm'])
            for field in POI_FIELDS:
                if match.get(field) is None and p.get(field) is not None:match[field]=p[field]
        else:kept.append(p);buckets[key].append(p)
    aliases={x['removed_poi_id']:x['canonical_poi_id'] for x in DUPLICATES}
    for f in FACTS:
        if f['poi_id'] in aliases:f['poi_id']=aliases[f['poi_id']]
    return kept

SPAM=re.compile(r'(?i)(snowbet|slot gacor|togel|mahjong ways|promaxwin|mpo\w*\d{2,}|situs judi)')

def select_text(s,*selectors):
    for selector in selectors:
        node=s.select_one(selector)
        if node:
            val=node.get_text(' ',strip=True).replace('\u200b','')
            if val and val not in ('Array','Адрес не найден'):return val
    return None

def tourism_paths():
    index=load(RAW/'tourism_index.json',{})
    for item in load(RAW/'extra_index.json',[]):
        if 'visitastana.kz/ru/about-city/' in item.get('url','') and item.get('path'):index[item['url']]=item['path']
    # A finite directory crawl is authoritative; ignore unrelated cached trap URLs.
    return [ROOT/Path(p) for p in dict.fromkeys(index.values())] if index else list((RAW/'visitastana').glob('*.html'))

def official_pois():
    out=[]
    directory_types={}
    for path in tourism_paths():
        m=meta(path);parsed_url=urlparse(m['url']);category=parse_qs(parsed_url.query).get('category',[None])[0]
        if category:
            listing=BeautifulSoup(path.read_text(encoding='utf-8'),'html.parser')
            for link in listing.select('.museum a[href]'):
                href=urljoin(m['url'],link['href']).split('?')[0]
                directory_types[href]=category
    for path in sorted(tourism_paths()):
        m=meta(path);url=m['url'];text=path.read_text(encoding='utf-8');s=BeautifulSoup(text,'html.parser')
        if SPAM.search(s.get_text(' ',strip=True)):
            REJECTED.append({'source':'Visit Astana','url':url,'reason':'unrelated_gambling_spam_in_source_page'});continue
        name=select_text(s,'.teatr_ban_title','.banner--gastronomy-single-container h1','.banner--gastronomy-single-container h2','h1')
        if not name or urlparse(url).query:continue
        # Detail pages have a banner and/or a substantive local description.
        description=select_text(s,'.center_info:not(.sad_history) .center_text','.banner--gastronomy-single-sec-info','.gastronomy-single__about-text-container')
        if not description:continue
        coords=re.search(r'center\s*:\s*\[\s*(5[01]\.\d+)\s*,\s*(7[01]\.\d+)\s*\]',text)
        lat,lon=(float(coords[1]),float(coords[2])) if coords else (None,None)
        if lat is not None and not (50.98<=lat<=51.34 and 71.18<=lon<=71.75):
            REJECTED.append({'source':'Visit Astana','url':url,'reason':'outside_study_bbox_coordinates'});continue
        directory_type=directory_types.get(url)
        cat='food_drink' if 'where-to-eat' in url else ('wellness' if '/wellness/' in url else ('quiet_spaces' if '/coworking/' in url else 'sightseeing'))
        cat={'culture':'culture','history':'culture','leisure':'entertainment','parks':'nature','galleries':'culture','sec':'shopping','sports-complexes':'sport'}.get(directory_type,cat)
        p=blank('visitastana:'+hashlib.sha256(url.encode()).hexdigest()[:16])
        p.update({'external_ids':{'visitastana':url},'name':name,'display_name':name,'name_ru':name,'latitude':lat,'longitude':lon,'category':cat,'subcategory':'restaurant' if cat=='food_drink' else 'tourism_directory','short_description':description,'description_type':'source_text','source_url':url,'last_updated_at':m['collected_at'],'sources':[{'name':'Visit Astana','url':url,'collected_at':m['collected_at'],'license':None}],'derived_fields':['category','subcategory'],'address':select_text(s,'.teatr_ban_info','.banner--gastronomy-single-address'),'raw_osm_tags':{},'image_candidates':None})
        p['coordinate_method']='official_page_map_center_unverified'
        p['coordinate_is_verified_entrance']=False
        p['directory_category']=directory_type
        if directory_type:p['subcategory']={'history':'museum','culture':'theatre','parks':'park','galleries':'gallery','sec':'mall','sports-complexes':'sports_centre'}.get(directory_type,directory_type)
        if directory_type=='locations':p['photo_spot']=True;p['derived_fields'].append('photo_spot')
        content=s.select_one('section.sad_history')
        if content:
            content_text=content.get_text(' ',strip=True)
            for anchor in content.select('a[href]'):
                href=anchor['href']
                host=urlparse(href).netloc
                if host and host not in ('www.instagram.com','instagram.com','www.youtube.com','youtube.com','2gis.kz','visitastana.kz','www.visitastana.kz') and href.startswith('https://'):p['website']=href
            numbers=re.findall(r'\+7\s*\(\d{3,4}\)\s*[\d\s‒–-]{6,16}',content_text)
            if numbers:p['phone']='; '.join(x.strip() for x in numbers[:2])
            hm=re.search(r'(?:ежедневно|Ежедневно)\s*[:—-]?\s*(\d{1,2}:\d{2})\s*[-–]\s*(\d{1,2}:\d{2})',content_text)
            if hm:p['opening_hours']=f'Mo-Su {hm[1]}-{hm[2]}'
        for item in s.select('.gastronomy-single__contacts-item'):
            label=select_text(item,'.gastronomy-single__contacts-item-header') or ''
            value=select_text(item,'.gastronomy-single__contacts-item-text')
            if 'Адрес' in label and value:p['address']=value
            if 'Телефон' in label and value:p['phone']=value
        hours=select_text(s,'.banner--gastronomy-single-schedule') or p.get('opening_hours')
        p['opening_hours']=hours
        if hours:p['opening_hours_observed_at']=m['collected_at']
        price=select_text(s,'.banner--gastronomy-single-price')
        if price and re.search(r'\d',price):
            p['estimated_visit_budget']={'amount':int(''.join(re.findall(r'\d+',price))),'currency':'KZT','basis':'published_price_category_or_average_check'}
        for item in s.select('.gastronomy-single__about-info-item'):
            label=select_text(item,'.gastronomy-single__about-info-item-label') or ''
            value=select_text(item,'.gastronomy-single__about-info-item-value') or ''
            if 'Посадочных мест' in label and re.search(r'\d+',value):p['seating']={'capacity':int(re.search(r'\d+',value)[0])}
        for a in s.select('a[href]'):
            href=a['href']
            if href.startswith('tel:') and href!='tel:15800':p['phone']=href[4:]
            if '2gis.' in href and '/firm/' in href:p['external_ids']['2gis']=href
        out.append(p)
    return out

def merge_official(pois,official):
    candidates=[]
    for p in official:
        same=[]
        for q in pois:
            if not q.get('name'):continue
            names=[name_key(q.get(k)) for k in ('name','name_ru','name_kk','name_en') if q.get(k)]
            key=name_key(p['name'])
            sim=max(difflib.SequenceMatcher(None,key,n).ratio() for n in names)
            if any(len(n)>=6 and len(key)>=6 and (n in key or key in n) for n in names):sim=max(sim,.95)
            dist=distance((p['latitude'],p['longitude']),(q['latitude'],q['longitude'])) if p['latitude'] is not None else None
            # Coordinate centres on official pages can be generic: require name agreement.
            if sim>=.90 and (dist is None or dist<=150):same.append((sim,q,dist))
        if same:
            sim,target,dist=max(same,key=lambda x:x[0]);p['matched_poi_id']=target['poi_id']
            target['external_ids']['visitastana']=p['source_url'];target['sources']+=p['sources']
            for field in POI_FIELDS:
                val=p.get(field)
                if val is None or field in ('poi_id','source_url','external_ids','latitude','longitude','category','subcategory','tags'):continue
                if field=='short_description' and target['description_type']=='derived_template':
                    target[field]=val;target['description_type']='source_text';target['derived_fields'].remove('short_description')
                elif target.get(field) is None:target[field]=val
                elif target.get(field)!=val and field in ('opening_hours','phone','address','estimated_visit_budget'):
                    CONFLICTS.append({'poi_id':target['poi_id'],'field_name':field,'canonical_value':target[field],'alternate_value':val,'alternate_source_url':p['source_url'],'note':'different representations may be equivalent; unresolved'})
            target['official_match']={'name_similarity':round(sim,3),'coordinate_distance_m':round(dist,1) if dist is not None else None,'method':'name_and_optional_spatial_match','manually_verified':False}
        elif p['latitude'] is not None:
            target=p;pois.append(p)
        else:
            candidates.append(p);target=p
        for field in POI_FIELDS:
            fact(target,field,p.get(field),'Visit Astana',p['source_url'],p['last_updated_at'],method='html_structured_selector',score=.8,derived=field in p['derived_fields'],license=None)
    return candidates

def infrastructure():
    path=RAW/'osm_infrastructure.json';stamp=meta(path)['collected_at'];out=[]
    for e in load(path,{'elements':[]})['elements']:
        lat,lon=point(e)
        if lat is None:continue
        t=e.get('tags',{});kinds=[]
        if t.get('highway')=='bus_stop' or t.get('public_transport') in ('platform','stop_position','station'):kinds.append('transit_stop')
        if t.get('entrance'):kinds.append('entrance_exit')
        if t.get('barrier'):kinds.append('barrier')
        if t.get('amenity'):kinds.append(t['amenity'])
        out.append({'infrastructure_id':f'osm:{e["type"]}:{e["id"]}','name':t.get('name'),'latitude':lat,'longitude':lon,'kinds':kinds,'opening_hours':t.get('opening_hours'),'wheelchair_accessible':truth(t.get('wheelchair')),'source_url':f'https://www.openstreetmap.org/{e["type"]}/{e["id"]}','collected_at':stamp,'license':'ODbL-1.0','raw_osm_tags':t})
    return out

def nearby(pois,infra):
    stops=[s for s in infra if 'transit_stop' in s['kinds']]
    entrances=[s for s in infra if 'entrance_exit' in s['kinds']]
    for items,field,radius in [(stops,'nearby_transit_stops',500),(entrances,'entrances_exits',60)]:
        if not items:continue
        tree=cKDTree([xy(x['latitude'],x['longitude']) for x in items])
        for p in pois:
            indices=tree.query_ball_point(xy(p['latitude'],p['longitude']),radius)
            matches=sorted([{'infrastructure_id':items[i]['infrastructure_id'],'straight_line_distance_m':round(distance((p['latitude'],p['longitude']),(items[i]['latitude'],items[i]['longitude'])),1),'association_verified':False} for i in indices],key=lambda x:x['straight_line_distance_m'])[:5]
            p[field]=matches or None
            if matches:p['derived_fields'].append(field);fact(p,field,matches,'OpenStreetMap',p['source_url'],NOW,method=f'spatial_proximity_within_{radius}m_not_verified_membership',derived=True,score=.5)

def events():
    result={}
    paths=[RAW/'visit_home.txt']+tourism_paths()
    for path in paths:
        text=path.read_text(encoding='utf-8');s=BeautifulSoup(text,'html.parser')
        if SPAM.search(s.get_text(' ',strip=True)):continue
        url=meta(path)['url'] or 'https://visitastana.kz/ru/'
        for title in s.select('.upcoming__title,.reccomend_title'):
            parent=title
            for _ in range(5):
                if re.search(r'\d{2}\.\d{2}\.\d{4}',parent.get_text(' ',strip=True)):break
                if parent.parent:parent=parent.parent
            dates=re.findall(r'\d{2}\.\d{2}\.\d{4}',parent.get_text(' ',strip=True))
            if not dates:continue
            name=title.get_text(' ',strip=True)
            start=datetime.strptime(dates[0],'%d.%m.%Y').date().isoformat();end=datetime.strptime(dates[-1],'%d.%m.%Y').date().isoformat()
            card=parent.parent if parent.parent else parent
            a=card.select_one('a.upcoming__buy') or card.select_one('a[href*=ticketon],a[href*=instagram]')
            key=(name,start,end)
            result[key]={'event_id':'event:'+hashlib.sha256('|'.join(key).encode()).hexdigest()[:16],'event_name':name,'event_start':start,'event_end':end,'date_precision':'day','timezone':'Asia/Qyzylorda','event_location':select_text(card,'.upcoming__address'),'event_coordinates':None,'event_description':None,'event_category':None,'event_price':None,'registration_url':urljoin(url,a['href']) if a else None,'event_age_group':None,'event_status':None,'listing_period_status':'past' if end<datetime.now(timezone.utc).date().isoformat() else 'upcoming_or_ongoing','event_verified_at':None,'collected_at':meta(path)['collected_at'],'source_url':url,'license':None,'verification_note':'Official listing retrieved; cancellation, venue and exact time not independently verified.'}
    return list(result.values())

def weather():
    path=RAW/'weather.txt';doc=load(path,{})
    if 'current' not in doc:return {}
    stamp=meta(path)['collected_at'];current=doc['current'];when=current['time']
    return {'source_url':'https://api.open-meteo.com/v1/forecast','source_name':'Open-Meteo','license':'CC-BY-4.0','collected_at':stamp,'weather_valid_at':when,'timezone':doc['timezone'],'utc_offset_seconds':doc['utc_offset_seconds'],'current_weather':current,'temperature':current.get('temperature_2m'),'feels_like':current.get('apparent_temperature'),'wind_speed':{'value':current.get('wind_speed_10m'),'unit':doc['current_units']['wind_speed_10m']},'precipitation_forecast':doc.get('hourly'),'sunset_time':doc.get('daily',{}).get('sunset'),'seasonality':{'value':'autumn' if int(when[5:7]) in (9,10,11) else ('winter' if int(when[5:7]) in (12,1,2) else ('spring' if int(when[5:7]) in (3,4,5) else 'summer')),'derived_value':True,'method':'northern_hemisphere_calendar_season'},'weather_alerts':None,'transit_service_hours':None,'units':{'current':doc.get('current_units'),'hourly':doc.get('hourly_units'),'daily':doc.get('daily_units')},'refresh_recommended_after_min':15,'note':'Snapshot only: request fresh weather at recommendation time. Official severe-weather alerts are not supplied by this endpoint.'}

def database(pois,infra,ev):
    path=OUT/'smart_city.sqlite'
    if path.exists():path.unlink()
    db=sqlite3.connect(path)
    db.executescript('CREATE TABLE pois(poi_id TEXT PRIMARY KEY,name TEXT,category TEXT,subcategory TEXT,latitude REAL,longitude REAL,payload_json TEXT); CREATE VIRTUAL TABLE poi_search USING fts5(poi_id UNINDEXED,text,tokenize="unicode61"); CREATE TABLE facts(poi_id TEXT,field_name TEXT,source_name TEXT,payload_json TEXT); CREATE INDEX fact_lookup ON facts(poi_id,field_name); CREATE TABLE infrastructure(infrastructure_id TEXT PRIMARY KEY,payload_json TEXT); CREATE TABLE events(event_id TEXT PRIMARY KEY,payload_json TEXT);')
    db.executemany('INSERT INTO pois VALUES(?,?,?,?,?,?,?)',[(p['poi_id'],p['display_name'],p['category'],p['subcategory'],p['latitude'],p['longitude'],json.dumps(p,ensure_ascii=False)) for p in pois])
    db.executemany('INSERT INTO poi_search VALUES(?,?)',[(p['poi_id'],' '.join(str(p.get(k) or '') for k in ('name','name_ru','name_kk','name_en','short_description','category','subcategory','tags','address'))) for p in pois])
    db.executemany('INSERT INTO facts VALUES(?,?,?,?)',[(f['poi_id'],f['field_name'],f['source_name'],json.dumps(f,ensure_ascii=False)) for f in FACTS])
    db.executemany('INSERT INTO infrastructure VALUES(?,?)',[(p['infrastructure_id'],json.dumps(p,ensure_ascii=False)) for p in infra])
    db.executemany('INSERT INTO events VALUES(?,?)',[(e['event_id'],json.dumps(e,ensure_ascii=False)) for e in ev])
    db.commit();db.close()

def main():
    pois=deduplicate(osm_pois());official=official_pois();unlocated=merge_official(pois,official)
    infra=infrastructure();nearby(pois,infra);ev=events();wx=weather()
    # Every canonical field disagreement is retained, rather than silently overwritten.
    conflict_keys={(c['poi_id'],c['field_name']) for c in CONFLICTS}
    for f in FACTS:f['source_conflict']=(f['poi_id'],f['field_name']) in conflict_keys
    known_ids={p['poi_id'] for p in pois}|{p['poi_id'] for p in unlocated}
    assert all(f['poi_id'] in known_ids for f in FACTS)
    jsonl(OUT/'pois.jsonl',pois);jsonl(OUT/'facts.jsonl',FACTS);jsonl(OUT/'infrastructure.jsonl',infra);jsonl(OUT/'events.jsonl',ev);jsonl(OUT/'official_unlocated.jsonl',unlocated)
    jsonl(OUT/'official_records.jsonl',official)
    save(OUT/'weather_snapshot.json',wx);save(OUT/'schema.json',SCHEMA);save(OUT/'duplicates.json',DUPLICATES);save(OUT/'rejected_sources.json',REJECTED);save(OUT/'source_conflicts.json',CONFLICTS)
    save(OUT/'pois.geojson',{'type':'FeatureCollection','features':[{'type':'Feature','geometry':{'type':'Point','coordinates':[p['longitude'],p['latitude']]},'properties':{k:p.get(k) for k in ('poi_id','display_name','name_ru','name_kk','name_en','category','subcategory','source_url','short_description','description_type')}} for p in pois]})
    jsonl(OUT/'rag_documents.jsonl',[{'id':p['poi_id'],'text':'\n'.join(filter(None,[p['display_name'],p['short_description'],p['address'],'Категория: '+p['category'],'Теги: '+', '.join(p['tags'] or [])])), 'metadata':{k:p.get(k) for k in ('poi_id','latitude','longitude','category','source_url','last_updated_at','description_type','opening_hours')},'structured_facts':{k:p.get(k) for k in POI_FIELDS}} for p in pois])
    database(pois,infra,ev)
    counts={field:sum(p.get(field) is not None for p in pois) for field in POI_FIELDS}
    summary={'created_at':NOW,'study_bbox_south_west_north_east':[50.98,71.18,51.34,71.75],'area_note':'Urban Astana study rectangle, including airport; not exact administrative boundary and not a completeness census.','poi_count':len(pois),'named_poi_count':sum(bool(p.get('name')) for p in pois),'category_counts':dict(collections.Counter(p['category'] for p in pois)),'source_description_count':sum(p['description_type']=='source_text' for p in pois),'template_description_count':sum(p['description_type']=='derived_template' for p in pois),'official_records':len(official),'official_unlocated':len(unlocated),'official_matched':sum('official_match' in p for p in pois),'infrastructure_count':len(infra),'infrastructure_counts':dict(collections.Counter(k for p in infra for k in p['kinds'])),'events_count':len(ev),'facts_count':len(FACTS),'duplicates_removed':len(DUPLICATES),'source_conflicts_count':len(CONFLICTS),'quarantined_sources_count':len(REJECTED),'field_coverage':counts,'confidence_method':'Heuristic evidence tiers, not calibrated probabilities: OSM explicit field 0.70; official structured HTML 0.80; derived classification/template/spatial association 0.50. No independent verification is implied.','missing_data_rule':'null means unknown; absence of a tag never means false.'}
    save(OUT/'summary.json',summary)
    print(json.dumps({k:v for k,v in summary.items() if k!='field_coverage'},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
