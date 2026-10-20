"""OSM pedestrian graph and nearby-POI routes; no straight-line routing fallback."""
import collections
import json
import math
from pathlib import Path
import sqlite3
import sys

import numpy as np
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import dijkstra, connected_components
from scipy.spatial import cKDTree
from scripts.build_dataset import RAW, OUT, load, save, jsonl, xy, distance, NOW

sys.stdout.reconfigure(encoding='utf-8')
EXCLUDE={'motorway','motorway_link','trunk','trunk_link','construction','proposed','raceway','bus_guideway','corridor'}

def main():
    path=RAW/'osm_network_geom.json'
    if not path.exists():raise RuntimeError('Download network first: python -m scripts.fetch_network')
    ways=load(path)['elements'];nodes={};edges={};way_rows=[];areas=[];closures=[];excluded=collections.Counter()
    forbidden=set()
    for e in load(RAW/'osm_infrastructure.json',{'elements':[]})['elements']:
        tags=e.get('tags',{})
        if e['type']=='node' and (tags.get('foot')=='no' or (tags.get('access') in ('no','private') and tags.get('foot') not in ('yes','designated','permissive'))):forbidden.add(e['id'])
    for way in ways:
        t=way.get('tags',{});h=t.get('highway');foot=t.get('foot');access=t.get('access')
        if h in ('construction','proposed'):
            closures.append({'osm_way_id':way['id'],'tags':t,'geometry':way.get('geometry'),'source_url':f'https://www.openstreetmap.org/way/{way["id"]}','realtime_verified':False})
        if h in EXCLUDE:excluded['excluded_highway_type']+=1;continue
        if foot in ('no','private','use_sidepath') or (access in ('no','private','customers','delivery','agricultural','forestry') and foot not in ('yes','designated','permissive')):
            excluded['access_restricted']+=1;continue
        coords=way.get('geometry',[]);ids=way.get('nodes',[])
        if len(coords)!=len(ids):excluded['geometry_mismatch']+=1;continue
        if h=='pedestrian' and t.get('area')=='yes':areas.append({'osm_way_id':way['id'],'geometry':coords,'tags':t,'source_url':f'https://www.openstreetmap.org/way/{way["id"]}'})
        attrs={'osm_way_id':way['id'],'highway':h,'foot':foot,'access':access,'wheelchair':t.get('wheelchair'),'surface':t.get('surface'),'smoothness':t.get('smoothness'),'incline':t.get('incline'),'lit':t.get('lit'),'sidewalk':t.get('sidewalk'),'conditional_access':t.get('access:conditional') or t.get('foot:conditional'),'opening_hours':t.get('opening_hours'),'source_url':f'https://www.openstreetmap.org/way/{way["id"]}'}
        way_rows.append(attrs|{'nodes':ids})
        for a,b,ca,cb in zip(ids,ids[1:],coords,coords[1:]):
            if a in forbidden or b in forbidden:continue
            if not ca or not cb:continue
            if ca.get('lat') is None or cb.get('lat') is None:continue
            nodes[a]=(ca['lat'],ca['lon']);nodes[b]=(cb['lat'],cb['lon'])
            length=distance(nodes[a],nodes[b])
            if a==b or length<.01:continue
            one=t.get('oneway:foot')
            directions=[(a,b)] if one=='yes' else ([(b,a)] if one=='-1' else [(a,b),(b,a)])
            for u,v in directions:
                key=(u,v)
                edge={'from_node':u,'to_node':v,'length_m':round(length,3),**attrs}
                if key not in edges or edges[key]['length_m']>length:edges[key]=edge
    nodeids=list(nodes);index={n:i for i,n in enumerate(nodeids)}
    row=np.array([index[u] for u,v in edges],dtype=np.int32);col=np.array([index[v] for u,v in edges],dtype=np.int32)
    graph=csr_matrix((np.array([x['length_m'] for x in edges.values()]),(row,col)),shape=(len(nodeids),len(nodeids)))
    components,labels=connected_components(graph,directed=True,connection='weak')
    counts=collections.Counter(labels.tolist())
    tree=cKDTree([xy(*nodes[n]) for n in nodeids])
    pois=[json.loads(x) for x in (OUT/'pois.jsonl').read_text(encoding='utf-8').splitlines()]
    connections=[]
    for p in pois:
        dd,idx=tree.query(xy(p['latitude'],p['longitude']))
        n=nodeids[int(idx)];snap=distance((p['latitude'],p['longitude']),nodes[n])
        connections.append({'poi_id':p['poi_id'],'node_id':n,'snap_distance_m':round(snap,2),'snap_connector_verified':False,'usable_for_candidate_routes':snap<=80,'component_id':int(labels[int(idx)])})
    poi_tree=cKDTree([xy(p['latitude'],p['longitude']) for p in pois]);routes=[]
    for i,p in enumerate(pois):
        c=connections[i]
        if not c['usable_for_candidate_routes']:continue
        _,neighbors=poi_tree.query(xy(p['latitude'],p['longitude']),k=min(9,len(pois)),distance_upper_bound=2000)
        targets=[int(j) for j in np.atleast_1d(neighbors) if j<len(pois) and j!=i and connections[int(j)]['usable_for_candidate_routes'] and connections[int(j)]['component_id']==c['component_id']]
        if not targets:continue
        dist,pred=dijkstra(graph,directed=True,indices=index[c['node_id']],limit=5000,return_predecessors=True)
        for j in targets:
            other=connections[j];target=index[other['node_id']];d=float(dist[target])
            if not math.isfinite(d):continue
            path_indices=[target];cur=target;source=index[c['node_id']]
            while cur!=source and cur!=-9999:
                cur=int(pred[cur])
                if cur!=-9999:path_indices.append(cur)
            if cur==-9999:continue
            path_nodes=[nodeids[k] for k in reversed(path_indices)]
            path_edges=[edges[u,v] for u,v in zip(path_nodes,path_nodes[1:])]
            duration=sum(e['length_m']/(.65 if e['highway']=='steps' else 1.25) for e in path_edges)/60
            routes.append({'route_id':f'{p["poi_id"]}__{pois[j]["poi_id"]}','from_poi_id':p['poi_id'],'to_poi_id':pois[j]['poi_id'],'walking_distance_m':round(d,1),'walking_duration_min':round(duration,1),'distance_scope':'OSM_graph_nodes_only','origin_snap_distance_m':c['snap_distance_m'],'destination_snap_distance_m':other['snap_distance_m'],'snap_connectors_verified':False,'door_to_door_verified':False,'accessible_routes':None,'contains_steps':any(e['highway']=='steps' for e in path_edges),'has_conditional_access':any(e['conditional_access'] or e['opening_hours'] for e in path_edges),'path_node_ids':path_nodes,'derived_value':True,'method':'Dijkstra_on_OSM_foot_permitted_graph','speed_assumption_m_s':{'default':1.25,'steps':.65},'source_name':'OpenStreetMap','source_url':'https://www.openstreetmap.org/copyright','license':'ODbL-1.0','collected_at':NOW})
        if i%500==0:print(f'Routes: processed {i}/{len(pois)}, {len(routes)} connections',flush=True)
    jsonl(OUT/'pedestrian_nodes.jsonl',[{'node_id':n,'latitude':v[0],'longitude':v[1]} for n,v in nodes.items()])
    jsonl(OUT/'pedestrian_edges.jsonl',edges.values());jsonl(OUT/'pedestrian_ways.jsonl',way_rows)
    jsonl(OUT/'poi_route_connectivity.jsonl',connections);jsonl(OUT/'walking_routes.jsonl',routes)
    jsonl(OUT/'pedestrian_areas.jsonl',areas);jsonl(OUT/'path_closures.jsonl',closures)
    summary={'created_at':NOW,'raw_highway_ways':len(ways),'foot_permitted_ways':len(way_rows),'graph_nodes':len(nodes),'directed_edges':len(edges),'weak_components':int(components),'largest_component_nodes':counts.most_common(1)[0][1] if counts else 0,'poi_with_snap_within_80m':sum(x['usable_for_candidate_routes'] for x in connections),'candidate_routes':len(routes),'pedestrian_areas':len(areas),'mapped_path_closures_or_construction':len(closures),'exclusions':dict(excluded),'limitations':['Network distances are calculated on OSM geometry, not straight lines.','POI-to-network snaps are unverified straight-line associations, excluded from reported walking distance. Routes are candidates, not verified door-to-door directions.','Missing paths and crossings cause disconnected components. No artificial joins are added.','Construction and access tags reflect map observations, not live closure reports. Conditional restrictions are flagged but not evaluated by time.','Wheelchair accessibility is unknown unless independently verified; steps and restricted access are excluded only from their applicable profiles.','Vehicle oneway is ignored for pedestrians; explicit oneway:foot is respected. Turn restriction relations and indoor passage routing are not supported.']}
    save(OUT/'routing_summary.json',summary)
    db=sqlite3.connect(OUT/'smart_city.sqlite')
    db.executescript('DROP TABLE IF EXISTS walking_routes; CREATE TABLE walking_routes(route_id TEXT PRIMARY KEY,from_poi_id TEXT,to_poi_id TEXT,walking_distance_m REAL,walking_duration_min REAL,payload_json TEXT);CREATE INDEX route_origin ON walking_routes(from_poi_id);')
    db.executemany('INSERT INTO walking_routes VALUES(?,?,?,?,?,?)',[(r['route_id'],r['from_poi_id'],r['to_poi_id'],r['walking_distance_m'],r['walking_duration_min'],json.dumps(r,ensure_ascii=False)) for r in routes]);db.commit();db.close()
    print(json.dumps(summary,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
