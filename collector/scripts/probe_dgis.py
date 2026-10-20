"""Small access test; saves field availability only, not provider place records."""
from datetime import datetime, timezone
import json
from scripts.dgis_client import DgisClient, DgisError, ROOT

def main():
    client = DgisClient(max_requests=3)
    report = {'checked_at': datetime.now(timezone.utc).isoformat(), 'credential_present': True,
              'key_type': 'demo_user_reported', 'request_cap': 3, 'tests': [],
              'provider_records_persisted': False, 'credential_logged': False}
    fields = 'items.point,items.rubrics,items.schedule,items.schedule_special,items.reviews,items.attribute_groups,items.dates'
    try:
        data = client.request('items', q='MEGA Silk Way', location='71.407,51.089', radius=3000,
                              type='branch', locale='ru_KZ', page_size=1, fields=fields)
        items = data.get('result', {}).get('items', [])
        available = sorted(set().union(*(x.keys() for x in items))) if items else []
        rating_available = any(any(k in x.get('reviews', {}) for k in ('general_rating', 'rating')) for x in items)
        report['tests'].append({'method': 'items', 'success': True, 'returned_items': len(items),
                                'available_field_names': available, 'rating_field_present': rating_available,
                                'schedule_field_present': any('schedule' in x for x in items),
                                'attributes_field_present': any('attribute_groups' in x for x in items)})
        if items:
            detail = client.request('items/byid', id=items[0]['id'], locale='ru_KZ', fields=fields)
            detail_items = detail.get('result', {}).get('items', [])
            report['tests'].append({'method': 'items/byid', 'success': True,
                                     'returned_items': len(detail_items),
                                     'available_field_names': sorted(set().union(*(x.keys() for x in detail_items))) if detail_items else []})
    except DgisError as exc:
        report['tests'].append({'success': False, 'error': str(exc)})
    report['requests_made'] = client.requests_made
    path = ROOT / 'data/processed/dgis_access_check.json'
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()
