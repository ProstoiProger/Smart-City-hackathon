"""Live 2GIS lookup for demo use. Does not cache or persist provider records."""
from datetime import datetime, timezone
import math
from scripts.dgis_client import DgisClient

FIELDS = 'items.point,items.rubrics,items.schedule,items.schedule_special,items.reviews,items.attribute_groups,items.dates'

def _result(data):
    places = []
    for item in data.get('result', {}).get('items', []):
        reviews = item.get('reviews') or {}
        rating = reviews.get('general_rating') if reviews.get('general_rating') is not None else reviews.get('rating')
        point = item.get('point') or {}
        places.append({
            'external_id': item.get('id'), 'name': item.get('name'),
            'address': item.get('address_name'), 'latitude': point.get('lat'),
            'longitude': point.get('lon'), 'categories': item.get('rubrics'),
            'opening_hours': item.get('schedule'), 'holiday_hours': item.get('schedule_special'),
            'rating': rating if rating != 0 else None,
            'ratings_count': reviews.get('general_review_count_with_stars'),
            'reviews_count': reviews.get('general_review_count') if reviews.get('general_review_count') is not None else reviews.get('review_count'),
            'attributes': item.get('attribute_groups'), 'source_updated_at': (item.get('dates') or {}).get('updated_at'),
            'source_url': 'https://2gis.kz/astana/firm/' + str(item['id']).split('_')[0] if item.get('type') == 'branch' and item.get('id') else None,
            'operational_status': None, 'open_now': None,
        })
    return {'source': '2ГИС', 'attribution_url': 'https://dev.2gis.ru/',
            'retrieved_at': datetime.now(timezone.utc).isoformat(), 'storage_mode': 'live_only_no_cache',
            'places': places, 'note': 'Online provider data, separate from the downloadable OSM-based dataset. No persistent storage is performed.'}

def search_live(query, latitude, longitude, limit=3, radius_m=2000, client=None):
    if not str(query or '').strip():
        raise ValueError('A search phrase is required.')
    if not math.isfinite(latitude) or not math.isfinite(longitude) or not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        raise ValueError('Invalid latitude or longitude.')
    if not 1 <= limit <= 10:
        raise ValueError('Live demo limit must be between 1 and 10 places.')
    if not 1 <= radius_m <= 10000:
        raise ValueError('Radius must be between 1 and 10000 metres.')
    api = client or DgisClient(max_requests=1)
    data = api.request('items', q=query, location=f'{longitude},{latitude}', radius=radius_m,
                       type='branch', locale='ru_KZ', page_size=limit, fields=FIELDS)
    return _result(data)

def details_live(external_id, client=None):
    if not str(external_id or '').strip():
        raise ValueError('2GIS object ID is required.')
    api = client or DgisClient(max_requests=1)
    return _result(api.request('items/byid', id=external_id, locale='ru_KZ', fields=FIELDS))
