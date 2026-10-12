import io
import json
import subprocess
from pathlib import Path
import pandas as pd
from fastapi.testclient import TestClient
import server
import analytics as a

def test_all_dataset_countries_have_globe_geometry():
    world=json.loads(Path('web/vendor/countries-50m.json').read_text())
    names={g['properties']['name'] for g in world['objects']['countries']['geometries']}
    names.add('United States')
    raw,_=a.read_csv('data/banking_raw.csv')
    expected=set(a.canonical(raw)[0].country.dropna().unique())
    assert len(expected)==70
    assert expected<=names,expected-names

def test_globe_filters_match_country_drilldown_and_exports(tmp_path,monkeypatch):
    monkeypatch.setattr(server,'STORE',tmp_path);server.sessions.clear()
    with TestClient(server.app) as client:
        client.headers['X-Bankscope-Token']=client.get('/api/bootstrap').json()['token']
        sid=client.post('/api/load',json={}).json()['session']
        query={'categories':{'country':['India'],'gender':['Female']},'ranges':{'age':[30,60]},'logic':'AND'}
        base={'session':sid,'query':query}
        globe=client.post('/api/globe',json=base).json()
        result=client.post('/api/query',json=base).json()
        india=next(r for r in globe['countries'] if r['country']=='India')
        assert india['customers']==result['total']
        assert len(globe['available'])==70
        exported=client.post('/api/export',json={**base,'kind':'filtered'})
        data=pd.read_csv(io.BytesIO(exported.content))
        assert len(data)==india['customers'] and data.country.eq('India').all()
        assert data.gender.eq('Female').all() and data.age.between(30,60).all()
        explore=client.post('/api/explore',json=base).json()
        assert sum(r['records'] for r in explore['frequency'])==len(data)
        assert all(r['observed_records']<=len(data) for r in explore['assets'])
        empty=client.post('/api/globe',json={'session':sid,'query':{'search':'NO_RECORDS_EXIST_XYZ'}}).json()
        assert empty['total']==0 and empty['countries']==[]

def test_derived_column_preview_apply_and_persistence(tmp_path,monkeypatch):
    monkeypatch.setattr(server,'STORE',tmp_path);server.sessions.clear()
    with TestClient(server.app) as client:
        client.headers['X-Bankscope-Token']=client.get('/api/bootstrap').json()['token']
        sid=client.post('/api/upload',content=b'CustomerId,Age,Tenure\na,40,10\nb,50,0\n').json()['session']
        body={'session':sid,'name':'age_per_year','left':'age','right':'tenure','operation':'divide','revision':0}
        p=client.post('/api/derive',json=body)
        assert p.status_code==200 and p.json()['missing']==1
        assert 'age_per_year' not in server.get(sid)['current']
        assert client.post('/api/derive',json={**body,'apply':True}).status_code==200
        server.sessions.clear()
        restored=server.get(sid)['current']
        assert restored.age_per_year.iloc[0]==4
        assert pd.api.types.is_numeric_dtype(restored.age_per_year)
