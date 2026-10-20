"""Enrich from finite public snapshots with evidence and explicit scope limits."""
from collections import Counter,defaultdict
from datetime import datetime,timezone,timedelta
import difflib
import hashlib
import json
import re
import sqlite3
import html
from urllib.parse import urlparse
from bs4 import BeautifulSoup
from scripts.build_dataset import ROOT,RAW,OUT,NOW,load,save,jsonl,blank,meta,name_key
from scripts.enrich_dataset import parse_hours,strip_html

MODULE='extended_v1'
def rows(name):
    p=OUT/name
    return [json.loads(x) for x in p.read_text(encoding='utf-8').splitlines()] if p.exists() else []

def clean(text):return re.sub(r'\s+',' ',BeautifulSoup(str(text or ''),'html.parser').get_text(' ',strip=True)).replace('\x00','').strip()

def decode_body(body):
    if 'Ð' in body or 'Ñ' in body:
        try:return body.encode('latin1').decode('utf-8')
        except UnicodeError:pass
    return body

class Sources:
    def __init__(self):
        self.index={x['url']:x for x in load(RAW/'extended_index.json',[]) if x.get('path')}
        self.cache={}
    def get(self,url):
        if url in self.cache:return self.cache[url]
        record=self.index.get(url)
        if not record:return None
        path=ROOT/record['path']
        if record.get('content_type')=='application/pdf':
            soup=BeautifulSoup('<main>'+html.escape((ROOT/record['text_path']).read_text(encoding='utf-8'))+'</main>','html.parser')
        else:soup=BeautifulSoup(decode_body(path.read_text(encoding='utf-8')),'html.parser')
        ld=[]
        for script in soup.select('script[type="application/ld+json"]'):
            try:ld.append(json.loads(script.string or script.get_text()))
            except (ValueError,TypeError):pass
        result={'url':url,'soup':soup,'ld':ld,'collected_at':meta(path)['collected_at'],'source_name':urlparse(url).hostname,'license':None}
        text_soup=BeautifulSoup(str(soup),'html.parser')
        for x in text_soup(['script','style','nav','header','footer']):x.decompose()
        result['text']=text_soup.get_text('\n',strip=True)
        self.cache[url]=result
        return result

class Update:
    def __init__(self,pois):self.pois=pois;self.byid={p['poi_id']:p for p in pois};self.facts=[];self.conflicts=[];self.counts=Counter()
    def set(self,p,field,value,s,evidence,method='explicit_saved_source',score=.8,derived=False,opinion=False,overwrite=True):
        if value is None:return
        old=p.get(field)
        if not overwrite and old is not None:return
        if old is not None and old!=value:
            self.conflicts.append({'poi_id':p['poi_id'],'field_name':field,'previous_value':old,'new_value':value,'chosen_source_url':s['url'],'reason':method})
        p[field]=value;p['last_updated_at']=max(p.get('last_updated_at') or '',s['collected_at'])
        p.setdefault('sources',[])
        if not any(x['url']==s['url'] for x in p['sources']):p['sources'].append({'name':s['source_name'],'url':s['url'],'collected_at':s['collected_at'],'license':s.get('license')})
        if derived and field not in p.setdefault('derived_fields',[]):p['derived_fields'].append(field)
        self.facts.append({'poi_id':p['poi_id'],'field_name':field,'field_value':value,'source_name':s['source_name'],'source_url':s['url'],'collected_at':s['collected_at'],'verified_at':None,'verification_method':method,'confidence_score':score,'license':s.get('license'),'source_conflict':old is not None and old!=value,'stale_data':None,'derived_value':derived,'user_generated_opinion':opinion,'evidence_text':clean(evidence)[:900],'pipeline_module':MODULE})
        self.counts[field]+=1
    def new(self,pid,name,lat,lon,category,subcategory,source,coordinate_method):
        if pid in self.byid:return self.byid[pid]
        p=blank(pid);p.update({'name':name,'display_name':name,'name_ru':name,'latitude':lat,'longitude':lon,'category':category,'subcategory':subcategory,'tags':[],'external_ids':{'official_site':source['url']},'source_url':source['url'],'last_updated_at':source['collected_at'],'sources':[],'description_type':'source_text','raw_osm_tags':{},'coordinate_method':coordinate_method,'coordinate_is_verified_entrance':False,'derived_fields':[]})
        self.pois.append(p);self.byid[pid]=p
        for field in ('name_ru','latitude','longitude','category','subcategory'):self.set(p,field,p[field],source,coordinate_method)
        return p
    def hours(self,p,value,s,evidence):
        self.set(p,'opening_hours',value,s,evidence)
        parsed=parse_hours(value)
        if parsed:
            p['opening_hours_by_day']=parsed['weekly'];self.set(p,'is_24_7',value=='24/7',s,evidence,method='parse_explicit_schedule',derived=True)
            if parsed['break_hours']:self.set(p,'break_hours',parsed['break_hours'],s,evidence,method='parse_explicit_schedule',derived=True)

