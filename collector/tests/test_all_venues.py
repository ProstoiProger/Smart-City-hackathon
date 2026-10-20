from bs4 import BeautifulSoup
from scripts.enrich_all_venues import closure_claim,parse_provider_prices,extract_document

def test_absent_and_false_flags_do_not_establish_open():
    for flags in [{},{'temporary_closed':False}]:
        claim=closure_claim({'flags':flags})
        assert claim['state']=='no_explicit_closure_flag_returned'
        assert claim['physical_closure_verified'] is False

def test_opening_soon_and_removed_not_operating():
    assert closure_claim({'flags':{'temporary_closed':'opening_soon'}})['state']=='opening_soon_as_reported_by_2gis'
    assert closure_claim({'is_deleted':True})['physical_closure_verified'] is False

def test_average_check_is_not_entrance_price():
    values=parse_provider_prices({'attribute_groups':[{'attributes':[{'tag':'food_service_avg_price','name':'Чек 1 500 ₸'}]}]}, {'url':'https://2gis.kz/astana/firm/1','collected_at':'2026-10-19'})
    assert values[0]['kind']=='average_check' and values[0]['amount_min']==1500

def test_shared_prices_preserve_uncertainty_and_skip_weights():
    source={'url':'https://example.org/menu','collected_at':'2026-10-19','soup':BeautifulSoup('<main><p>Салат 250 г</p><p>Кофе 1500 ₸</p></main>','html.parser'),'ld':[]}
    doc,prices,rules=extract_document(source,'chain_branch_unverified')
    assert len(prices)==1 and prices[0]['amount_min']==1500
    assert prices[0]['branch_applicability_verified'] is False

def test_privacy_policy_is_not_a_visitor_rule():
    source={'url':'https://example.org/privacy','collected_at':'2026-10-19','soup':BeautifulSoup('<title>Политика конфиденциальности</title><main>Посетители обязаны передавать персональные данные</main>','html.parser'),'ld':[]}
    assert extract_document(source,'chain_branch_unverified')[2]==[]
