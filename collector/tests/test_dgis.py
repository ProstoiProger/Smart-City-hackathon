import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import requests
from scripts.dgis_client import DgisClient,DgisError,load_key
from scripts.dgis_live import search_live

class DgisTests(unittest.TestCase):
    def test_key_can_be_read_without_executing_env_content(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'.env'
            path.write_text('# comment\nDGIS_API_KEY="unit-test-placeholder"\n',encoding='utf-8')
            with patch.dict(os.environ,{'DGIS_API_KEY':''}):
                self.assertEqual(load_key(path),'unit-test-placeholder')

    def test_network_failure_does_not_expose_key(self):
        client=DgisClient(key='unit-test-secret')
        client.session.get=Mock(side_effect=requests.ConnectionError('URL?key=unit-test-secret'))
        with self.assertRaises(DgisError) as raised:
            client.request('items',q='cafe')
        self.assertNotIn('unit-test-secret',str(raised.exception))
        self.assertIsNone(raised.exception.__cause__)

    def test_local_request_cap_prevents_second_request(self):
        client=DgisClient(key='unit-test-secret',max_requests=1)
        response=Mock(status_code=200)
        response.json.return_value={'meta':{'code':200},'result':{'items':[]}}
        client.session.get=Mock(return_value=response)
        client.request('items',q='cafe')
        with self.assertRaises(DgisError):client.request('items',q='cafe')
        self.assertEqual(client.session.get.call_count,1)

    def test_live_mapping_preserves_unknown_fields_and_lat_lon_order(self):
        client=Mock()
        client.request.return_value={'result':{'items':[{'id':'123','type':'branch','name':'Test cafe','point':{'lat':51.1,'lon':71.4},'reviews':{'general_rating':4.5,'general_review_count':0}}]}}
        result=search_live('cafe',51.1,71.4,client=client)
        self.assertEqual(client.request.call_args.kwargs['location'],'71.4,51.1')
        self.assertEqual(result['places'][0]['rating'],4.5)
        self.assertEqual(result['places'][0]['reviews_count'],0)
        self.assertIsNone(result['places'][0]['ratings_count'])
        self.assertIsNone(result['places'][0]['open_now'])
        self.assertEqual(result['storage_mode'],'live_only_no_cache')

if __name__=='__main__':unittest.main()
