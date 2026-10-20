import unittest
from scripts.enrich_dgis import normalize,classify,schedule_fields

def record(**fields):
    return {'dgis_id':'123','data':{'name':'Test','point':{'lat':51.1,'lon':71.4},'rubrics':[{'name':'Кафе','kind':'primary'}],**fields},'matched_queries':['Кафе'],'collected_at':'2026-10-19T00:00:00+00:00','source_url':'https://2gis.kz/astana/firm/123'}

class NormalizationTests(unittest.TestCase):
    def test_unknown_amenities_remain_null(self):
        row=normalize(record())
        for field in ['wifi_available','power_outlets','quiet_place','laptop_friendly','wheelchair_accessible','rating']:
            self.assertIsNone(row[field])

    def test_explicit_attributes_and_rating_counts(self):
        row=normalize(record(attribute_groups=[{'attributes':[{'tag':'food_service_cafe_working','name':'Можно с ноутбуком'},{'tag':'additionally_services_freewifi','name':'Бесплатный Wi-Fi'}]}],reviews={'general_rating':4.7,'general_review_count':12,'general_review_count_with_stars':30}))
        self.assertTrue(row['wifi_available']);self.assertTrue(row['laptop_friendly'])
        self.assertEqual(row['ratings_count'],30);self.assertEqual(row['reviews_count'],12)
        self.assertIsNone(row['power_outlets'])

    def test_gravestone_retail_is_not_a_sight(self):
        self.assertEqual(classify({'rubrics':[{'name':'Памятники и надгробия','kind':'primary'}]})[0],'other')
        self.assertEqual(classify({'rubrics':[{'name':'Памятники и скульптуры','kind':'primary'}]})[0],'sightseeing')

    def test_partial_schedule_does_not_invent_missing_days(self):
        raw,weekly,is24=schedule_fields({'Mon':{'working_hours':[{'from':'09:00','to':'18:00'}]}})
        self.assertEqual(weekly['Mo'],[['09:00','18:00']]);self.assertIsNone(weekly['Su'])
        self.assertFalse(is24);self.assertEqual(raw,'Mo 09:00-18:00')

    def test_zero_provider_rating_is_not_a_zero_star_recommendation(self):
        row=normalize(record(reviews={'general_rating':0,'general_review_count_with_stars':8}))
        self.assertIsNone(row['rating']);self.assertIsNone(row['rating_source'])
        self.assertEqual(row['raw_2gis_reviews']['general_rating'],0)
        self.assertEqual(row['ratings_count'],8)

if __name__=='__main__':unittest.main()