def all_ld(value):
    if isinstance(value,list):
        for v in value:yield from all_ld(v)
    elif isinstance(value,dict):
        yield value
        if '@graph' in value:yield from all_ld(value['@graph'])

def enrich_tags(update):
    for p in update.pois:
        tags=p.get('raw_osm_tags') or {}
        osm_source=next((x for x in p.get('sources',[]) if x.get('name')=='OpenStreetMap'),{})
        s={'url':f'https://www.openstreetmap.org/{p["poi_id"].split(":")[1]}/{p["poi_id"].split(":")[-1]}' if p['poi_id'].startswith('osm:') else p['source_url'],'source_name':'OpenStreetMap','collected_at':osm_source.get('collected_at') or p.get('last_updated_at') or NOW,'license':'ODbL-1.0'}
        for key,field in [('covered','weather_shelter'),('socket','power_outlets')]:
            if tags.get(key) in ('yes','no'):update.set(p,field,tags[key]=='yes',s,f'{key}={tags[key]}',overwrite=False)
        indoor=tags.get('indoor');indoor_seating=tags.get('indoor_seating');outdoor_seating=tags.get('outdoor_seating')
        if indoor in ('yes','no'):update.set(p,'indoor_outdoor','indoor' if indoor=='yes' else 'outdoor',s,f'indoor={indoor}',overwrite=False)
        elif indoor_seating=='yes' and outdoor_seating=='yes':update.set(p,'indoor_outdoor','both',s,'indoor_seating=yes; outdoor_seating=yes',overwrite=False)
        if indoor_seating or outdoor_seating:update.set(p,'seating_area_types',{'indoor':indoor_seating,'outdoor':outdoor_seating},s,'Explicit OSM seating tags')
        if tags.get('description') and p.get('description_type')!='source_text':
            update.set(p,'short_description',clean(tags['description'])[:700],s,tags['description']);p['description_type']='source_text'
        if re.fullmatch(r'\d{4}-\d{2}-\d{2}',tags.get('check_date:opening_hours','')):
            update.set(p,'source_hours_checked_at',tags['check_date:opening_hours'],s,'check_date:opening_hours; source contributor claim, not our independent verification')
        attrs={a.get('tag'):a for a in p.get('raw_2gis_attributes') or [] if a.get('tag')}
        if not attrs:continue
        provider_source=next((x for x in p.get('sources',[]) if x.get('name')=='2GIS Places API'),{})
        s={'url':f'https://2gis.kz/astana/firm/{p.get("external_ids",{}).get("2gis") or p["poi_id"].split(":")[-1]}','source_name':'2GIS Places API','collected_at':provider_source.get('collected_at') or p.get('last_updated_at') or NOW,'license':'2GIS proprietary'}
        if 'food_service_details_food_table_reservation' in attrs:update.set(p,'reservation_available',True,s,attrs['food_service_details_food_table_reservation']['name'])
        ins=[k for k in ('pool_indoor','courts_indoor_court','ice_rink_indoor','summer_attractions_karting_type_indoor_karting') if k in attrs]
        outs=[k for k in ('pool_outdoor','courts_outdoor_court','ice_rink_outdoor') if k in attrs]
        if ins or outs:
            update.set(p,'indoor_outdoor','both' if ins and outs else ('indoor' if ins else 'outdoor'),s,'; '.join(attrs[k]['name'] for k in ins+outs),overwrite=False)
            p['indoor_outdoor_scope']='facility types explicitly listed; not a building-wide accessibility claim'
        if 'food_service_infrastructure_outdoor_tables_eat_out' in attrs:update.set(p,'outdoor_seating',True,s,attrs['food_service_infrastructure_outdoor_tables_eat_out']['name'])
        if 'additionalgarbage_availability_access_restricted' in attrs:update.set(p,'access_restrictions',{'description':'Доступ ограничен','source_scope':'provider explicit tag; conditions unspecified'},s,'Доступ ограничен',overwrite=False)

