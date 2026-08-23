from market_selective_disclosure import DisclosureRule, disclose

def test_forbidden_fields_never_disclosed():
    p={'offer_id':'o1','price':20,'trusted':True,'private_key':'secret'}
    e=disclose(object_id='o1',object_digest='d'*64,payload=p,rule=DisclosureRule('buyer',('offer_id','price','trusted','private_key')))
    assert e.disclosed == {'offer_id':'o1','price':20}
    assert e.authority_effect == 'none'
