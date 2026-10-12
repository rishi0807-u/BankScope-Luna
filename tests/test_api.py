import io
import pandas as pd
import pytest
from fastapi.testclient import TestClient
import server

@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setattr(server,'STORE',tmp_path)
    server.sessions.clear()
    with TestClient(server.app) as c:
        token=c.get('/api/bootstrap').json()['token'];c.headers['X-Bankscope-Token']=token
        yield c

def test_preview_apply_undo_export_and_restart(client):
    raw=b'CustomerId,Geography,Age,Churn,Balance,Currency,FXToUSD\na,A,30,1,100,USD,1\nb,B,,0,0,USD,1\nc,A,50,,200,USD,1\n'
    sid=client.post('/api/upload',content=raw).json()['session'];base={'session':sid}
    state=client.post('/api/state',json=base).json();assert state['revision']==0
    plan={**base,'revision':0,'automatic':True,'deduplicate':True}
    preview=client.post('/api/clean',json=plan);assert preview.status_code==200
    assert client.post('/api/state',json=base).json()['revision']==0
    assert client.post('/api/clean',json={**plan,'apply':True}).status_code==200
    assert client.post('/api/clean',json={**plan,'apply':True}).status_code==409
    q={'categories':{'country':['A']}}
    result=client.post('/api/query',json={**base,'query':q}).json()
    assert result['total']==2 and result['kpis']['churn_rate']==100
    export=client.post('/api/export',json={**base,'kind':'filtered','query':q})
    assert len(pd.read_csv(io.BytesIO(export.content)))==2
    excel=client.post('/api/export',json={**base,'kind':'excel','query':q})
    assert len(pd.read_excel(io.BytesIO(excel.content)))==2
    assert client.post('/api/history',json={**base,'action':'undo'}).status_code==200
    assert client.post('/api/history',json={**base,'action':'redo'}).status_code==200
    server.sessions.clear()
    assert client.post('/api/query',json=base).json()['total']==3

def test_all_charts_and_demo_isolation(client):
    sid=client.post('/api/load',json={'dataset':'messy'}).json()['session'];base={'session':sid}
    before=client.post('/api/state',json=base).json()
    for chart in server.CHARTS:
        r=client.post('/api/chart',json={**base,'chart':chart,'query':{'categories':{'country':['India']}}})
        assert r.status_code==200,(chart,r.text)
        assert 'figure' in r.json()
    demo=client.post('/api/demo',json={**base,'count':4}).json()['session']
    assert demo!=sid
    assert client.post('/api/state',json=base).json()['sha256']==before['sha256']
    assert client.post('/api/state',json={'session':demo}).json()['demo']

def test_session_validation_empty_and_origin(client):
    assert client.post('/api/state',json={'session':'../data'}).status_code==400
    assert client.post('/api/load',json={},headers={'Origin':'https://example.com'}).status_code==403
    sid=client.post('/api/load',json={}).json()['session']
    r=client.post('/api/query',json={'session':sid,'query':{'search':'ABSENT-NONEXISTENT'}})
    assert r.status_code==200 and r.json()['total']==0


def test_custom_upload_clean_filter_export_restart(client):
    raw=b'Customer ID;Country Name;Sex;Reward Points;Branch;Postal Code\n001;india;F;10;South;00123\n002;USA;M;;North;00456\n003;;;30;South;00789\n003;;;30;South;00789\n'
    response=client.post('/api/upload',content=raw,headers={'X-Filename':'my%20bank.csv'})
    assert response.status_code==200, response.text
    base={'session':response.json()['session']}
    state=client.post('/api/state',json=base).json()
    assert state['name']=='my bank.csv'
    assert state['options']['country']==['India','United States','Unknown']
    assert state['options']['branch']==['North','South']
    plan={**base,'revision':0,'automatic':True,'deduplicate':True}
    preview=client.post('/api/clean',json=plan).json()
    assert preview['after']['rows']==3
    assert preview['preview'][1]['reward_points']==20
    assert preview['preview'][2]['gender']=='Unknown'
    assert client.post('/api/state',json=base).json()['revision']==0
    assert client.post('/api/clean',json={**plan,'apply':True}).status_code==200
    assert client.post('/api/explore',json=base).status_code==200
    filtered=client.post('/api/query',json={**base,'query':{'categories':{'branch':['South']}}}).json()
    assert filtered['total']==2
    server.sessions.clear()
    restored=client.post('/api/state',json=base).json()
    assert restored['working_preview'][1]['reward_points']==20
    export=client.post('/api/export',json={**base,'kind':'cleaned'})
    frame=pd.read_csv(io.BytesIO(export.content),dtype=str)
    assert frame['postal_code'].tolist()==['00123','00456','00789']
    assert frame['customer_id'].tolist()==['001','002','003']


def test_upload_invalid_encoding_is_actionable(client):
    response=client.post('/api/upload',content=b'country,gender\n\xff,M')
    assert response.status_code==400
    assert 'UTF-8' in response.json()['detail']