def manual_places(update,sources):
    for url,pid in [
        ('https://astanews.kz/mesta/kofejnya-barista-coffee-prospekt-koshkarbaeva-astana/','dgis:70000001032066906'),
        ('https://astanews.kz/mesta/kofejnya-tary-ulicza-akmeshit-astana/','dgis:70000001091792646')]:
        source=sources.get(url);place=update.byid.get(pid)
        if source and place and re.search(r'розетки',source['text'],re.I):
            evidence=' '.join(re.findall(r'[^\n.]*розетки[^\n.]*',source['text'],re.I))[:600]
            for field in ('power_outlets','wifi_available','laptop_friendly'):update.set(place,field,True,source,evidence,method='explicit_editorial_branch_description; not_independently_inspected',score=.7)
            place['power_outlets_scope']='Published editorial claim for this street-address branch; current availability and placement not independently checked.'
            place['amenity_evidence_scope']='Third-party editorial listing, not an official venue guarantee.'
    alem=sources.get('https://alem.ai/')
    if alem:
        p=update.new('official:alem_ai_museum','Музей Сингулярности alem.ai',51.0892,71.4161,'culture','interactive_museum',alem,'coordinates from official site Google Maps link; not independently verified entrance')
        for field,value in [('website','https://alem.ai/'),('phone','+7 777 522 02 47'),('address','Астана, проспект Мангилик Ел, B1'),('short_description','Интерактивный Музей Сингулярности на первом этаже центра alem.ai знакомит посетителей с развитием искусственного интеллекта. Вход платный; предусмотрены льготные категории.'),('interactive_exhibits',True),('indoor_outdoor','indoor'),('free_entry',False),('adult_ticket_price',{'amount':2500,'currency':'KZT','ticket_type':'входной билет','valid_until':None}),('discounts',[{'eligibility':'дети до 7 лет; лица с инвалидностью и сопровождающие; дети-сироты и дети без попечения родителей; многодетные матери; участники и ветераны ВОВ','price':0,'currency':'KZT'},{'eligibility':'пенсионеры','condition':'по вторникам; подтверждающий документ','price':0,'currency':'KZT'}]),('operational_status','open_as_published')]:
            update.set(p,field,value,alem,alem['text'][:1200])
        update.hours(p,'Mo off; Tu-Su 10:00-18:30',alem,'10:00-18:30 ВТ-ВС, ПН - Технический день')
    old=sources.get('https://qazexpocongress.kz/ru/nur-alem/')
    if old and 'прекратил прием посетителей' in old['text']:
        notice={'place_name':'Музей энергии будущего NUR ALEM','status':'permanently_closed_as_museum','effective_since':'2024-12','successor_place_id':'official:alem_ai_museum','source_url':old['url'],'collected_at':old['collected_at'],'evidence':'С декабря 2024 года Музей энергии будущего завершил свою работу и прекратил прием посетителей.','note':'Building and EXPO territory are not closed. Old museum hours on the same page are historical.'}
        save(OUT/'closed_place_notices.json',[notice])
        for p in update.pois:
            if re.search(r'(?:nur\s*alem|нур\s*алем|нұр\s*әлем)',p.get('display_name',''),re.I) and p['category']=='culture':
                update.set(p,'operational_status','permanently_closed',old,notice['evidence']);update.set(p,'opening_hours',None,old,notice['evidence'])
                p['opening_hours']=None;p['opening_hours_by_day']=None;p['is_24_7']=None;p['successor_place_id']='official:alem_ai_museum'
    shop=sources.get('https://ailand.kz/ru/shop/')
    ocean=update.byid.get('dgis:70000001018081165')
    if shop and ocean:
        for kind,field in [('Стандарт','adult_ticket_price'),('Детский','child_ticket_price')]:
            m=re.search(r'Океанариум\s*[—–-]\s*'+kind+r'\s+([\d\s\xa0]+)\s*₸',shop['text'])
            if m:update.set(ocean,field,{'amount':int(re.sub(r'\s','',m[1])),'currency':'KZT','ticket_type':kind,'valid_until':None},shop,m[0])
        update.set(ocean,'website','https://ailand.kz/ru/attractions/ocean-ru/',shop,'Official Ailand shop linked attraction');update.set(ocean,'free_entry',False,shop,'Paid standard and child tickets listed')
        jungle_source=sources.get('https://ailand.kz/ru/attractions/jungle-ru/')
        if jungle_source:
            p=update.new('official:ailand_jungle','Джунгли Ailand',ocean['latitude'],ocean['longitude'],'entertainment','jungle_exhibition',jungle_source,'parent Ailand venue point; exact subvenue and entrance not verified')
            update.set(p,'short_description','Тематическая экспозиция «Джунгли» в центре семейного отдыха Ailand. Посещение проводится по сеансам; билеты для детей и стандартные билеты продаются отдельно.',jungle_source,'Official attraction page and linked ticket shop')
            update.set(p,'website',jungle_source['url'],jungle_source,'Official attraction page');update.set(p,'indoor_outdoor','indoor',jungle_source,jungle_source['text'][:300],method='explicit_themed_indoor_exhibition')
            update.set(p,'free_entry',False,shop,'Paid jungle tickets listed')
            for kind,field in [('Стандарт','adult_ticket_price'),('Детский','child_ticket_price')]:
                m=re.search(r'Джунгли\s*[—–-]\s*'+kind+r'\s+([\d\s\xa0]+)\s*₸',shop['text'])
                if m:update.set(p,field,{'amount':int(re.sub(r'\s','',m[1])),'currency':'KZT','ticket_type':kind,'valid_until':None},shop,m[0])
    green=sources.get('https://astanabotsad.kz/pravila')
    if green:
        p=update.byid.get('dgis:70000001047796501') or update.byid.get('dgis:70000001061518573')
        if p:
            update.hours(p,'Mo off; Tu-Su 10:00-13:00,14:00-19:00',green,'Каждый день (кроме понедельника) с 10:00 до 19:00. Обед: с 13:00 до 14:00')
            for field,value,evidence in [('indoor_outdoor','indoor','Правила посещения оранжерей'),('stroller_accessible',False,'Запрещено заходить в оранжереи на роликах, с колясками, самокатами, велосипедами'),('pet_friendly',False,'Домашние животные не допускаются'),('age_restrictions',{'under_12':'only with an adult'},'Дети до 12 лет допускаются только в сопровождении взрослых'),('access_restrictions',{'scope':'greenhouses only','rules':['children under 12 accompanied by adults','no pets','no strollers, rollers, scooters or bicycles','no food or drinks']},'Правила оранжерей; не распространять автоматически на открытый парк')]:update.set(p,field,value,green,evidence)
            update.set(p,'website','https://astanabotsad.kz/ru',green,'Official botanical garden site')
    iq=sources.get('https://iqwork.me/coworking/')
    p=update.byid.get('dgis:70000001033835901')
    if iq and p:
        for field,value,evidence in [('wifi_available',True,'Возможность подключения к проводной и беспроводной сетям'),('laptop_friendly',True,'Персональные рабочие места'),('website',iq['url'],'Official IQ coworking page'),('phone','+7 701 755 88 98','+7 701 755 88 98')]:update.set(p,field,value,iq,evidence)
    connect=sources.get('https://connect-ms.kz/');p=update.byid.get('dgis:70000001095205402')
    if connect and p:
        for field,value,evidence in [('website',connect['url'],'Official Connect site'),('parking',True,'Большая парковка, обеспечивающая комфортное размещение автомобилей для всех клиентов'),('reservation_available',True,'Забронировать переговорные и офисы'),('laptop_friendly',True,'Зона с рабочим столом; смарт-офисы')]:update.set(p,field,value,connect,evidence)
    vo=sources.get('https://www.vodvore.kz/')
    if vo:
        mapping=[('dgis:70000001074434109','+7 701 445 55 56'),('dgis:70000001114648253','+7 701 300 11 56'),('dgis:70000001117573531','+7 702 051 27 12')]
        for pid,phone in mapping:
            p=update.byid.get(pid)
            if not p:continue
            update.set(p,'website',vo['url'],vo,'Official branch list');update.set(p,'phone',phone,vo,phone);update.hours(p,'Mo-Su 12:00-02:00',vo,'Ежедневно · 12:00—02:00');update.set(p,'reservation_available',True,vo,'Бронируйте столик по телефону или в WhatsApp')
        p=update.byid.get('dgis:70000001042877028')
        if p and 'Ориентировочное открытие — декабрь 2026' in vo['text']:
            update.set(p,'temporary_closure',{'reason':'обновление интерьера','reopening_estimate':'2026-12','estimate_not_guaranteed':True},vo,'Куйши Дина, 11/1. Временно закрыт. Ориентировочное открытие — декабрь 2026')
            update.set(p,'operational_status','temporarily_closed',vo,'Куйши Дина, 11/1. Временно закрыт')
        p=update.byid.get('dgis:70000001114648253')
        if p:
            update.set(p,'review_topics',[{'topic':'quiet_atmosphere','polarity':'positive','scope':'one testimonial selected by business; not representative of all reviews','source_origin':'business-hosted attributed 2GIS testimonial'}],vo,'Тихо, душевно, приятная музыка и атмосфера',method='topic_from_one_attributed_testimonial',derived=True,opinion=True,score=.5)
            update.set(p,'quiet_place',True,vo,'Тихо, душевно, приятная музыка и атмосфера',method='one_subjective_testimonial_not_noise_measurement',opinion=True,score=.5)
            p['quiet_place_scope']='single selected customer testimonial; no measured noise level or general guarantee'

