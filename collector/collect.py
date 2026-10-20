"""One-command, reproducible Astana public-data pipeline."""
import argparse
import os
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parent

def main():
    parser=argparse.ArgumentParser(description='Collect Astana POI, infrastructure, events, weather and pedestrian routes.')
    parser.add_argument('--offline',action='store_true',help='Rebuild normalized outputs from cached source snapshots, without network requests.')
    parser.add_argument('--refresh',action='store_true',help='Refetch source snapshots, replacing only pipeline-generated cache files.')
    parser.add_argument('--with-2gis',action='store_true',help='Collect 2GIS category data using the local key before rebuilding exports')
    parser.add_argument('--2gis-max-requests',dest='dgis_max_requests',type=int,default=400,help='Maximum new 2GIS requests in this run')
    args=parser.parse_args()
    if args.offline and args.refresh:parser.error('--offline and --refresh cannot be combined')
    if args.offline and args.with_2gis:parser.error('--offline cannot send new 2GIS requests')
    if args.with_2gis:
        subprocess.run([sys.executable,'-m','scripts.collect_dgis','--strict-rubrics','--max-requests',str(args.dgis_max_requests)],cwd=ROOT,check=True)
    if args.refresh:os.environ['ASTANA_REFRESH']='1'
    if not args.offline:
        from scripts.download_sources import osm,tourism,BBOX,download,RAW
        jobs=[('pois',f'nwr[amenity~"^(cafe|restaurant|fast_food|food_court|bar|pub|ice_cream|biergarten|theatre|cinema|arts_centre|library|community_centre|coworking_space|planetarium|nightclub|social_centre|public_bath|place_of_worship)$"]({BBOX});nwr[tourism]({BBOX});nwr[leisure]({BBOX});nwr[shop~"^(mall|bakery|coffee|confectionery)$"]({BBOX});nwr[historic]({BBOX});'),('infrastructure',f'nwr[highway=bus_stop]({BBOX});nwr[public_transport]({BBOX});nwr[amenity~"^(toilets|shelter|bench|parking|drinking_water)$"]({BBOX});node[entrance]({BBOX});nwr[barrier]({BBOX});')]
        for job in jobs:
            result=osm(*job)
            if result.get('errors'):raise RuntimeError(result)
        tourism()
        from scripts.fetch_network import main as fetch_network
        fetch_network()
        # Weather is always refreshed; the rest of the sources use cache unless --refresh is passed.
        params={'latitude':51.1282,'longitude':71.4304,'current':'temperature_2m,apparent_temperature,precipitation,weather_code,wind_speed_10m','hourly':'temperature_2m,apparent_temperature,precipitation_probability,precipitation,wind_speed_10m','daily':'sunset,sunrise','timezone':'Asia/Almaty','forecast_days':7}
        previous=os.environ.get('ASTANA_REFRESH');os.environ['ASTANA_REFRESH']='1'
        download('https://api.open-meteo.com/v1/forecast',RAW/'weather.txt',params)
        if previous is None:os.environ.pop('ASTANA_REFRESH',None)
        else:os.environ['ASTANA_REFRESH']=previous
        subprocess.run([sys.executable,'-m','scripts.fetch_extra_sources'],cwd=ROOT,check=True)
    else:os.environ['ASTANA_OFFLINE']='1'
    for module in ['scripts.consolidate_dgis','scripts.build_dataset','scripts.enrich_primary','scripts.enrich_dataset','scripts.enrich_dgis','scripts.enrich_extended','scripts.derive_context','scripts.enrich_all_venues','scripts.build_routes','scripts.report_dataset','scripts.build_readiness_report']:
        print('Running',module,flush=True)
        subprocess.run([sys.executable,'-m',module],cwd=ROOT,check=True)

if __name__=='__main__':main()
