"""Conservative hours parsing and Wikimedia photo-rights metadata."""
from datetime import datetime
import html
import json
import re
import sqlite3
import time
import os

from scripts.build_dataset import RAW, OUT, NOW, load, save, jsonl, fact, FACTS
from scripts.download_sources import download

DAYS=['Mo','Tu','We','Th','Fr','Sa','Su']

def parse_hours(raw):
    if not raw:return None
    if raw=='24/7':return {'weekly':{d:[['00:00','24:00']] for d in DAYS},'holiday_hours':None,'break_hours':None,'method':'conservative_OSM_subset','raw':raw}
    russian=re.fullmatch(r'с\s*(\d{1,2}:\d{2})\s*до\s*(\d{1,2}:\d{2})\s*ежедневно',raw.strip(),re.I)
    if russian:raw=f'Mo-Su {russian[1]}-{russian[2]}'
    weekly={d:None for d in DAYS};holidays=[];breaks={};assigned=False
    for clause in raw.split(';'):
        clause=clause.strip()
        if clause.startswith(('PH ','SH ')):
            holidays.append(clause);continue
        match=re.fullmatch(r'(?:(Mo|Tu|We|Th|Fr|Sa|Su)(?:-(Mo|Tu|We|Th|Fr|Sa|Su))?(?:,((?:(?:Mo|Tu|We|Th|Fr|Sa|Su),?)+))?\s+)?(off|closed|\d{1,2}:\d{2}-\d{1,2}:\d{2}(?:,\s*\d{1,2}:\d{2}-\d{1,2}:\d{2})*)',clause)
        if not match:return None
        first,last,extra,periods=match.groups()
        days=DAYS[:] if not first else [first]
        if last:
            a,b=DAYS.index(first),DAYS.index(last)
            days=DAYS[a:b+1] if a<=b else DAYS[a:]+DAYS[:b+1]
        if extra:days+=extra.split(',')
        intervals=[] if periods in ('off','closed') else [x.strip().split('-') for x in periods.split(',')]
        for pair in intervals:
            for value in pair:
                hour,minute=map(int,value.split(':'))
                if hour>24 or minute>59 or (hour==24 and minute!=0):return None
        for day in days:
            if weekly[day] is not None:return None # overlapping clauses require a complete parser
            weekly[day]=intervals;assigned=True
            if len(intervals)>1 and all(intervals[i][1]<intervals[i+1][0] for i in range(len(intervals)-1)):
                breaks[day]=[[intervals[i][1],intervals[i+1][0]] for i in range(len(intervals)-1)]
    if not assigned:return None
    # Unspecified days stay unknown; do not infer closed for partial schedules.
    return {'weekly':weekly,'holiday_hours':holidays or None,'break_hours':breaks or None,'method':'conservative_OSM_subset','raw':raw,'open_now_evaluated':False}

def strip_html(text):
    return html.unescape(re.sub('<[^>]+>','',text or '')).strip()

def photo_metadata(poi):
    cat=poi.get('image_candidates',{}).get('wikimedia_commons') if poi.get('image_candidates') else None
    if not cat:return None
    params={'action':'query','format':'json','prop':'imageinfo','iiprop':'url|extmetadata','iiurlwidth':1000}
    if cat.startswith('Category:'):params|={'generator':'categorymembers','gcmtitle':cat,'gcmtype':'file','gcmlimit':3}
    elif cat.startswith('File:'):params['titles']=cat
    else:return None
    import hashlib
    target=RAW/'commons'/(hashlib.sha256(cat.encode()).hexdigest()[:16]+'.json')
    try:
        if os.environ.get('ASTANA_OFFLINE')=='1':
            if not target.exists():return None
            doc=load(target,{})
        else:doc=json.loads(download('https://commons.wikimedia.org/w/api.php',target,params,timeout=30))
    except Exception as exc:
        return {'error':str(exc),'category':cat}
    photos=[]
    for page in doc.get('query',{}).get('pages',{}).values():
        for info in page.get('imageinfo',[]):
            metadata=info.get('extmetadata',{})
            def value(k):return metadata.get(k,{}).get('value')
            license_name=strip_html(value('LicenseShortName'));license_url=value('LicenseUrl')
            if not license_name or not (license_name.startswith(('CC BY','CC0')) or license_name in ('Public domain','PDM')):continue
            photos.append({'url':info.get('thumburl') or info.get('url'),'original_url':info.get('url'),'source_url':info.get('descriptionurl'),'title':page.get('title'),'license':license_name,'license_url':license_url,'author':strip_html(value('Artist')),'credit':strip_html(value('Credit')),'attribution':strip_html(value('Attribution')),'rights_metadata_collected_at':NOW,'rights_verification_method':'Wikimedia_Commons_extmetadata_license_allowlist','depicts_poi_verified':False,'note':'Category-associated image; check depicted subject before display. Follow this individual image license and attribution.'})
    return photos or None

def main():
    pois=[json.loads(x) for x in (OUT/'pois.jsonl').read_text(encoding='utf-8').splitlines()]
    errors=[];parsed_count=0;photo_count=0
    for p in pois:
        parsed=parse_hours(p.get('opening_hours'))
        p['opening_hours_by_day']=parsed['weekly'] if parsed else None
        if parsed:
            parsed_count+=1
            for field,value in [('opening_hours_by_day',parsed['weekly']),('break_hours',parsed['break_hours']),('holiday_hours',parsed['holiday_hours'])]:
                if value is not None:
                    p[field]=value
                    p.setdefault('derived_fields',[]).append(field)
                    fact(p,field,value,'local_conservative_hours_parser',p['source_url'],NOW,method='parse_supported_explicit_schedule_clauses; unspecified_days_unknown',derived=True,score=.5,license=None)
        photos=photo_metadata(p)
        if isinstance(photos,dict) and photos.get('error'):errors.append({'poi_id':p['poi_id'],**photos})
        elif photos:
            p['photos']=photos;photo_count+=1
            for photo in photos:fact(p,'photos',photo,'Wikimedia Commons',photo['source_url'],NOW,method='explicit_license_metadata',score=.7,license=photo['license'])
        if p.get('image_candidates'):time.sleep(.2)
    jsonl(OUT/'pois.jsonl',pois)
    with (OUT/'facts.jsonl').open('a',encoding='utf-8') as f:
        for row in FACTS:f.write(json.dumps(row,ensure_ascii=False,separators=(',',':'))+'\n')
    db=sqlite3.connect(OUT/'smart_city.sqlite')
    db.executemany('UPDATE pois SET payload_json=? WHERE poi_id=?',[(json.dumps(p,ensure_ascii=False),p['poi_id']) for p in pois])
    db.executemany('INSERT INTO facts VALUES(?,?,?,?)',[(f['poi_id'],f['field_name'],f['source_name'],json.dumps(f,ensure_ascii=False)) for f in FACTS]);db.commit();db.close()
    save(OUT/'enrichment_summary.json',{'created_at':NOW,'weekly_schedules_parsed':parsed_count,'poi_with_licensed_photo_metadata':photo_count,'photo_errors':errors,'schedule_limitations':'Only explicitly supported simple schedules are parsed. Complex syntax is retained verbatim; current opening status is never guessed.'})
    print('Parsed weekly schedules:',parsed_count,'POI with licensed photo metadata:',photo_count,'photo API errors:',len(errors),flush=True)

if __name__=='__main__':main()