def enrich_wikidata(update):
    path=RAW/'supplementary/wikidata.json';doc=load(path,{})
    commons=load(RAW/'supplementary/commons_images.json',{});photos={}
    for page in commons.get('query',{}).get('pages',{}).values():
        for info in page.get('imageinfo',[]):
            em=info.get('extmetadata',{});value=lambda k:em.get(k,{}).get('value')
            license=strip_html(value('LicenseShortName'))
            if not (license.startswith(('CC BY','CC0')) or license in ('Public domain','PDM')):continue
            photos[page.get('title','').replace('_',' ')]={'url':info.get('thumburl') or info.get('url'),'original_url':info.get('url'),'source_url':info.get('descriptionurl'),'title':page.get('title'),'license':license,'license_url':value('LicenseUrl'),'author':strip_html(value('Artist')),'credit':strip_html(value('Credit')),'rights_metadata_collected_at':meta(RAW/'supplementary/commons_images.json')['collected_at'],'rights_verification_method':'Commons license allowlist and Wikidata P18 link','depicts_poi_verified':False,'note':'Linked by Wikidata P18; individual license applies; no independent visual subject check.'}
    for p in update.pois:
        qids=re.findall(r'Q\d+',p.get('raw_osm_tags',{}).get('wikidata',''))
        if len(qids)!=1:continue
        qid=qids[0];e=doc.get('entities',{}).get(qid,{})
        if not e:continue
        s={'url':f'https://www.wikidata.org/wiki/{qid}','source_name':'Wikidata','collected_at':meta(path)['collected_at'],'license':'CC0-1.0'}
        for lang in ('ru','kk','en'):
            value=e.get('labels',{}).get(lang,{}).get('value')
            if value:update.set(p,'name_'+lang,value,s,'Wikidata label linked by explicit OSM wikidata tag',overwrite=False)
        desc=e.get('descriptions',{}).get('ru',{}).get('value')
        if desc:update.set(p,'wikidata_description',desc,s,'Wikidata entity description')
        images=[]
        for claim in e.get('claims',{}).get('P18',[])[:2]:
            name=claim.get('mainsnak',{}).get('datavalue',{}).get('value');photo=photos.get(('File:'+str(name)).replace('_',' '))
            if photo:images.append(photo)
        if images:
            merged={ph['source_url']:ph for ph in (p.get('photos') or [])+images}
            ps={'url':images[0]['source_url'],'source_name':'Wikimedia Commons','collected_at':images[0]['rights_metadata_collected_at'],'license':images[0]['license']}
            update.set(p,'photos',list(merged.values()),ps,'Wikidata P18 -> Commons explicit author and license metadata',score=.7)

