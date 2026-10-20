"""Package final data and the finite set of source snapshots needed to rebuild it."""
import hashlib
import argparse
import json
from pathlib import Path
import zipfile
from scripts.build_dataset import ROOT,RAW,OUT,load,save,NOW

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output-name',default='smart_city_astana_dataset.zip');args=parser.parse_args()
    if Path(args.output_name).name!=args.output_name or not args.output_name.endswith('.zip'):parser.error('--output-name must be a ZIP filename without directories')
    target=ROOT/'output';target.mkdir(exist_ok=True)
    files=set(OUT.glob('*'))
    files|={ROOT/x for x in ['README.md','DATA_REPORT.md','ENRICHMENT_REPORT.md','requirements.txt','collect.py','query.py','smart_city_parsing_checklist.md','.env.example','.gitignore']}
    files|=set((ROOT/'scripts').glob('*.py'))|set((ROOT/'tests').glob('*.py'))
    names=['osm_pois.json','osm_infrastructure.json','osm_network_geom.json','visit_home.txt','visit_robots.txt','weather.txt','tourism_index.json','extra_index.json']
    snapshots={RAW/n for n in names}
    snapshots|={ROOT/Path(p) for p in load(RAW/'tourism_index.json',{}).values()}
    snapshots|={ROOT/Path(p['path']) for p in load(RAW/'extra_index.json',[]) if p.get('path')}
    snapshots|=set((RAW/'commons').glob('*.json'))
    snapshots|=set((RAW/'dgis').glob('*.json'))
    snapshots|=set((RAW/'dgis_transit').glob('*.json'))
    snapshots|=set((RAW/'supplementary').glob('*.json'))
    snapshots|={RAW/'extended_index.json',RAW/'osm_transit.json'}
    snapshots|=set(RAW.glob('extended_urls_*.json'))
    snapshots|={ROOT/Path(r['path']) for r in load(RAW/'extended_index.json',[]) if r.get('path')}
    snapshots|={ROOT/Path(r['text_path']) for r in load(RAW/'extended_index.json',[]) if r.get('text_path')}
    snapshots|=set((RAW/'extended').glob('*.pdf'))|set((RAW/'extended').glob('*.text.json'))
    snapshots|={p for p in [RAW/'dgis_region.json',RAW/'dgis_rubric_ids.json'] if p.exists()}
    files|=snapshots
    files|={p.with_suffix(p.suffix+'.meta.json') for p in snapshots if p.with_suffix(p.suffix+'.meta.json').exists()}
    files={p.resolve() for p in files if p.is_file()}
    assert all(p.is_relative_to(ROOT.resolve()) for p in files)
    assert not any(p.name=='.env' for p in files), 'Credential file must never be packaged.'
    from scripts.dgis_client import load_key
    try: secret=load_key().encode('utf-8')
    except RuntimeError: secret=None
    entries=[]
    for p in sorted(files):
        payload=p.read_bytes()
        if secret and secret in payload:raise RuntimeError('Credential detected in a package input; packaging stopped.')
        entries.append({'path':p.relative_to(ROOT).as_posix(),'bytes':len(payload),'sha256':hashlib.sha256(payload).hexdigest()})
    manifest={'packaged_at':NOW,'credential_scan':'passed','files':entries}
    manifest_path=target/'manifest.json';save(manifest_path,manifest)
    archive=target/args.output_name
    with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6,allowZip64=True) as z:
        for p in sorted(files):z.write(p,p.relative_to(ROOT).as_posix())
        z.write(manifest_path,'manifest.json')
    with zipfile.ZipFile(archive) as z:
        bad=z.testzip()
        if bad:raise RuntimeError('ZIP CRC failed: '+bad)
    print(json.dumps({'archive':str(archive),'bytes':archive.stat().st_size,'files':len(files)+1,'sha256':hashlib.sha256(archive.read_bytes()).hexdigest()},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
