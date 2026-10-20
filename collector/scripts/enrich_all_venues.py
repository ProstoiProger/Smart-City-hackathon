"""Per-object audit of prices, published visiting constraints and closure claims.

Every POI is represented; unavailable evidence remains unavailable. A directory
listing is not proof of physical operation, and a chain menu is not a verified
branch price list.
"""
from collections import Counter,defaultdict
import hashlib
import json
import re
import sqlite3
from urllib.parse import urlparse
from scripts.build_dataset import ROOT,RAW,OUT,NOW,load,save,jsonl
from scripts.enrich_extended import rows,Sources,Update,clean

VERSION='all_venues_v1'
PRICE_TAGS={
 'food_service_avg_price':('average_check','visit'),
 'food_service_lunch_cost':('business_lunch','meal'),
 'fitness_month_unltd_subscription_price':('fitness_subscription','month'),
 'fitness_year_unltd_subscription_price':('fitness_subscription','year'),
 'sauna_hour_price':('sauna_rental','hour'),
 'barbershop_female_haircut_starting_price':('haircut_women','service'),
 'barbershop_male_haircut_price':('haircut_men','service'),
}
RULE_FIELDS=['access_restrictions','age_restrictions','pet_friendly','stroller_accessible','reservation_required','booking_required','reservation_available']

def provider_id(p):
    m=re.search(r'(?:firm/)?(\d{10,})',str(p.get('external_ids',{}).get('2gis','')))
    return m[1] if m else None

def parse_provider_prices(item,source):
    result=[]
    for group in item.get('attribute_groups') or []:
        for attr in group.get('attributes') or []:
            code=attr.get('tag');kind_unit=PRICE_TAGS.get(code)
            if not kind_unit:continue
            text=clean(attr.get('name'));numbers=[int(re.sub(r'\s','',n)) for n in re.findall(r'\d[\d \u00a0]*',text) if n.strip()]
            if not numbers:continue
            kind,unit=kind_unit
            result.append({'kind':kind,'unit':unit,'amount_min':numbers[0],'amount_max':numbers[-1],'currency':'KZT','raw':text,'is_from_price':'от ' in text.casefold(),'source_attribute':code,'source_url':source['url'],'collected_at':source['collected_at'],'scope':'provider_branch_attribute','note':'Published average check is not an entrance ticket or a complete menu.' if kind=='average_check' else 'Source tariff, not independently verified.'})
    return result

def closure_claim(item):
    """Interpret explicit flags only; omission and unknown dates never imply open."""
    flags=item.get('flags') or {};flag=flags.get('temporary_closed')
    if item.get('is_deleted') is True:
        return {'state':'removed_from_provider_catalog','raw_is_deleted':True,'physical_closure_verified':False,'note':'Removal from the directory is not independent evidence of permanent physical closure.'}
    if flag=='opening_soon':
        return {'state':'opening_soon_as_reported_by_2gis','provider_flag':flag,'parameters':flags.get('temporary_closed_parameters'),'physical_closure_verified':False}
    if flag is not None and flag is not False:
        return {'state':'temporarily_closed_as_reported_by_2gis','provider_flag':flag,'parameters':flags.get('temporary_closed_parameters'),'physical_closure_verified':False,'note':'unknown is the value of an explicit temporary_closed flag; the reopening date/reason is unspecified. A past planned opening date does not confirm reopening.'}
    return {'state':'no_explicit_closure_flag_returned','physical_closure_verified':False,'note':'Absence of a closure flag does not establish that the venue is operating.'}

def walk_json(value):
    if isinstance(value,dict):
        yield value
        for child in value.values():
            if isinstance(child,(dict,list)):yield from walk_json(child)
    elif isinstance(value,list):
        for child in value:yield from walk_json(child)