def enrich_websites(update,sources):
    byhost=defaultdict(list)
    for p in update.pois:
        u=p.get('website')
        if isinstance(u,str):byhost[(urlparse(u).hostname or '').removeprefix('www.')].append(p)
    audit=[]
    for url,record in sources.index.items():
        host=(urlparse(url).hostname or '').removeprefix('www.');matches=byhost.get(host,[])
        if len(matches)!=1:continue
        p=matches[0];s=sources.get(url);soup=s['soup'];text=s['text']
        if re.search(r'vavada|вавада|1xbet|betwinner|казино\s+онлайн',text,re.I):
            audit.append({'url':url,'poi_id':p['poi_id'],'status':'quarantined_unrelated_gambling_content'});continue
        if len(text)<120 or any(word in text[:1500].casefold() for word in ['access denied','just a moment','домен прода','домен припарк','account suspended','сайт на стадии']):
            audit.append({'url':url,'poi_id':p['poi_id'],'status':'not_used_content_unavailable'});continue
        description=soup.find('meta',attrs={'name':'description'}) or soup.find('meta',attrs={'property':'og:description'})
        if description:
            d=clean(description.get('content',''))
            # Use short self-descriptions only for a single mapped venue and clear identity overlap.
            name=name_key(p.get('name'));title=name_key((soup.title.get_text() if soup.title else '')+' '+d)
            tokens=[x for x in re.findall(r'\w+',p.get('display_name','').casefold()) if len(x)>3 and x not in ('ресторан','кофейня','гостиница','библиотека','комплекс','театр','центр','музей','отель','кафе')]
            identity=any(t in (soup.title.get_text() if soup.title else '').casefold() for t in tokens)
            if 60<=len(d)<=800 and identity:
                update.set(p,'website_description',d,s,d)
                if p.get('description_type')!='source_text':update.set(p,'short_description',d,s,d);p['description_type']='source_text'
        for node in all_ld(s['ld']):
            if node.get('@type') not in ('LocalBusiness','Restaurant','CafeOrCoffeeShop','Museum','Hotel','Library','SportsActivityLocation','TouristAttraction'):continue
            if node.get('telephone'):update.set(p,'phone',str(node['telephone']),s,'Schema.org telephone',overwrite=False)
        # Public phone links are retained separately when branch ownership is uncertain.
        phones=list(dict.fromkeys(a.get('href')[4:] for a in soup.select('a[href^="tel:"]')))
        if phones:update.set(p,'website_contact_phones',phones,s,'Public telephone links; single mapped venue, contacts not independently called')
        audit.append({'url':url,'poi_id':p['poi_id'],'status':'parsed','has_description':bool(description)})
    save(OUT/'business_website_audit.json',audit)

