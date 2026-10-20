"""Refresh exports, checklist coverage, licenses and validation evidence."""
from pathlib import Path
import collections
import json
import math
import random
import sqlite3
import zipfile
from scripts.build_dataset import ROOT,OUT,RAW,NOW,load,save,jsonl,SCHEMA,POI_FIELDS

def read_rows(name):
    path=OUT/name
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()] if path.exists() else []

def main():
    pois=read_rows('pois.jsonl');infra=read_rows('infrastructure.jsonl');events=read_rows('events.jsonl');routes=read_rows('walking_routes.jsonl');facts=read_rows('facts.jsonl')
    summary=load(OUT/'summary.json',{});routing=load(OUT/'routing_summary.json',{});wx=load(OUT/'weather_snapshot.json',{})
    conflicts=load(OUT/'source_conflicts.json',[])+load(OUT/'primary_source_updates.json',[])+load(OUT/'dgis_source_conflicts.json',[])+load(OUT/'extended_source_conflicts.json',[])+load(OUT/'all_venue_source_conflicts.json',[])
    conflict_keys={(x['poi_id'],x['field_name']) for x in conflicts}
    for f in facts:
        if (f['poi_id'],f['field_name']) in conflict_keys:f['source_conflict']=True
    jsonl(OUT/'facts.jsonl',facts)
    summary.update({'finalized_at':NOW,'poi_count':len(pois),'named_poi_count':sum(bool(p.get('name')) for p in pois),'source_description_count':sum(p.get('description_type')=='source_text' for p in pois),'template_description_count':sum(p.get('description_type')=='derived_template' for p in pois),'events_count':len(events),'facts_count':len(facts),'source_conflicts_count':len(conflicts),'field_coverage':{field:sum(p.get(field) is not None for p in pois) for field in POI_FIELDS},'weekly_schedules_parsed':sum(p.get('opening_hours_by_day') is not None for p in pois),'poi_with_licensed_photo_metadata':sum(bool(p.get('photos')) for p in pois),'candidate_walking_routes':len(routes)})
    save(OUT/'summary.json',summary)
    summary['category_counts']=dict(collections.Counter(p['category'] for p in pois))
    summary['dgis']=load(OUT/'dgis_enrichment_summary.json',{})
    save(OUT/'summary.json',summary)
    jsonl(OUT/'detailed_pois.jsonl',[p for p in pois if p.get('description_type')=='source_text' and len(p.get('short_description') or '')>=100 and p['category'] not in ('infrastructure','accommodation')])
    columns=POI_FIELDS+['name','display_name','description_type','opening_hours_by_day','sources','derived_fields','nearby_transit_stops','entrances_exits','reservation_available','quiet_place_scope','power_outlets_scope','amenity_evidence_scope','source_hours_checked_at','website_description','website_contact_phones','seating_area_types','outdoor_seating','indoor_outdoor_scope','wheelchair_accessibility_scope']
    columns+=['pricing','visit_rules','closure_assessment','venue_enrichment_audit']
    jsonl(OUT/'rag_documents.jsonl',[{'id':p['poi_id'],'text':'\n'.join(filter(None,[p['display_name'],p['short_description'],p['address'],'Категория: '+p['category'],'Теги: '+', '.join(p['tags'] or [])])), 'metadata':{k:p.get(k) for k in ('poi_id','latitude','longitude','category','source_url','last_updated_at','description_type')},'structured_facts':{k:p.get(k) for k in columns}} for p in pois])
    save(OUT/'pois.geojson',{'type':'FeatureCollection','features':[{'type':'Feature','geometry':{'type':'Point','coordinates':[p['longitude'],p['latitude']]},'properties':{k:p.get(k) for k in ('poi_id','display_name','category','subcategory','source_url','short_description','description_type','opening_hours','photos')}} for p in pois]})
    # Copy all non-private records into a compact, analytics-friendly columnar export.
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
        pq.write_table(pa.Table.from_pylist([{k:p.get(k) for k in ('poi_id','display_name','name_ru','name_kk','name_en','latitude','longitude','category','subcategory','address','short_description','description_type','opening_hours','website','phone','source_url','last_updated_at','rating','ratings_count','rating_source','wifi_available','laptop_friendly','power_outlets','quiet_place','wheelchair_accessible','ramps','elevators','restrooms','pet_friendly','operational_status')}|{k+'_json':json.dumps(p.get(k),ensure_ascii=False) for k in ('pricing','visit_rules','closure_assessment','venue_enrichment_audit')} for p in pois]),OUT/'pois.parquet',compression='zstd')
    except ImportError:pass
    domain_counts=collections.Counter()
    from urllib.parse import urlparse
    for f in facts:domain_counts[urlparse(f['source_url']).netloc]+=1
    source_registry=[
        {'source':'OpenStreetMap','url':'https://www.openstreetmap.org/copyright','status':'collected','license':'ODbL-1.0','scope':'POIs, mapped amenities, transit stops, barriers and pedestrian graph','attribution':'© OpenStreetMap contributors','note':'Attribution and ODbL obligations apply. OSM tags are map observations, not independent live verification.'},
        {'source':'Visit Astana','url':'https://visitastana.kz/ru/','status':'partially_collected_with_quarantine','license':None,'scope':'Tourism directory descriptions, restaurants, schedules, contacts, average checks and event listings','note':'No general reuse license established. Text kept with attribution for research. Do not treat these texts as ODbL or assume photos are licensed. Some pages contain unrelated spam and are quarantined.'},
        {'source':'National Museum of Kazakhstan','url':'https://nmrk.kz/ru/','status':'collected','license':None,'scope':'Hours, accessibility, visit rules, conditional discounts and one dated exhibition','note':'Published self-reports, retrieved at collection time. No independent on-site verification or general text reuse license.'},
        {'source':'Kazakhstan.travel','url':'https://kazakhstan.travel/ru/attractions/423','status':'collected','license':None,'scope':'Bayterek published adult, child and concession prices','note':'Price validity dates are not published. Coordinates from this page disagree with OSM and were not adopted.'},
        {'source':'Wikimedia Commons','url':'https://commons.wikimedia.org/','status':'collected','license':'per_image','scope':'Photo URLs, authors, credit and explicit license metadata','note':'Metadata only, no images downloaded. Category membership does not independently verify the depicted subject. Follow each image license.'},
        {'source':'Open-Meteo','url':'https://open-meteo.com/en/docs','status':'collected','license':'CC-BY-4.0','scope':'Current weather, apparent temperature, wind, precipitation forecast and sunset','attribution':'Weather data by Open-Meteo.com','note':'Refresh at query time; this is a timestamped snapshot. No official severe-weather alert feed.'},
        {'source':'data.egov.kz','url':'https://data.egov.kz/pages/samples','status':'catalogue_metadata_only','license':None,'scope':'Two archived Astana park datasets identified','note':'Archived entries are not used as current POI facts. Developer API key is required for API records; no key was available in this session.'},
        {'source':'2GIS Places API','url':'https://docs.2gis.com/en/api/search/places/overview','status':'not_collected_no_api_key','license':None,'scope':'Potential ratings, reviews, hours and business status','note':'No API key available. Storage terms must be checked before enabling a persistent-data integration.'},
        {'source':'Google Places API','url':'https://developers.google.com/maps/documentation/places/web-service/reference/rest/v1/places','status':'not_collected_no_api_key','license':None,'scope':'Potential rating and business-status verification','note':'No API key available. Do not treat API content as a freely redistributable permanent database.'},
    ]
    dgis_check=load(OUT/'dgis_access_check.json',{})
    dgis_enrichment=load(OUT/'dgis_enrichment_summary.json',{})
    dgis_collection=load(OUT/'dgis_collection_report.json',{})
    if any(test.get('success') for test in dgis_check.get('tests',[])):
        for source in source_registry:
            if source['source']=='2GIS Places API':
                source.update({'status':'live_demo_access_verified_no_persistence','scope':'Live ratings, schedules and organization attributes; search and by-ID access tested','note':'Demo access verified with two test requests. Provider place records are not cached, merged into SQLite, or included in downloadable data. Standard directory API offer section 3.1 restricts extraction/storage; a separate data-export permission would be needed for persistent enrichment.','terms_url':'https://law.2gis.ru/webapi-offer','access_checked_at':dgis_check.get('checked_at'),'requests_in_access_check':dgis_check.get('requests_made')})
    if dgis_enrichment.get('provider_records'):
        for source in source_registry:
            if source['source']=='2GIS Places API':source.update({'status':'collected_and_merged','license':'2GIS proprietary','scope':'Saved provider records, ratings/counts, schedules, explicit amenity attributes, entrances and nearby stations','note':'Collected at the user\'s explicit request. Data remains proprietary and is not relicensed as ODbL. Search coverage and outstanding tasks are recorded in dgis_collection_report.json.','records':dgis_enrichment['provider_records'],'collection_complete':dgis_collection.get('complete',False)})
    if (OUT/'extended_enrichment_summary.json').exists():
        source_registry.extend([
          {'source':'2GIS Routing API','url':'https://docs.2gis.com/api/navigation/routing/start','status':'sampled_public_transport_routes','license':'2GIS proprietary','scope':'Route variants, walking and waiting legs between fixed public demo landmarks','note':'Snapshots, not a complete city bus timetable or guaranteed arrival time. See transit_summary.json and dgis_transit_access.json.'},
          {'source':'Kazhydromet','url':'https://www.kazhydromet.kz/ru/storm','status':'collected_official_warning_snapshot','license':None,'scope':'Published Astana warnings, region filter 20 confirmed by response','note':'Refresh at request time and read the published validity interval. Retrieval does not independently verify current hazards.'},
          {'source':'Wikidata','url':'https://www.wikidata.org/','status':'collected_by_explicit_osm_identity_links','license':'CC0-1.0','scope':'Labels, brief entity descriptions and P18 image links','note':'Wikidata facts are linked by explicit OSM wikidata identifiers; image files retain their individual Commons licenses.'},
          {'source':'Freedom Ticketon','url':'https://ticketon.kz/astana','status':'collected_structured_event_listings','license':None,'scope':'Dated Astana occurrences, starting prices, age restrictions and publisher status','note':'Foreign-city events and multi-city cinema catalogues excluded. Publisher status is not independent confirmation with an organiser.'},
          {'source':'Venue websites','url':'https://alem.ai/','status':'collected_finite_explicit_pages','license':None,'scope':'Official venue prices, rules, descriptions, contacts and closure notices; exact URLs in facts.jsonl','note':'Includes Ailand, alem.ai, Astana botanical greenhouses, selected cafes and coworkings. Scope limits and subjective testimonials are retained per fact.'},
          {'source':'Astana News','url':'https://astanews.kz/','status':'collected_two_editorial_branch_listings','license':None,'scope':'Outlets, Wi-Fi and laptop use at Barista Coffee on Koshkarbaev 8 and Tary on Akmeshit','note':'Editorial source claims, not independent inspection or venue guarantees. Exact branch IDs, evidence and scope recorded in facts.jsonl.'},
        ])
    save(OUT/'source_registry.json',source_registry)
    facts_fields={x['field'] for x in SCHEMA if x['section'].startswith('9.')}
    mapping={
      'pedestrian_network':('pedestrian_edges.jsonl',routing.get('directed_edges',0)),
      'entrances_exits':('infrastructure.jsonl',sum('entrance_exit' in x['kinds'] for x in infra)),
      'walking_distance_m':('walking_routes.jsonl',len(routes)),
      'walking_duration_min':('walking_routes.jsonl',len(routes)),
      'transit_duration_min':('transit_routes.jsonl',sum(r.get('transit_duration_min') is not None for r in read_rows('transit_routes.jsonl'))),
      'nearby_transit_stops':('pois.jsonl',sum(bool(x.get('nearby_transit_stops')) for x in pois)),
      'pedestrian_areas':('pedestrian_areas.jsonl',routing.get('pedestrian_areas',0)),
      'path_closures':('path_closures.jsonl',routing.get('mapped_path_closures_or_construction',0)),
      'poi_route_connectivity':('poi_route_connectivity.jsonl',routing.get('poi_with_snap_within_80m',0)),
    }
    reasons={'rating':'Нет доступного лицензированного источника оценок без API-ключа.','ratings_count':'Нет доступного источника оценок.','rating_source':'Рейтинги не загружены.','power_outlets':'В собранных источниках нет явных подтверждений наличия розеток.','quiet_place':'Нет подтверждённых сведений о тишине.','laptop_friendly':'Нет подтверждённых правил использования ноутбуков.','transit_duration_min':'Нет подключённого расписания/GTFS и транспортного маршрутизатора.','accessible_routes':'Тегов недостаточно для подтверждения безбарьерного маршрута целиком.','weather_alerts':'Выбранный погодный API не предоставляет официальные предупреждения.','hours_verified_at':'Независимая проверка расписаний не выполнена; есть время получения исходных сведений.','event_verified_at':'Есть дата загрузки афиши, но отмена и перенос не подтверждены независимо.','operational_status':'Наличие записи в каталоге не подтверждает текущий статус работы.','photos':'Есть метаданные лицензии; изображённый объект требует проверки перед показом.'}
    if dgis_enrichment.get('provider_records'):
        for field in ('rating','ratings_count','rating_source','laptop_friendly'):reasons[field]='Сохранено из ответа/явного атрибута 2GIS, если поле присутствовало. Отсутствие значения не превращается в false.'
    if (OUT/'extended_enrichment_summary.json').exists():
        reasons.update({'power_outlets':'Публикации редакционного каталога для двух конкретных филиалов; не независимая проверка на месте. См. power_outlets_scope.','quiet_place':'Есть отдельное субъективное свидетельство клиента; это не измерение шума и не гарантия тишины. См. quiet_place_scope и facts.jsonl.','transit_duration_min':'Варианты поездок между фиксированными публичными точками; снимок расчёта 2GIS с ходьбой и ожиданием, не полное расписание города.','weather_alerts':'Официальный снимок предупреждений Казгидромета по Астане; проверять срок действия и обновлять при запросе.','reservation_required':'Возможность забронировать столик сохранена отдельно в reservation_available и не означает обязательное бронирование.'})
    coverage=[]
    for x in SCHEMA:
        f=x['field'];sec=x['section'];denom=None
        if sec.startswith(('1.','2.','3.','4.','5.')):artifact='pois.jsonl';n=sum(p.get(f) is not None for p in pois);denom=len(pois)
        elif sec.startswith('6.'):
            artifact,n=mapping.get(f,('walking_routes.jsonl',0))
        elif sec.startswith('7.'):artifact='events.jsonl';n=sum(e.get(f) is not None for e in events);denom=len(events)
        elif sec.startswith('8.'):artifact='weather_snapshot.json';n=int(wx.get(f) is not None)
        elif sec.startswith('9.'):artifact='facts.jsonl';n=sum(p.get(f) is not None for p in facts);denom=len(facts)
        else:continue
        coverage.append(x|{'artifact':artifact,'known_count':n,'total_count':denom,'coverage_percent':round(n/denom*100,2) if denom else None,'status':'unavailable' if not n else ('available' if denom is None or n==denom else 'partial'),'note':reasons.get(f,'null сохраняет неизвестность; наличие значения не означает независимую проверку.')})
    save(OUT/'checklist_coverage.json',coverage)
    lines=['# Покрытие чек-листа Smart City Astana','',f'Сбор: {NOW}. Все {len(coverage)} полей из разделов 1–9 учтены в схеме и этом отчёте.','',f'В базе {len(pois):,} POI, в том числе {summary["named_poi_count"]:,} с названием источника. Координаты — в прямоугольнике городской территории, включая аэропорт; это не перепись всех объектов административной Астаны.','',f'Описания источников: {summary["source_description_count"]}. Шаблонные описания по категории: {summary["template_description_count"]}, помечены `derived_template`. Подтверждённый на месте статус работы не заявляется.','',f'Инфраструктура: {len(infra):,} записей; события: {len(events)}; маршруты по графу OSM: {len(routes):,}.','', 'Расстояния маршрутов относятся к узлам графа. Привязка POI к графу и соединение с фактическим входом не проверены; это кандидаты маршрутов, а не проверенная навигация от двери до двери.','', '## Поля','', '| Раздел | Поле | Приоритет | Известно | Покрытие | Файл |','|---|---|---|---:|---:|---|']
    for c in coverage:lines.append(f'| {c["section"].split(". ",1)[0]} | `{c["field"]}` | {c["priority"] or "—"} | {c["known_count"]} | {str(c["coverage_percent"])+"%" if c["coverage_percent"] is not None else "—"} | {c["artifact"]} |')
    dgis_note='Демодоступ 2GIS проверен двумя запросами: доступны рейтинги, расписания и атрибуты. Эти сведения запрашиваются онлайн через `query.py --2gis`; ответы провайдера не сохраняются в постоянную базу. Стандартная оферта справочного API, п. 3.1, ограничивает извлечение и хранение. Для постоянного обогащения требуется отдельное разрешение на выгрузку.' if dgis_check.get('requests_made') else 'Ключ 2GIS не подключён.'
    if dgis_enrichment.get('provider_records'):dgis_note=f'2GIS: сохранено {dgis_enrichment["provider_records"]} уникальных карточек; сопоставлено с существующими POI {dgis_enrichment["matched_existing_pois"]}, добавлено {dgis_enrichment["added_pois"]}. Рейтинги, расписания и явно указанные атрибуты включены в постоянный датасет. Статус полноты поиска: {dgis_collection.get("complete",False)}; незавершённых поисковых областей: {len(dgis_collection.get("pending_tasks",[]))}. Причины и все ответы сохранены.'
    lines+=['','## Дополнение 2GIS и недоступные сведения','', dgis_note+' Ключ Google Places не подключён. Тексты отзывов через API 2GIS, подтверждённые розетки, измеренный уровень шума, полное транспортное расписание и проверенные безбарьерные маршруты отсутствуют. Отдельные субъективные свидетельства клиентов помечены как мнения. Транспортные расчёты для демонстрационных точек, официальные предупреждения Казгидромета, новые цены и правила находятся в дополнительных файлах; см. ENRICHMENT_REPORT.md. Неизвестные значения оставлены `null`.','', 'Часы работы сохранены в исходном виде; простые выражения дополнительно разобраны по дням. Неизвестный режим не означает «открыто». Последний вторник месяца для Национального музея сохранён как отдельное исключение; при оценке режима необходимо учитывать все исключения.','', '## Источники и ограничения','']
    for s in source_registry:lines.append(f'- [{s["source"]}]({s["url"]}): {s["status"]}. {s["note"]}')
    lines+=['','## Качество','',f'Удалено точных пространственных дублей OSM: {summary["duplicates_removed"]}. Сопоставлений официальных страниц с POI: {summary["official_matched"]}. Сопоставление автоматическое, не является ручной проверкой.',f'Противоречий/различий представления: {len(conflicts)}. См. `source_conflicts.json` и `primary_source_updates.json`. Сомнительных страниц: {summary["quarantined_sources_count"]}; причины сохранены в `rejected_sources.json`.','', 'Оценки `confidence_score` — эвристические уровни доказательств (0.50 / 0.70 / 0.80), а не измеренные вероятности достоверности. `verified_at` остаётся null при отсутствии независимой проверки. Исходное время изменения OSM сохранено отдельно от времени загрузки.','']
    (ROOT/'DATA_REPORT.md').write_text('\n'.join(lines),encoding='utf-8')
    # Validate actual exports and route lengths against the stored graph.
    ids={p['poi_id'] for p in pois};extra_ids={p['poi_id'] for p in read_rows('official_unlocated.jsonl')}
    checks={}
    checks['unique_poi_ids']=len(ids)==len(pois)
    checks['all_coordinates_in_study_area']=all(50.98<=p['latitude']<=51.34 and 71.18<=p['longitude']<=71.75 for p in pois)
    checks['all_poi_have_source_and_timestamp']=all(p.get('source_url') and p.get('last_updated_at') for p in pois)
    checks['all_checklist_poi_fields_present']=all(all(k in p for k in POI_FIELDS) for p in pois)
    checks['all_fact_foreign_keys_resolve']=all(f['poi_id'] in ids|extra_ids for f in facts)
    checks['all_route_foreign_keys_resolve']=all(r['from_poi_id'] in ids and r['to_poi_id'] in ids for r in routes)
    checks['unknown_hours_never_assumed_24_7']=all(p['is_24_7'] is None for p in pois if p.get('opening_hours') is None)
    checks['ratings_have_source_and_valid_range']=all(p['rating'] is None or (p.get('rating_source') and 1<=p['rating']<=5) for p in pois)
    checks['all_photos_have_license_metadata']=all(ph.get('license') and ph.get('source_url') for p in pois for ph in p.get('photos') or [])
    checks['events_have_ordered_dates']=all(e.get('event_start') and (e.get('event_end') is None or e['event_start']<=e['event_end']) for e in events)
    edges={(e['from_node'],e['to_node']):e for e in read_rows('pedestrian_edges.jsonl')}
    samples=random.Random(42).sample(routes,min(250,len(routes)))
    checks['sampled_routes_follow_real_graph_edges']=all(all((u,v) in edges for u,v in zip(r['path_node_ids'],r['path_node_ids'][1:])) for r in samples)
    checks['sampled_route_lengths_equal_edge_sums']=all(abs(sum(edges[u,v]['length_m'] for u,v in zip(r['path_node_ids'],r['path_node_ids'][1:]))-r['walking_distance_m'])<.11 for r in samples)
    checks['no_prohibited_access_in_graph']=all(e.get('foot') not in ('no','private','use_sidepath') and (e.get('access') not in ('no','private','customers','delivery','agricultural','forestry') or e.get('foot') in ('yes','designated','permissive')) for e in edges.values())
    db=sqlite3.connect(OUT/'smart_city.sqlite');db.execute('DELETE FROM facts')
    db.executemany('INSERT INTO facts VALUES(?,?,?,?)',[(f['poi_id'],f['field_name'],f['source_name'],json.dumps(f,ensure_ascii=False)) for f in facts]);db.commit()
    checks['sqlite_integrity']=db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    checks['sqlite_poi_count_matches']=db.execute('SELECT count(*) FROM pois').fetchone()[0]==len(pois)
    checks['sqlite_route_count_matches']=db.execute('SELECT count(*) FROM walking_routes').fetchone()[0]==len(routes)
    checks['fts_search_returns_cafe']=db.execute('SELECT count(*) FROM poi_search WHERE poi_search MATCH ?',('cafe',)).fetchone()[0]>0
    db.close()
    validation={'validated_at':NOW,'checks':checks,'sampled_routes':len(samples),'all_passed':all(checks.values())}
    save(OUT/'validation_report.json',validation)
    if not validation['all_passed']:raise AssertionError(json.dumps(validation,ensure_ascii=False))
    print(json.dumps({'poi_count':len(pois),'events':len(events),'source_descriptions':summary['source_description_count'],'field_rows':len(coverage),'checks_passed':len(checks),'routes':len(routes)},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