def extract_document(s,scope):
    source_id=hashlib.sha256(s['url'].encode()).hexdigest()[:20]
    soup=s['soup'];root=soup.select_one('main') or soup.select_one('article') or soup.body or soup
    text=root.get_text('\n',strip=True);title=clean(soup.title.get_text() if soup.title else '')
    bad=re.search(r'vavada|вавада|1xbet|betwinner|казино\s+онлайн',text,re.I)
    if bad:return {'source_id':source_id,'url':s['url'],'status':'quarantined_unrelated_content','collected_at':s['collected_at']},[],[]
    price_items=[];seen=set()
    def append_price(label,minimum,maximum,currency,evidence,method):
        try:lo=float(str(minimum).replace(' ','').replace('\xa0','').replace(',','.'));hi=float(str(maximum if maximum is not None else minimum).replace(' ','').replace('\xa0','').replace(',','.'))
        except (ValueError,TypeError):return
        if not (0<=lo<=hi<=100000000):return
        key=(clean(label),lo,hi,currency)
        if key in seen:return
        seen.add(key)
        price_items.append({'price_item_id':source_id+':p'+str(len(price_items)),'source_id':source_id,'label':clean(label)[:220],'amount_min':lo,'amount_max':hi,'currency':currency,'source_url':s['url'],'collected_at':s['collected_at'],'extraction_method':method,'scope':scope,'evidence_text':clean(evidence)[:500],'branch_applicability_verified':False,'valid_until':None})
    # Prefer structured product/service offers over unrelated numbers in page text.
    for node in walk_json(s['ld']):
        if node.get('@type') not in ('Product','MenuItem','Service','TouristAttraction','Offer','AggregateOffer'):continue
        offers=node.get('offers') or (node if node.get('@type') in ('Offer','AggregateOffer') else [])
        if isinstance(offers,dict):offers=[offers]
        if not isinstance(offers,list):continue
        for offer in offers:
            if not isinstance(offer,dict):continue
            currency=offer.get('priceCurrency')
            if not currency:continue
            append_price(node.get('name') or offer.get('name') or 'published offer',offer.get('price',offer.get('lowPrice')),offer.get('highPrice'),currency,str(offer),'schema_org_offer')
    # Currency must be explicit; a serving weight or phone number is not a price.
    lines=[clean(x) for x in text.splitlines() if clean(x)]
    for i,line in enumerate(lines):
        m=re.search(r'(?<![\d\w])(?P<price>\d{1,3}(?:[ \xa0]\d{3})+|\d{2,7})(?:[.,]\d{2})?\s*(?P<currency>₸|тг\b|тенге\b|KZT\b)',line,re.I)
        if not m:continue
        label=line[:m.start()].strip(' —:-')
        if len(label)<3 and i:label=lines[i-1]
        if any(w in label.casefold() for w in ['телефон','итого','корзина','промокод','кэшбэк','cashback','аренда всего здания']):continue
        append_price(label,m['price'],None,'KZT',line,'explicit_currency_text')
    visitor_context=bool(re.search(r'правила\s+посещ|посетител|дресс.?код|prohibit|visitor|гост(?:и|ей|ям)|не допуска|запрещ',title+' '+text,re.I))
    privacy=bool(re.search(r'политика\s+конфиденциальности|privacy\s+policy|обработк[аи]\s+персональных\s+данных',title,re.I))
    rules=[]
    if visitor_context and not privacy:
        for line in lines:
            if not 15<=len(line)<=1200:continue
            if not re.search(r'запрещ|не допуска|обязаны|обязан|допускаются только|вход разреш|дресс.?код|сопровожд|возрастн|pets|prohibited|not allowed|children under',line,re.I):continue
            if re.search(r'cookie|персональн|обработк[аи] данных|копирован|интеллектуальн|материалов сайта|правообладател|реклам[ау]',line,re.I):continue
            rules.append({'rule_id':source_id+':r'+str(len(rules)),'source_id':source_id,'text':line,'source_url':s['url'],'collected_at':s['collected_at'],'scope':scope,'independently_verified':False})
    return {'source_id':source_id,'url':s['url'],'title':title,'collected_at':s['collected_at'],'status':'parsed','scope':scope,'price_items':len(price_items),'visitor_rule_clauses':len(rules),'currency_and_branch_note':'Foreign-currency or chain-level offers must not be used as confirmed Astana branch prices.'},price_items,rules

