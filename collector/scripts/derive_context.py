"""Fill only explicitly marked estimates and rating-count popularity proxies."""
import json
import sqlite3
from scripts.build_dataset import OUT,NOW,jsonl,load,save

DURATION={'food_drink':40,'nightlife':60,'culture':90,'quiet_spaces':60,'nature':60,'children':40,'entertainment':90,'sport':60,'shopping':90,'sightseeing':20,'infrastructure':10,'wellness':90}

def main():
    pois=[json.loads(x) for x in (OUT/'pois.jsonl').read_text(encoding='utf-8').splitlines()]
    facts=[]
    zero_ids=set()
    for p in pois:
        if p.get('rating')==0:
            p['rating']=None;p['rating_source']=None
            p['rating_unavailable_reason']='provider returned zero; raw value retained in raw_2gis_reviews, not interpreted as a 1-to-5 rating'
            zero_ids.add(p['poi_id'])
        values={}
        if p.get('suggested_visit_duration_min') is None and p['category'] in DURATION:
            values['suggested_visit_duration_min']=DURATION[p['category']]
        if p.get('popularity') is None and p.get('ratings_count') is not None:
            values['popularity']={'metric':'ratings_count','value':p['ratings_count'],'is_proxy':True,'live_crowding':False,'source':p.get('rating_source')}
        for field,value in values.items():
            p[field]=value;p.setdefault('derived_fields',[]).append(field)
            facts.append({'poi_id':p['poi_id'],'field_name':field,'field_value':value,'source_name':'local_explicit_heuristics','source_url':p['source_url'],'collected_at':NOW,'verified_at':None,'verification_method':'category_duration_rule' if field=='suggested_visit_duration_min' else 'rating_count_popularity_proxy_not_live_crowding','confidence_score':.5,'license':None,'source_conflict':False,'stale_data':None,'derived_value':True,'user_generated_opinion':False})
    jsonl(OUT/'pois.jsonl',pois)
    if zero_ids:
        source_facts=[json.loads(x) for x in (OUT/'facts.jsonl').read_text(encoding='utf-8').splitlines()]
        for f in source_facts:
            if f['poi_id'] in zero_ids and f['field_name']=='rating' and f['field_value']==0:
                f['verification_method']='raw_provider_zero_retained; excluded_from_canonical_1_to_5_rating'
                f['confidence_score']=.3
        jsonl(OUT/'facts.jsonl',source_facts)
        provider=OUT/'dgis_pois.jsonl'
        if provider.exists():
            provider_rows=[json.loads(x) for x in provider.read_text(encoding='utf-8').splitlines()]
            for p in provider_rows:
                if p.get('rating')==0:
                    p['rating']=None;p['rating_source']=None
                    p['rating_unavailable_reason']='provider returned zero; raw value retained separately'
            jsonl(provider,provider_rows)
            summary_path=OUT/'dgis_enrichment_summary.json'
            summary=load(summary_path,{})
            if summary:
                for field in ('rating','rating_source'):
                    summary.setdefault('provider_field_coverage',{})[field]=sum(p.get(field) is not None for p in provider_rows)
                save(summary_path,summary)
    with (OUT/'facts.jsonl').open('a',encoding='utf-8') as stream:
        for f in facts:stream.write(json.dumps(f,ensure_ascii=False,separators=(',',':'))+'\n')
    db=sqlite3.connect(OUT/'smart_city.sqlite')
    db.executemany('UPDATE pois SET payload_json=? WHERE poi_id=?',[(json.dumps(p,ensure_ascii=False),p['poi_id']) for p in pois]);db.commit();db.close()
    print('Additional explicitly derived context facts:',len(facts))

if __name__=='__main__':main()