def match_venue(name,pois):
    aliases=[(r'qazaqconcert|қазақконцерт|казахконцерт','osm:node:13395423568'),(r'astana\s*opera|астана\s*опера','osm:way:917478479'),(r'астанинский\s*цирк|столичный\s*цирк','dgis:70000001018126667')]
    for pattern,pid in aliases:
        if re.search(pattern,name,re.I):return next((p for p in pois if p['poi_id']==pid),None)
    key=name_key(name)
    if len(key)<5:return None
    candidates=[p for p in pois if p['category'] in ('culture','sport','entertainment','nightlife') and difflib.SequenceMatcher(None,key,name_key(p.get('name'))).ratio()>=.92]
    return candidates[0] if len(candidates)==1 else None

def parse_ticketon(s,pois):
    """Expand source-listed occurrences; never claim an entire date range is continuous."""
    result=[];excluded=[]
    if '/cinema/' in s['url']:return [],[{'url':s['url'],'reason':'movie catalogue spans multiple cities; local screenings not established'}]
    for root in all_ld(s['ld']):
        if not str(root.get('@type','')).endswith('Event'):continue
        children=root.get('subEvent') or [root]
        if isinstance(children,dict):children=[children]
        age=re.search(r'Возрастное ограничение\s*(\d{1,2}\+)',s['text']) or re.search(r'^.*?\n(\d{1,2}\+)\n',s['text'])
        for item in children:
            start=item.get('startDate') or root.get('startDate')
            if not start:continue
            location=item.get('location') or root.get('location') or {};address=location.get('address') or {}
            if not isinstance(location,dict) or not isinstance(address,dict):continue
            city=clean(address.get('addressLocality'))
            if city.casefold() not in ('астана','astana','нур-султан','nur-sultan'):
                excluded.append({'url':s['url'],'event_name':root.get('name'),'reason':'event locality is not explicitly Astana','locality':city});continue
            end=item.get('endDate') or (root.get('endDate') if item is root else None)
            duration=item.get('duration') or root.get('duration')
            if not end and duration and 'T' in start:
                m=re.fullmatch(r'PT(?:(\d+)H)?(?:(\d+)M)?',duration)
                if m:end=(datetime.fromisoformat(start)+timedelta(hours=int(m[1] or 0),minutes=int(m[2] or 0))).isoformat()
            name=clean(item.get('name') or root.get('name'));venue=clean(location.get('name'));p=match_venue(venue,pois)
            geo=location.get('geo') or {};coordinates=None
            try:
                lat=float(geo['latitude']);lon=float(geo['longitude'])
                if 50.98<=lat<=51.34 and 71.18<=lon<=71.75:coordinates={'latitude':lat,'longitude':lon}
            except (ValueError,TypeError,KeyError):pass
            if not coordinates and p:coordinates={'latitude':p['latitude'],'longitude':p['longitude']}
            offer=item.get('offers') or root.get('offers') or {};offer=offer[0] if isinstance(offer,list) and offer else offer
            price=None
            if isinstance(offer,dict) and offer.get('price') is not None:
                try:price={'amount_min':float(offer['price']),'currency':offer.get('priceCurrency'),'price_type':'published starting ticket price','availability':offer.get('availability'),'observed_at':s['collected_at']}
                except (ValueError,TypeError):pass
            status=item.get('eventStatus') or root.get('eventStatus')
            status=status.rsplit('/',1)[-1] if isinstance(status,str) else None
            range_listing=not root.get('subEvent') and end and end[:10]!=start[:10]
            result.append({'event_id':'ticketon:'+hashlib.sha256((s['url']+'|'+start+'|'+venue).encode()).hexdigest()[:20],'event_name':name,'event_start':start,'event_end':end,'date_precision':'listing_range_not_continuous' if range_listing else ('datetime' if 'T' in start else 'day'),'timezone':'Asia/Qyzylorda','event_location':venue,'event_address':address.get('streetAddress'),'event_coordinates':coordinates,'location_coordinate_method':'explicit_schema_geo' if geo else ('matched_public_venue_point_not_verified_entrance' if p else None),'venue_poi_id':p['poi_id'] if p else None,'event_description':clean(root.get('description'))[:650] or None,'event_category':str(root.get('@type')),'event_price':price,'registration_url':s['url'],'event_age_group':age[1] if age else None,'event_status':status,'event_verified_at':None,'event_status_observed_at':s['collected_at'],'status_verification_method':'publisher_schema_org_status; not independently confirmed with organiser','listing_period_status':'past' if (end or start)[:10]<NOW[:10] else 'upcoming_or_ongoing','source_url':s['url'],'source_name':'Freedom Ticketon','collected_at':s['collected_at'],'license':None,'pipeline_module':MODULE})
    return result,excluded

