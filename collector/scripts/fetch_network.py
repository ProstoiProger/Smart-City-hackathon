from scripts.download_sources import download, RAW
import json
query = '[out:json][timeout:120];way[highway][highway!~"^(motorway|motorway_link|trunk|trunk_link)$"](50.98,71.18,51.34,71.75);out meta geom;'
def main():
    text=download('https://overpass-api.de/api/interpreter', RAW/'osm_network_geom.json', {'data':query}, 150)
    data=json.loads(text)
    if data.get('remark'): raise RuntimeError(data['remark'])
    print('Network ways:',len(data['elements']))

if __name__ == '__main__':main()
