"""Rebuild the provider snapshot from every saved response, merging field coverage."""
import json
from scripts.build_dataset import RAW,OUT,NOW,jsonl,save,load

def main():
    records={};snapshots=0
    for path in sorted((RAW/'dgis').glob('*.json')):
        doc=load(path,{});snapshots+=1;query=doc.get('params',{}).get('q','')
        for item in doc.get('response',{}).get('result',{}).get('items',[]):
            if not item.get('id'):continue
            object_id=str(item['id']).split('_')[0]
            if object_id not in records:
                records[object_id]={'dgis_id':object_id,'data':{},'matched_queries':[],'collected_at':doc['collected_at'],'source_url':f'https://2gis.kz/astana/firm/{object_id}','source_name':'2GIS Places API','license':'2GIS proprietary','source_snapshot_files':[]}
            record=records[object_id];previous=record['data']
            # Different search contexts expose different attribute groups for one object.
            groups={}
            for group in (previous.get('attribute_groups') or [])+(item.get('attribute_groups') or []):
                key=group.get('name','')
                if key not in groups:groups[key]={**group,'attributes':[]}
                attrs={str(a.get('tag') or a.get('id') or a.get('name')):a for a in groups[key]['attributes']}
                attrs.update({str(a.get('tag') or a.get('id') or a.get('name')):a for a in group.get('attributes',[])})
                groups[key]['attributes']=list(attrs.values())
            if doc['collected_at']>=record['collected_at']:
                previous.update({k:v for k,v in item.items() if v is not None})
            else:
                for k,v in item.items():
                    if k not in previous and v is not None:previous[k]=v
            if groups:previous['attribute_groups']=list(groups.values())
            record['collected_at']=max(record['collected_at'],doc['collected_at'])
            if query and query not in record['matched_queries']:record['matched_queries'].append(query)
            record['source_snapshot_files'].append('data/raw/dgis/'+path.name)
    jsonl(OUT/'dgis_records.jsonl',records.values())
    save(OUT/'dgis_snapshot_summary.json',{'consolidated_at':NOW,'cached_responses':snapshots,'unique_records':len(records),'source_query_total_note':'Search/category coverage may overlap and change during collection; unique object IDs define the saved record count.'})
    print('Consolidated 2GIS:',len(records),'unique records from',snapshots,'cached responses',flush=True)

if __name__=='__main__':main()