def enrich_events(sources,pois):
    existing=[e for e in rows('events.jsonl') if e.get('pipeline_module')!=MODULE];new=[];excluded=[]
    for url in sources.index:
        if 'ticketon.kz' in url and '/event/' in url:
            events,bad=parse_ticketon(sources.get(url),pois);new+=events;excluded+=bad
    unique={e['event_id']:e for e in new}
    # The official poster is corroborating evidence for the retailer listing, not a second event.
    by_registration=defaultdict(list)
    for e in unique.values():by_registration[e['registration_url'].split('?')[0]].append(e)
    for url in sources.index:
        if 'qazaqconcert.kz/ru/poster/' not in url:continue
        s=sources.get(url)
        for a in s['soup'].select('a[href]'):
            target=a.get('href','').split('?')[0].replace('ticketon.kz/kz/','ticketon.kz/')
            for e in by_registration.get(target,[]):
                e.setdefault('corroborating_sources',[]).append({'url':url,'collected_at':s['collected_at']})
    merged={e['event_id']:e for e in existing+list(unique.values())};events=list(merged.values())
    jsonl(OUT/'events.jsonl',events);save(OUT/'excluded_event_listings.json',excluded)
    save(OUT/'events_enrichment_summary.json',{'created_at':NOW,'new_occurrences':len(unique),'total_events':len(events),'upcoming_or_ongoing':sum(e.get('listing_period_status')=='upcoming_or_ongoing' for e in events),'excluded_listings':len(excluded),'note':'Some publisher date ranges are explicitly marked as ranges, not continuous performances. Status is the publisher claim as retrieved.'})
    return events

def enrich_transit():
    trips=[];legs=[];route_names=set()
    anchors=load(OUT/'demo_landmarks.json',{})
    for path in sorted((RAW/'dgis_transit').glob('*.json')):
        wrapper=load(path,{});doc=wrapper.get('response');variants=doc if isinstance(doc,list) else (doc or {}).get('result',[])
        for i,r in enumerate(variants):
            if r.get('pedestrian') is True:continue
            movement=r.get('movements',[])
            if not any(m.get('type')=='passage' for m in movement):continue
            pid='dgis_transit:'+path.stem+':'+str(i)
            for n,m in enumerate(movement):
                for line in m.get('routes') or []:route_names.update(line.get('names') or [])
                legs.append({'trip_id':pid,'sequence':n,'type':m.get('type'),'distance_m':m.get('distance'),'moving_duration_seconds':m.get('moving_duration'),'waiting_duration_seconds':m.get('waiting_duration'),'routes':m.get('routes'),'platforms':m.get('platforms'),'waypoint':m.get('waypoint'),'alternatives':m.get('alternatives')})
            trips.append({'trip_id':pid,'from_anchor':wrapper['from_anchor'],'to_anchor':wrapper['to_anchor'],'source_point':wrapper['params']['source']['point'],'target_point':wrapper['params']['target']['point'],'transit_duration_min':round(r['total_duration']/60,2) if r.get('total_duration') is not None else None,'total_distance_m':r.get('total_distance'),'transfer_count':r.get('transfer_count'),'moving_duration_seconds':sum(m.get('moving_duration') or 0 for m in movement),'waiting_duration_seconds':sum(m.get('waiting_duration') or 0 for m in movement),'service_departure_snapshots':r.get('schedules'),'source_url':wrapper['endpoint'],'collected_at':wrapper['collected_at'],'license':'2GIS proprietary','source_snapshot':path.relative_to(ROOT).as_posix(),'note':'Calculated route snapshot between fixed public demo coordinates; not a city-wide bus timetable or arrival guarantee.'})
    jsonl(OUT/'transit_routes.jsonl',trips);jsonl(OUT/'transit_legs.jsonl',legs)
    doc=load(RAW/'osm_transit.json',{});stamp=meta(RAW/'osm_transit.json')['collected_at'] if doc else NOW
    mapped=[{'route_id':f'osm:relation:{e["id"]}','name':e.get('tags',{}).get('name'),'mode':e.get('tags',{}).get('route'),'raw_tags':e.get('tags',{}),'ordered_members':e.get('members',[]),'source_url':f'https://www.openstreetmap.org/relation/{e["id"]}','source_updated_at':e.get('timestamp'),'collected_at':stamp,'operating_status_verified':False,'license':'ODbL-1.0'} for e in doc.get('elements',[])]
    jsonl(OUT/'mapped_transit_relations.jsonl',mapped)
    save(OUT/'transit_summary.json',{'created_at':NOW,'pair_count':len({(r['from_anchor'],r['to_anchor']) for r in trips}),'route_variants':len(trips),'legs':len(legs),'line_names_in_sample':sorted(route_names),'osm_relations':len(mapped),'full_gtfs_available':False,'service_hours_available':False,'limitations':['Provider route duration is a time-sensitive estimate, including walking and waiting.','Line geometry and intermediate stops describe only sampled journeys; not complete lines.','LRT is mapped in OSM but operating status has not been established.','No current official city-wide GTFS/timetable was obtained.']})
    return trips,legs,mapped

