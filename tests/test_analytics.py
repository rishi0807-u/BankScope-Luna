import io
import numpy as np
import pandas as pd
import pytest
import analytics as a

def test_text_missing_and_valid_none():
    raw=pd.DataFrame({'loan_type':['None',' NA ','Personal',''], 'gender':[' female ','  ','NULL','M'], 'balance':['0','abc','-4','1,000']})
    df,issues=a.canonical(raw)
    assert df.loan_type.iloc[0]=='None'
    assert df.loan_type.isna().sum()==2
    assert df.gender.tolist()[0]=='Female'
    assert df.gender.iloc[3]=='Male'
    assert df.balance.iloc[0]==0 and df.balance.iloc[3]==1000
    assert df.balance.isna().sum()==2

def test_currency_imputation_does_not_pool_currencies():
    raw=pd.DataFrame({'currency':['USD','USD','JPY','JPY'],'balance':['100','','10000','']})
    clean,log=a.clean(raw,{'balance':'group_median'})
    assert clean.balance.tolist()==[100,100,10000,10000]

def test_protected_missing_targets_never_imputed():
    raw=pd.DataFrame({'customer_id':['a',''],'churn':['1','']})
    clean,_=a.clean(raw)
    assert clean.churn.isna().sum()==1
    with pytest.raises(ValueError):a.clean(raw,{'churn':'mode'})
    with pytest.raises(ValueError):a.clean(raw,{'customer_id':'unknown'})

def test_exact_duplicates_not_conflicting_ids():
    raw=pd.DataFrame({'customer_id':['a','a','a'],'age':['30','30','31']})
    clean,_=a.clean(raw)
    assert len(clean)==2 and clean.customer_id.duplicated().sum()==1
    assert len(raw)==3

def test_missing_outcome_denominator():
    df=pd.DataFrame({'country':['A']*3,'churn':[1,0,np.nan]})
    seg=a.segments(df,'country')
    assert seg.churn_rate_pct.iloc[0]==50
    assert seg.known_outcomes.iloc[0]==2 and seg.customers.iloc[0]==3

def test_fx_and_bitcoin_units():
    df=pd.DataFrame({'balance':[100,10],'fx_to_usd':[.1,np.nan],'bitcoin_btc':[2,1],'bitcoin_price_usd':[60000,50000]})
    out=a.transform(df)
    assert out.balance_usd.iloc[0]==10 and pd.isna(out.balance_usd.iloc[1])
    assert out.bitcoin_usd.tolist()==[120000,50000]

def test_filters_sort_and_empty():
    df=pd.DataFrame({'country':['A','B','A'],'age':[30,40,50]})
    assert len(a.filter_frame(df,{'categories':{'country':['A']},'ranges':{'age':[40,60]}}))==1
    assert len(a.filter_frame(df,{'categories':{'country':['A']},'ranges':{'age':[40,60]},'logic':'OR'}))==3
    assert a.filter_frame(df,{'search':'[no regex'}).empty
    assert a.filter_frame(df,{'sort':[{'column':'age','ascending':False}]}).age.tolist()==[50,40,30]
    assert len(a.filter_frame(pd.DataFrame({'products_number':[1.,2.,1.]}),{'categories':{'products_number':['1']}}))==2

def test_validation_and_all_missing():
    raw=pd.DataFrame({'age':['200','30'],'tenure':['5','40'],'balance':['','']})
    typed,_=a.canonical(raw)
    assert pd.isna(typed.age.iloc[0]) and pd.isna(typed.tenure.iloc[1])
    clean,_=a.clean(raw)
    assert clean.balance.isna().all()
    with pytest.raises(ValueError):a.clean(raw,{'age':{'method':'constant','value':'-1'}})

def test_formula_export_protection():
    d=a.excel_safe(pd.DataFrame({'name':['=1+1',' +cmd','safe']}))
    assert d.name.iloc[0].startswith("'") and d.name.iloc[1].startswith("'")

def test_real_dataset_integrity():
    raw,_=a.read_csv('data/banking_raw.csv');before=raw.copy(deep=True)
    clean,_=a.clean(raw)
    pd.testing.assert_frame_equal(raw,before)
    assert len(clean)==len(raw)-raw.duplicated().sum()
    assert clean.country.nunique()==70
    assert a.profile(clean)['missing_cells']<a.profile(raw)['missing_cells']
    df=a.transform(clean);seg=a.segments(df,'country')
    assert seg.customers.sum()==len(df)