def main():
    pois=rows('pois.jsonl');update=Update(pois);sources=Sources();source_index=load(RAW/'extended_index.json',[])
    all_facts=rows('facts.jsonl');facts_by=defaultdict(list)
    for f in all_facts:
        if f.get('pipeline_module')!=VERSION:facts_by[(f['poi_id'],f['field_name'])].append(f)
    provider={};provider_sources={}
    for r in rows('dgis_records.jsonl'):
        provider[r['dgis_id']]=r['data'];provider_sources[r['dgis_id']]={'url':r['source_url'],'source_name':'2GIS Places API','collected_at':r['collected_at'],'license':'2GIS proprietary'}
    refreshed={};byid_audit={}
    for path in sorted((RAW/'venue_details').glob('*.json')):
        wrapper=load(path,{})
        for item in wrapper.get('response',{}).get('result',{}).get('items',[]):
            oid=str(item.get('id','')).split('_')[0]
            if not oid:continue
            refreshed[oid]=item;byid_audit[oid]={'snapshot':path.relative_to(ROOT).as_posix(),'collected_at':wrapper['collected_at']}
    host_pois=defaultdict(list)
    for p in pois:
        url=p.get('website')
        if isinstance(url,str):host_pois[(urlparse(url if '://' in url else 'https://'+url).hostname or '').removeprefix('www.')].append(p['poi_id'])
    docs=[];price_items=[];rule_items=[];docs_by_host=defaultdict(list)
    aggregators={'ticketon.kz','topbilet.kz','instagram.com','facebook.com','2gis.kz','yandex.kz','google.com'}
    for url in sources.index:
        host=(urlparse(url).hostname or '').removeprefix('www.')
        if host not in host_pois:continue
        linked_ids=host_pois[host]
        if host in aggregators:
            linked_ids=[p['poi_id'] for p in pois if p['poi_id'] in host_pois[host] and isinstance(p.get('website'),str) and p['website'].rstrip('/')==url.rstrip('/')]
            if not linked_ids:continue
        scope='website_link_shared_by_multiple_pois_branch_applicability_unverified' if len(host_pois[host])>1 else 'website_link_from_single_poi_subvenue_applicability_requires_review'
        s=sources.get(url);doc,prices,rules=extract_document(s,scope)
        doc['linked_poi_ids']=linked_ids;docs.append(doc);price_items+=prices;rule_items+=rules;docs_by_host[host].append(doc)
    unique_prices={}
    for entry in price_items:
        url=urlparse(entry['source_url']);key=(url.hostname,url.path,entry['label'],entry['amount_min'],entry['amount_max'],entry['currency'])
        if key not in unique_prices:
            entry['price_item_id']='price:'+hashlib.sha256(json.dumps(key,ensure_ascii=False).encode()).hexdigest()[:24]
            entry['corroborating_source_urls']=[entry['source_url']];unique_prices[key]=entry
        elif entry['source_url'] not in unique_prices[key]['corroborating_source_urls']:unique_prices[key]['corroborating_source_urls'].append(entry['source_url'])
    price_items=list(unique_prices.values())
    # Per-object data is separate from shared document item lists to avoid copying
    # a corporate menu into thousands of individual branch records.
    records=[];counts=Counter();closure_changes=[]
    for p in pois:
        pid=p['poi_id'];oid=provider_id(p);item=provider.get(oid,{});fresh=refreshed.get(oid)
        source=provider_sources.get(oid)
        entries=[];price_seen=set()
        if item and source:entries+=parse_provider_prices(item,source)
        if fresh:
            fs={'url':f'https://2gis.kz/astana/firm/{oid}','source_name':'2GIS Places API by ID','collected_at':byid_audit[oid]['collected_at'],'license':'2GIS proprietary'}
            # A complete refreshed attribute value takes precedence for that tariff.
            new=parse_provider_prices(fresh,fs);new_tags={e['source_attribute'] for e in new}
            entries=[e for e in entries if e['source_attribute'] not in new_tags]+new
            avg=next((e for e in new if e['kind']=='average_check'),None)
            if avg:update.set(p,'estimated_visit_budget',{'amount_min':avg['amount_min'],'amount_max':avg['amount_max'],'currency':'KZT','basis':'2gis_published_average_check','raw':avg['raw']},fs,avg['raw'],method='refreshed_explicit_provider_average_check',score=.7)
            item_for_closure=fresh;cs=fs
        else:item_for_closure=item;cs=source
        for field,kind in [('adult_ticket_price','adult_entry_ticket'),('child_ticket_price','child_entry_ticket'),('estimated_visit_budget','estimated_visit_budget')]:
            value=p.get(field)
            if not value:continue
            evidence=facts_by.get((pid,field),[]);f=evidence[-1] if evidence else {}
            if field=='estimated_visit_budget' and isinstance(value,dict) and value.get('basis')=='2gis_published_average_check' and any(e['kind']=='average_check' for e in entries):continue
            if isinstance(value,dict):entries.append({'kind':kind,'unit':'entry' if 'ticket' in field else 'visit','value':value,'currency':value.get('currency'),'source_url':f.get('source_url') or p['source_url'],'collected_at':f.get('collected_at') or p['last_updated_at'],'scope':'existing_published_or_derived_field','derived_value':f.get('derived_value',False)})
        if p.get('free_entry') is True:
            evidence=facts_by.get((pid,'free_entry'),[]);f=evidence[-1] if evidence else {}
            entries.append({'kind':'explicit_free_entry','unit':'entry','amount_min':0,'amount_max':0,'currency':'KZT','source_url':f.get('source_url') or p['source_url'],'collected_at':f.get('collected_at') or p['last_updated_at'],'scope':'explicit_free_entry_claim_not_inferred_from_category'})
        for e in entries:
            key=(e['kind'],json.dumps(e.get('value') or [e.get('amount_min'),e.get('amount_max')],sort_keys=True,ensure_ascii=False))
            price_seen.add(key)
        host=(urlparse(p.get('website') if isinstance(p.get('website'),str) and '://' in p['website'] else 'https://'+str(p.get('website') or '')).hostname or '').removeprefix('www.')
        linked_docs=[d for d in docs_by_host.get(host,[]) if pid in d['linked_poi_ids']]
        parsed=[d for d in linked_docs if d['status']=='parsed']
        price_refs=[d['source_id'] for d in parsed if d.get('price_items')]
        rule_refs=[d['source_id'] for d in parsed if d.get('visitor_rule_clauses')]
        pricing={'status':'has_published_branch_price_or_budget' if entries else ('linked_price_documents_branch_unverified' if price_refs else 'unknown_no_published_price_found'),'entries':entries,'price_document_ids':price_refs,'complete_menu_or_all_tariffs_verified':False,'note':'Price kind is explicit: entrance, average check, lunch, subscription or hourly rental. A missing price never means free entry.'}
        constraints=[]
        for field in RULE_FIELDS:
            value=p.get(field)
            if value is None:continue
            evidence=facts_by.get((pid,field),[]);f=evidence[-1] if evidence else {}
            constraints.append({'field':field,'value':value,'source_url':f.get('source_url') or p['source_url'],'collected_at':f.get('collected_at') or p['last_updated_at'],'scope':p.get('wheelchair_accessibility_scope') if field=='stroller_accessible' else 'published claim; source and subvenue scope must be read'})
        if p.get('raw_osm_tags',{}).get('access'):
            constraints.append({'field':'osm_access','value':p['raw_osm_tags']['access'],'source_url':p['source_url'],'collected_at':p['last_updated_at'],'scope':'OSM mapped access restriction'})
        rules={'status':'has_published_constraints' if constraints else ('linked_policy_documents_branch_unverified' if rule_refs else 'unknown_no_venue_rules_found'),'constraints':constraints,'policy_document_ids':rule_refs,'full_visit_policy_verified':False,'note':'Reservation availability is separate from mandatory reservation. Rules of a greenhouse, event or rented room do not automatically apply to an entire park or complex.'}
        closure=closure_claim(item_for_closure) if item_for_closure else {'state':'unknown_no_provider_status_source','physical_closure_verified':False}
        closure['source_url']=cs['url'] if cs else p['source_url'];closure['observed_at']=cs['collected_at'] if cs else None
        if p.get('operational_status') in ('temporarily_closed','permanently_closed','open_as_published'):
            closure['additional_explicit_status']=p['operational_status'];closure['additional_source_facts']=[{'value':f['field_value'],'source_url':f['source_url'],'collected_at':f['collected_at']} for f in facts_by.get((pid,'operational_status'),[]) if f.get('field_value')==p['operational_status']][-3:]
        if closure['state'] in ('temporarily_closed_as_reported_by_2gis','opening_soon_as_reported_by_2gis','removed_from_provider_catalog') and cs:
            old=p.get('operational_status')
            # Explicit official closure information is preserved alongside provider claims.
            if old not in ('temporarily_closed','permanently_closed'):
                update.set(p,'operational_status',closure['state'],cs,json.dumps(item_for_closure.get('flags') or {},ensure_ascii=False),method='explicit_provider_closure_flag_not_independent_verification',score=.7)
            if closure['state']!='removed_from_provider_catalog':update.set(p,'temporary_closure',closure,cs,json.dumps(item_for_closure.get('flags') or {},ensure_ascii=False),method='explicit_provider_closure_flag_not_independent_verification',score=.7,overwrite=old not in ('temporarily_closed','permanently_closed'))
            update.set(p,'closure_reports',[closure],cs,'Explicit provider flag; no independent field verification',score=.7)
            closure_changes.append({'poi_id':pid,'field_name':'operational_status','previous_value':old,'new_value':p['operational_status'],'chosen_source_url':cs['url'],'reason':'closure flag was previously retained only in raw provider data'})
        audits=[]
        if oid:audits.append({'source':'2GIS by ID','status':'returned' if fresh else 'no_refreshed_response','external_id':oid,**byid_audit.get(oid,{})})
        for r in source_index:
            if (urlparse(r['url']).hostname or '').removeprefix('www.')==host and host:audits.append({'source':'linked website','url':r['url'],'status':'response_saved' if r.get('path') else 'unavailable','error':r.get('error')})
        if not audits:audits.append({'source':'existing OSM/tourism facts','status':'no_direct_business_status_or_price_source_identified','note':'No price or operating claim was fabricated from object category.'})
        record={'poi_id':pid,'name':p['display_name'],'category':p['category'],'pricing':pricing,'visit_rules':rules,'closure_assessment':closure,'source_audit':audits,'processed_at':NOW}
        p['pricing']=pricing;p['visit_rules']=rules;p['closure_assessment']=closure;p['venue_enrichment_audit']={'processed_at':NOW,'source_attempts':len(audits),'provider_id_refreshed':bool(fresh),'all_three_fields_complete':False}
        records.append(record);counts['objects_processed']+=1
        counts['objects_with_branch_price_or_budget']+=bool(entries);counts['objects_linked_to_price_documents']+=bool(price_refs);counts['objects_with_published_constraints']+=bool(constraints);counts['objects_linked_to_policy_documents']+=bool(rule_refs);counts['explicit_provider_closure_flags']+=closure['state'] in ('temporarily_closed_as_reported_by_2gis','opening_soon_as_reported_by_2gis');counts['provider_ids_refreshed']+=bool(fresh)
    for f in update.facts:f['pipeline_module']=VERSION
    facts=[f for f in all_facts if f.get('pipeline_module')!=VERSION]+update.facts
    jsonl(OUT/'pois.jsonl',pois);jsonl(OUT/'facts.jsonl',facts);jsonl(OUT/'venue_conditions.jsonl',records);jsonl(OUT/'published_price_items.jsonl',price_items);jsonl(OUT/'published_visit_rules.jsonl',rule_items);jsonl(OUT/'venue_policy_sources.jsonl',docs)
    save(OUT/'all_venue_source_conflicts.json',update.conflicts)
    save(OUT/'all_venue_enrichment_summary.json',{'created_at':NOW,**dict(counts),'shared_source_price_items':len(price_items),'shared_source_policy_clauses':len(rule_items),'source_documents':len(docs),'all_prices_all_rules_all_statuses_complete':False,'limitations':['Not all places publish prices, a visitor policy or an operational-status claim.','A directory response without a closure flag does not mean physically open.','Shared chain price documents have not been verified for each branch.','Adult/child entrance fees are not substituted with restaurant average checks.']})
    db=sqlite3.connect(OUT/'smart_city.sqlite')
    db.executemany('UPDATE pois SET payload_json=? WHERE poi_id=?',[(json.dumps(p,ensure_ascii=False),p['poi_id']) for p in pois])
    for table,items,key in [('venue_conditions',records,'poi_id'),('published_price_items',price_items,'price_item_id'),('published_visit_rules',rule_items,'rule_id')]:
        db.execute(f'CREATE TABLE IF NOT EXISTS {table}(id TEXT PRIMARY KEY,payload_json TEXT)');db.execute(f'DELETE FROM {table}');db.executemany(f'INSERT INTO {table} VALUES(?,?)',[(x[key],json.dumps(x,ensure_ascii=False)) for x in items])
    db.commit();db.close()
    print(json.dumps(load(OUT/'all_venue_enrichment_summary.json'),ensure_ascii=False,indent=2))

if __name__=='__main__':main()