def enrich_weather():
    wrapper=load(RAW/'supplementary/storm_astana.json',{});doc=wrapper.get('response',{});wx=load(OUT/'weather_snapshot.json',{})
    filters=doc.get('filters') or {}
    if str(filters.get('region'))=='20':
        alerts=[]
        for item in doc.get('items') or []:
            if str(item.get('regionId'))!='20' and not any(str(r.get('id'))=='20' for r in item.get('regions',[])):continue
            alerts.append({'alert_id':'kazhydromet:'+str(item.get('ID')),'title':clean(item.get('name')),'description':clean(item.get('opis')),'issued_date':item.get('stormDate'),'validity_raw':clean(item.get('name')),'is_dangerous_as_published':item.get('isDangerous')==1,'source_url':item.get('attachment') or 'https://www.kazhydromet.kz/ru/storm','publisher_url':'https://www.kazhydromet.kz/ru/storm','collected_at':wrapper['collected_at'],'region_id':20,'region_name':'Астана','active_at_query_time_verified':False})
        wx['weather_alerts']={'source_name':'Kazhydromet','source_url':'https://www.kazhydromet.kz/ru/storm','collected_at':wrapper['collected_at'],'region_filter_confirmed':True,'items':alerts,'note':'Official warning snapshot. Read the published validity interval and refresh at request time; empty list would not be a guarantee of safety.'}
        save(OUT/'weather_alerts.json',wx['weather_alerts']);save(OUT/'weather_snapshot.json',wx)

def main():
    sources=Sources();update=Update(rows('pois.jsonl'));enrich_tags(update);manual_places(update,sources);enrich_wikidata(update);enrich_websites(update,sources)
    events=enrich_events(sources,update.pois);trips,legs,mapped=enrich_transit();enrich_weather()
    jsonl(OUT/'pois.jsonl',update.pois)
    facts=[f for f in rows('facts.jsonl') if f.get('pipeline_module')!=MODULE]+update.facts;jsonl(OUT/'facts.jsonl',facts)
    save(OUT/'extended_source_conflicts.json',update.conflicts)
    db=sqlite3.connect(OUT/'smart_city.sqlite')
    db.execute('DELETE FROM pois');db.executemany('INSERT INTO pois VALUES(?,?,?,?,?,?,?)',[(p['poi_id'],p.get('name'),p['category'],p['subcategory'],p['latitude'],p['longitude'],json.dumps(p,ensure_ascii=False)) for p in update.pois])
    db.execute('DELETE FROM poi_search');db.executemany('INSERT INTO poi_search VALUES(?,?)',[(p['poi_id'],' '.join(str(p.get(k) or '') for k in ('display_name','name_ru','name_kk','name_en','short_description','category','tags','address'))) for p in update.pois])
    db.execute('DELETE FROM events');db.executemany('INSERT INTO events VALUES(?,?)',[(e['event_id'],json.dumps(e,ensure_ascii=False)) for e in events])
    for table,items,key in [('transit_routes',trips,'trip_id'),('mapped_transit_relations',mapped,'route_id')]:
        db.execute(f'CREATE TABLE IF NOT EXISTS {table}(id TEXT PRIMARY KEY,payload_json TEXT)');db.execute(f'DELETE FROM {table}');db.executemany(f'INSERT INTO {table} VALUES(?,?)',[(x[key],json.dumps(x,ensure_ascii=False)) for x in items])
    db.commit();db.close()
    report={'created_at':NOW,'source_pages_available':len(sources.index),'facts_added':len(update.facts),'affected_pois':len({f['poi_id'] for f in update.facts}),'field_updates':dict(update.counts),'conflicts':len(update.conflicts),'poi_count':len(update.pois),'events':len(events),'transit_variants':len(trips)}
    save(OUT/'extended_enrichment_summary.json',report);print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
