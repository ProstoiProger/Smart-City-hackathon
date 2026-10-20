import unittest
from scripts.enrich_extended import parse_ticketon,decode_body

class ExtendedEventTests(unittest.TestCase):
    def source(self,event,url='https://ticketon.kz/concerts/event/example'):
        return {'url':url,'collected_at':'2026-10-19T10:00:00+00:00','text':'Возрастное ограничение\n6+','ld':[event]}
    def event(self,city='Астана'):
        return {'@type':'MusicEvent','name':'Концерт','startDate':'2026-10-21T19:00:00+05:00','endDate':'2026-10-21T20:00:00+05:00','location':{'name':'Зал','address':{'addressLocality':city}},'offers':{'price':'0','priceCurrency':'KZT'},'eventStatus':'https://schema.org/EventScheduled'}
    def test_foreign_city_is_not_imported(self):
        events,excluded=parse_ticketon(self.source(self.event('Алматы')),[])
        self.assertEqual(events,[]);self.assertEqual(excluded[0]['locality'],'Алматы')
    def test_occurrences_keep_own_locality_and_time(self):
        event=self.event();event['subEvent']=[self.event(),self.event('Алматы')]
        events,excluded=parse_ticketon(self.source(event),[])
        self.assertEqual(len(events),1);self.assertEqual(len(excluded),1)
        self.assertEqual(events[0]['event_price']['amount_min'],0)
        self.assertEqual(events[0]['event_status'],'EventScheduled')
        self.assertIsNone(events[0]['event_verified_at'])
    def test_missing_end_is_not_fabricated(self):
        event=self.event();event.pop('endDate')
        events,_=parse_ticketon(self.source(event),[])
        self.assertIsNone(events[0]['event_end'])
    def test_listing_range_is_not_a_continuous_performance(self):
        event=self.event();event['endDate']='2026-11-21T20:00:00+05:00'
        events,_=parse_ticketon(self.source(event),[])
        self.assertEqual(events[0]['date_precision'],'listing_range_not_continuous')
    def test_multicity_cinema_catalogue_excluded(self):
        events,excluded=parse_ticketon(self.source(self.event(),'https://ticketon.kz/cinema/event/film'),[])
        self.assertFalse(events);self.assertTrue(excluded)
    def test_misdeclared_latin1_header_can_be_recovered(self):
        self.assertEqual(decode_body('Астана'.encode('utf-8').decode('latin1')),'Астана')

if __name__=='__main__':unittest.main()
