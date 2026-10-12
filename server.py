"""FastAPI service for local demo and hosted deployment. Run with uvicorn server:app --host 0.0.0.0 --port 8000."""
import os
from pathlib import Path
from threading import RLock
import hashlib
import io
import json
import secrets
import uuid
from urllib.parse import unquote
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
import analytics as a

ROOT=Path(__file__).resolve().parent
STORE=ROOT/'runtime'; STORE.mkdir(exist_ok=True)
ALLOWED_HOSTS=os.getenv('ALLOWED_HOSTS','127.0.0.1,localhost,testserver,0.0.0.0').split(',')
ALLOWED_ORIGINS=[origin.strip() for origin in os.getenv('ALLOWED_ORIGINS','http://127.0.0.1:8765,http://localhost:8765').split(',') if origin.strip()]
if '*' in ALLOWED_HOSTS: ALLOWED_HOSTS=['*']
if '*' in ALLOWED_ORIGINS: ALLOWED_ORIGINS=['*']
app=FastAPI(title='BankScope local analytics API',version='1.0.0')
app.add_middleware(TrustedHostMiddleware,allowed_hosts=ALLOWED_HOSTS)
app.add_middleware(CORSMiddleware,allow_origins=ALLOWED_ORIGINS if ALLOWED_ORIGINS else ['*'],allow_credentials=True,allow_methods=['*'],allow_headers=['*'])
lock=RLock(); sessions={}; TOKEN=secrets.token_urlsafe(32)

def safe(value):
    return json.loads(json.dumps(value,default=lambda v:v.item() if hasattr(v,'item') else str(v),allow_nan=True),parse_constant=lambda _:None)

@app.middleware('http')
async def local_guard(request,call_next):
    if request.method=='POST':
        origin=request.headers.get('origin')
        if origin and ALLOWED_ORIGINS != ['*'] and origin not in ALLOWED_ORIGINS:
            return JSONResponse({'detail':'Origin not allowed for this deployment.'},status_code=403)
        if request.headers.get('x-bankscope-token')!=TOKEN:
            return JSONResponse({'detail':'Reload the local dashboard to obtain a session token.'},status_code=403)
        if int(request.headers.get('content-length','0'))>25_000_000:
            return JSONResponse({'detail':'Upload limit is 25 MB.'},status_code=413)
    response=await call_next(request)
    if request.url.path=='/' or request.url.path.endswith(('.js','.css')): response.headers['Cache-Control']='no-cache'
    return response

@app.exception_handler(ValueError)
async def invalid(request,exc): return JSONResponse({'detail':str(exc)},status_code=400)

def save(sid):
    s=sessions[sid]; path=STORE/sid;path.mkdir(exist_ok=True)
    s['raw'].to_csv(path/'raw.csv',index=False)
    s['current'].to_csv(path/'working.csv',index=False)
    meta={k:s[k] for k in ['name','mapping','audit','revision','synthetic','sha256','demo']}
    meta['working_numeric_columns']=s['current'].select_dtypes('number').columns.tolist()
    (path/'metadata.json').write_text(json.dumps(safe(meta),indent=2),encoding='utf-8')

def get(sid):
    if not isinstance(sid,str) or not re_id(sid): raise ValueError('Invalid session ID.')
    if sid not in sessions:
        path=STORE/sid
        if not (path/'metadata.json').exists(): raise HTTPException(404,'Dataset session not found.')
        meta=json.loads((path/'metadata.json').read_text(encoding='utf-8'))
        raw=pd.read_csv(path/'raw.csv',dtype=str,keep_default_na=False)
        working=pd.read_csv(path/'working.csv',dtype=str,keep_default_na=False)
        current=a.canonical(working)[0]
        for c in meta.get('working_numeric_columns',[]):
            if c in current: current[c]=pd.to_numeric(current[c],errors='coerce')
        sessions[sid]={**meta,'raw':raw,'current':current, 'undo':[],'redo':[]}
    return sessions[sid]

def re_id(sid):
    try: return str(uuid.UUID(sid))==sid
    except (ValueError,AttributeError): return False

def create(content,name):
    raw,mapping=a.read_csv(io.BytesIO(content)); sid=str(uuid.uuid4())
    origin=' '.join(raw.get('data_origin',pd.Series(dtype=str)).astype(str).unique()).lower()
    sessions[sid]={'raw':raw,'current':a.canonical(raw)[0],'mapping':mapping,'audit':[],
       'undo':[],'redo':[],'name':Path(name).name,'revision':0,'synthetic':'synthetic' in origin,
       'sha256':hashlib.sha256(content).hexdigest(),'demo':False}
    (STORE/sid).mkdir(exist_ok=True); (STORE/sid/'source.csv').write_bytes(content)
    save(sid); return sid

def commit(sid,frame,events):
    s=get(sid); s['undo'].append((s['current'].copy(),list(s['audit'])));s['undo']=s['undo'][-15:]
    s['redo']=[];s['current']=frame;s['audit']+=events;s['revision']+=1;save(sid)

@app.get('/api/bootstrap')
def bootstrap(): return {'token':TOKEN,'datasets':[{'key':'messy','name':'70-country classroom dataset'},{'key':'original','name':'Original churn dataset'}]}

@app.post('/api/load')
def load(body:dict):
    key=body.get('dataset','messy'); path=ROOT/'data'/('banking_raw.csv' if key=='messy' else 'bank_churn_original.csv')
    with lock: sid=create(path.read_bytes(),path.name)
    return {'session':sid}

@app.post('/api/upload')
async def upload(request:Request):
    content=await request.body()
    if len(content)>25_000_000: raise HTTPException(413,'Upload limit is 25 MB.')
    with lock: sid=create(content,unquote(request.headers.get('x-filename','uploaded.csv')))
    return {'session':sid}

@app.post('/api/state')
def state(body:dict):
    with lock:
        s=get(body['session']);df=a.transform(s['current']);typed,_=a.canonical(s['current'])
        options={c:sorted(df[c].fillna('Unknown').astype(str).unique().tolist()) for c in df if not pd.api.types.is_numeric_dtype(df[c]) and not a.identifier(c) and df[c].nunique()<=300}
        ranges={c:[float(df[c].min()),float(df[c].max())] for c in ['age','credit_score','tenure','balance_usd','estimated_salary_usd'] if c in df and df[c].notna().any()}
        return safe({'name':s['name'],'synthetic':s['synthetic'],'demo':s['demo'],'revision':s['revision'],
         'mapping':s['mapping'],'sha256':s['sha256'],'raw_quality':a.profile(s['raw']), 'quality':a.profile(s['current']),
         'options':options,'ranges':ranges,'columns':list(df),'audit':s['audit'],'undo':bool(s['undo']),'redo':bool(s['redo']),
         'recommendations':[{'column':c,'method':a.recommendation(typed,c)[0],'reason':a.recommendation(typed,c)[1]} for c in typed],
         'dictionary':{c:a.DICTIONARY.get(c, c.replace('_',' ').capitalize()+(' in row currency.' if c in a.MONEY else '.')) for c in s['raw']},
         'file_bytes':(STORE/body['session']/'source.csv').stat().st_size,
         'raw_tail':a.records(s['raw'].tail(10)),'working_tail':a.records(s['current'].tail(10)),
         'raw_preview':a.records(s['raw'].head(10)),'working_preview':a.records(s['current'].head(10))})

def make_clean(s,body):
    # First automated pass starts from immutable source; manual changes use working state.
    source=s['raw'] if body.get('automatic') and s['revision']==0 else s['current']
    return a.clean(source,None if body.get('automatic') else body.get('plan',{}),body.get('deduplicate',False))

@app.post('/api/clean')
def cleaning(body:dict):
    with lock:
        s=get(body['session'])
        if body.get('revision')!=s['revision']: raise HTTPException(409,'Dataset changed. Refresh and preview again.')
        df,audit=make_clean(s,body)
        result={'before':a.profile(s['current']),'after':a.profile(df),'audit':audit,'preview':a.records(df.head(10))}
        if body.get('apply'): commit(body['session'],df,audit)
        return safe(result)

@app.post('/api/history')
def history(body:dict):
    with lock:
        sid=body['session'];s=get(sid);action=body.get('action')
        if action=='reset':
            commit(sid,a.canonical(s['raw'])[0],[{'method':'reset','reason':'Restored original source analytical view.','affected':len(s['raw'])}])
        elif action in {'undo','redo'}:
            if not s[action]: raise ValueError('No history available for this action.')
            other='redo' if action=='undo' else 'undo'
            s[other].append((s['current'].copy(),list(s['audit'])))
            s['current'],s['audit']=s[action].pop();s['revision']+=1;save(sid)
        else: raise ValueError('Unknown history action.')
    return {'ok':True}

@app.post('/api/demo')
def demo(body:dict):
    with lock:
        original=get(body['session']);raw=original['raw'].copy();n=min(max(int(body.get('count',5)),1),50,len(raw))
        cols=[c for c in ['age','gender','balance'] if c in raw]
        for i in range(n):
            if cols: raw.loc[raw.index[i],cols[i%len(cols)]]=' '
        raw=pd.concat([raw,raw.head(n)],ignore_index=True)
        if 'balance' in raw: raw.loc[raw.index[-1],'balance']='999999999999'
        sid=create(raw.to_csv(index=False).encode(),'DEMO_COPY.csv');sessions[sid]['demo']=True;save(sid)
    return {'session':sid}

@app.post('/api/transform')
def transformation(body:dict):
    with lock:
        sid=body['session'];s=get(sid);df=s['current'].copy();c=body.get('column');op=body.get('operation')
        if c not in df or c in a.PROTECTED or c in a.BINARY: raise ValueError('Select an unprotected numeric column.')
        if not pd.api.types.is_numeric_dtype(df[c]): raise ValueError('Select a numeric column.')
        x=df[c]
        if op=='standardize':
            scale=x.std();df[c+'_zscore']=(x-x.mean())/scale if scale>0 else np.nan
        elif op=='normalize':
            scale=x.max()-x.min();df[c+'_normalized']=(x-x.min())/scale if scale>0 else np.nan
        elif op in {'cap','remove'}:
            if c in a.MONEY and 'currency' in df: raise ValueError('Mixed-currency outlier treatment requires per-currency review; inspect USD charts instead.')
            q1=x.quantile(.25);q3=x.quantile(.75);lo=q1-1.5*(q3-q1);hi=q3+1.5*(q3-q1)
            if op=='cap': df[c]=x.clip(lo,hi)
            else: df=df.loc[x.isna()|x.between(lo,hi)]
        else: raise ValueError('Unknown operation.')
        result={'before_rows':len(s['current']),'after_rows':len(df),'preview':a.records(df.head(10))}
        if body.get('apply'):
            if body.get('revision')!=s['revision']: raise HTTPException(409,'Refresh the dataset before applying.')
            commit(sid,df,[{'column':c,'method':op,'affected':len(df),'reason':'Explicit user transformation; original source preserved.'}])
        return safe(result)

def kpis(df):
    vals={'records':len(df),'unique_customers':int(df.customer_id.nunique()) if 'customer_id' in df else None,
       'countries':int(df.country.nunique()) if 'country' in df else None}
    if 'churn' in df:
        vals.update(churned=int(df.churn.eq(1).sum()),retained=int(df.churn.eq(0).sum()),known_outcomes=int(df.churn.count()),churn_rate=100*df.churn.mean())
    for c in ['credit_score','age','active_member','credit_card']:
        if c in df: vals['mean_'+c]=df[c].mean()
    for c in ['balance_usd','estimated_salary_usd','bitcoin_usd','fixed_deposit_usd','stocks_usd','mutual_funds_usd','loan_balance_usd']:
        if c in df:
            vals['total_'+c]=df[c].sum(min_count=1); vals['mean_'+c]=df[c].mean();vals['coverage_'+c]=int(df[c].count())
    return vals

@app.post('/api/globe')
def globe_data(body:dict):
    """Country availability ignores country selection but respects every other active filter."""
    with lock:
        s=get(body['session']);df=a.transform(s['current']);q=dict(body.get('query') or {})
        q['categories']={k:v for k,v in q.get('categories',{}).items() if k!='country'}
        filtered=a.filter_frame(df,q)
        return safe({'countries':a.records(a.segments(filtered,'country')),'total':len(filtered),
             'available':sorted(df.country.dropna().unique().tolist()) if 'country' in df else []})

@app.post('/api/explore')
def explore(body:dict):
    with lock:
        df=a.filter_frame(a.transform(get(body['session'])['current']),body.get('query'))
        by=body.get('group') or ('country' if 'country' in df else df.columns[0])
        pivot=body.get('pivot') or ('churn_label' if 'churn_label' in df else by)
        if by not in df or pivot not in df: raise ValueError('Choose grouping columns present in the dataset.')
        if df[by].nunique()>100 or df[pivot].nunique()>100: raise ValueError('Choose categorical fields with at most 100 distinct values for cross-tabs.')
        frequency=df[by].fillna('Unknown').value_counts().rename_axis(by).reset_index(name='records')
        cross=pd.crosstab(df[by].fillna('Unknown'),df[pivot].fillna('Unknown')).reset_index()
        assets=[]
        for c in ['balance_usd','bitcoin_usd','fixed_deposit_usd','stocks_usd','mutual_funds_usd','loan_balance_usd']:
            if c not in df: continue
            values=df[c];known=int(values.count());owners=int(values.gt(0).sum())
            assets.append({'asset':c,'total_usd':values.sum(min_count=1),'mean_usd':values.mean(),
                'median_usd':values.median(),'observed_records':known,'positive_holdings':owners,
                'ownership_pct_of_known':100*owners/known if known else None,
                'missing_records':int(values.isna().sum()),'type':'Liability' if c=='loan_balance_usd' else 'Asset'})
        comparisons=[]
        for dim in ['country','age_band','products_number','activity_label']:
            ss=a.segments(df,dim)
            if not ss.empty and 'known_outcomes' in ss:
                ranked=ss.loc[ss.known_outcomes>=30].dropna(subset=['churn_rate_pct']).sort_values('churn_rate_pct',ascending=False)
                if len(ranked):
                    top=ranked.iloc[0];comparisons.append(f"Highest observed churn by {dim.replace('_',' ')}: {top[dim]} — {top.churn_rate_pct:.1f}% from {int(top.known_outcomes)} known outcomes.")
        if 'churn_label' in df:
            outcomes=a.segments(df,'churn_label')
        else: outcomes=pd.DataFrame()
        return safe({'frequency':a.records(frequency),'crosstab':a.records(cross),'assets':assets,
            'outcome_comparison':a.records(outcomes),'insights':comparisons,
            'products':a.records(df.groupby([by,'products_number'],dropna=False).size().reset_index(name='records')) if 'products_number' in df and by!='products_number' else [],
            'missing_outcomes':int(df.churn.isna().sum()) if 'churn' in df else len(df)})

@app.post('/api/derive')
def derive(body:dict):
    """Safe calculated columns: fixed arithmetic operations only; no eval or arbitrary code."""
    with lock:
        sid=body['session'];s=get(sid);df=s['current'].copy();name=str(body.get('name','')).strip()
        import re
        if not re.fullmatch(r'[a-z][a-z0-9_]{0,49}',name) or name in a.transform(df).columns:
            raise ValueError('Choose an unused name: lowercase letters, digits and underscores, starting with a letter.')
        source=a.transform(df);left=body.get('left');right=body.get('right');op=body.get('operation')
        if left not in source: raise ValueError('Choose an existing source column.')
        if op=='copy': values=source[left].copy()
        else:
            if not pd.api.types.is_numeric_dtype(source[left]): raise ValueError('Arithmetic needs numeric columns.')
            if right not in source or not pd.api.types.is_numeric_dtype(source[right]): raise ValueError('Choose a numeric second column.')
            x,y=source[left],source[right]
            if op=='add': values=x+y
            elif op=='subtract': values=x-y
            elif op=='multiply': values=x*y
            elif op=='divide': values=x/y.replace(0,np.nan)
            else: raise ValueError('Unsupported calculation.')
            values=values.replace([np.inf,-np.inf],np.nan)
        df[name]=values
        result={'preview':a.records(df[[left,name]].head(10)) if left in df else a.records(df[[name]].head(10)),
           'missing':int(values.isna().sum()),'rows':len(df)}
        if body.get('apply'):
            if body.get('revision')!=s['revision']: raise HTTPException(409,'Refresh before applying.')
            commit(sid,df,[{'column':name,'method':op,'affected':len(df),'reason':f'Calculated from {left} and {right}; source columns preserved.'}])
        return safe(result)

@app.post('/api/query')
def query(body:dict):
    with lock:
        s=get(body['session']);full=a.transform(s['current']);df=a.filter_frame(full,body.get('query'))
        by=body.get('group','country');seg=a.segments(df,by)
        size=max(10,min(100,int(body.get('size',25))));page=max(0,int(body.get('page',0)))
        cols=[c for c in body.get('columns',list(df)) if c in df]
        view=df.iloc[page*size:(page+1)*size][cols].copy();view.insert(0,'_row',view.index)
        numeric=df.select_dtypes('number').drop(columns=['customer_id'],errors='ignore')
        if 'currency' in df: numeric=numeric.drop(columns=list(a.MONEY),errors='ignore')
        insights=[]
        if not seg.empty and 'churn_rate_pct' in seg:
            eligible=seg.loc[seg.known_outcomes>=30].dropna(subset=['churn_rate_pct'])
            if not eligible.empty:
                top=eligible.loc[eligible.churn_rate_pct.idxmax()]
                insights.append(f"{top[by]} has the highest observed churn rate among {by.replace('_',' ')} groups with at least 30 known outcomes: {top.churn_rate_pct:.1f}% ({int(top.known_outcomes)} outcomes).")
        if 'activity_label' in df and 'churn' in df:
            rates=df.groupby('activity_label').churn.mean()*100
            if {'Active','Inactive'}<=set(rates.index): insights.append(f"Inactive minus active churn difference: {rates['Inactive']-rates['Active']:.1f} percentage points. This is association, not causation.")
        return safe({'kpis':kpis(df),'rows':a.records(view),'total':len(df),'page':page,'size':size,
         'segments':a.records(seg),'statistics':a.records(a.statistics(df)), 'outliers':a.records(a.outliers(df,body.get('outlier_method','IQR'))),
         'insights':insights,'missing':int(df.isna().sum().sum()),'revision':s['revision'],
         'duplicates':a.records(df.loc[df.customer_id.notna() & df.customer_id.duplicated(keep=False)].head(200)) if 'customer_id' in df else []})

CHARTS=['Country customers','Churn mix','Churn by country','Age histogram','Credit histogram','Balance histogram',
 'Age vs balance','Credit vs salary','Balance box plot','Credit box plot','Age-band churn','Tenure balance',
 'Products churn','Activity churn','Correlation matrix','Card ownership','Country average balance','Tenure customers',
 'Asset allocation','Asset by country','Balance violin','Country and gender churn','Missingness matrix',
 'Country distribution','Age-band churn line','Column completeness']

def figure(df,kind):
    colors=['#4f63ee','#22b8a6','#ecad50','#ee7298','#8793bd']
    px.defaults.color_discrete_sequence=colors
    balance='balance_usd' if 'balance_usd' in df else 'balance'
    salary='estimated_salary_usd' if 'estimated_salary_usd' in df else 'estimated_salary'
    table=pd.DataFrame();cross=None
    if df.empty: return go.Figure().update_layout(title='No records match the active filters'),table,cross
    if kind=='Column completeness':
        table=pd.DataFrame({'column':df.columns,'complete_pct':100*df.notna().mean().values});fig=px.bar(table,x='column',y='complete_pct')
    elif kind=='Country distribution':
        table=df.country.fillna('Unknown').value_counts().rename_axis('country').reset_index(name='customers');fig=px.pie(table,names='country',values='customers');cross='country'
    elif kind=='Age-band churn line':
        table=a.segments(df,'age_band').set_index('age_band').reindex(['18–25','26–35','36–45','46–60','61+']).reset_index();fig=px.line(table,x='age_band',y='churn_rate_pct',markers=True,hover_data=['known_outcomes']);cross='age_band'
    elif kind in {'Country customers','Tenure customers'}:
        c='country' if kind.startswith('Country') else 'tenure';table=df.groupby(c,dropna=False).size().reset_index(name='customers')
        fig=px.bar(table,x=c,y='customers');cross=c
    elif kind in {'Churn mix','Card ownership'}:
        c='churn_label' if kind=='Churn mix' else 'card_label';table=df[c].value_counts(dropna=False).reset_index();fig=px.pie(table,names=c,values='count',hole=.65);cross=c
    elif kind in {'Churn by country','Age-band churn','Products churn'}:
        c={'Churn by country':'country','Age-band churn':'age_band','Products churn':'products_number'}[kind]
        table=a.segments(df,c).sort_values(c);fig=px.bar(table,x=c,y='churn_rate_pct',hover_data=['known_outcomes','small_sample']);cross=c
    elif kind in {'Age histogram','Credit histogram','Balance histogram'}:
        c={'Age histogram':'age','Credit histogram':'credit_score','Balance histogram':balance}[kind]
        table=df[[c]];fig=px.histogram(table,x=c,nbins=35)
    elif kind in {'Age vs balance','Credit vs salary'}:
        x,y=('age',balance) if kind=='Age vs balance' else ('credit_score',salary)
        table=df[[x,y,'churn_label']];fig=px.scatter(table,x=x,y=y,color='churn_label',opacity=.45,render_mode='webgl')
    elif kind in {'Balance box plot','Credit box plot','Balance violin'}:
        c='credit_score' if kind=='Credit box plot' else balance;table=df[['churn_label',c]]
        fig=px.violin(table,x='churn_label',y=c,color='churn_label',box=True,points=False) if kind=='Balance violin' else px.box(table,x='churn_label',y=c,color='churn_label',points='outliers')
    elif kind=='Tenure balance':
        table=df.groupby('tenure')[balance].mean().reset_index();fig=px.line(table,x='tenure',y=balance,markers=True)
    elif kind=='Activity churn':
        table=df.groupby(['activity_label','churn_label']).size().reset_index(name='customers');fig=px.bar(table,x='activity_label',y='customers',color='churn_label')
    elif kind=='Correlation matrix':
        nums=df.select_dtypes('number').drop(columns=['customer_id'],errors='ignore')
        if 'currency' in df: nums=nums.drop(columns=list(a.MONEY),errors='ignore')
        table=nums.corr();fig=px.imshow(table,zmin=-1,zmax=1,color_continuous_scale='RdBu_r');table=table.reset_index()
    elif kind=='Country average balance':
        table=df.groupby('country')[balance].agg(['mean','count']).reset_index();fig=px.bar(table,x='country',y='mean',hover_data=['count']);cross='country'
    elif kind in {'Asset allocation','Asset by country'}:
        cols=[c for c in ['balance_usd','bitcoin_usd','fixed_deposit_usd','stocks_usd','mutual_funds_usd'] if c in df]
        if not cols: raise ValueError('Asset comparison requires monetary fields and supplied FXToUSD rates in your CSV.')
        if kind=='Asset allocation':
            table=pd.DataFrame({'asset':cols,'usd':[df[c].sum(min_count=1) for c in cols],'observed_records':[df[c].count() for c in cols]})
            fig=px.pie(table,names='asset',values='usd',hole=.6,hover_data=['observed_records'])
        else:
            table=df.groupby('country')[cols].sum(min_count=1).reset_index().melt(id_vars='country',var_name='asset',value_name='usd');fig=px.bar(table,x='country',y='usd',color='asset');cross='country'
    elif kind=='Country and gender churn':
        table=df.groupby(['country','gender']).churn.agg(['mean','count']).reset_index();table['churn_pct']=100*table['mean'];fig=px.bar(table,x='country',y='churn_pct',color='gender',barmode='group',hover_data=['count']);cross='country'
    elif kind=='Missingness matrix':
        table=df.isna().astype(int).head(500);fig=px.imshow(table.T,color_continuous_scale=['#e9edf5','#ee7298'],zmin=0,zmax=1,aspect='auto',labels={'x':'First 500 filtered rows','y':'Column','color':'Missing'})
    else: raise ValueError('Unknown chart.')
    fig.update_layout(title=kind,template='plotly_white',font={'family':'Arial','color':'#42516b','size':12},
       margin={'l':55,'r':25,'t':55,'b':65},paper_bgcolor='rgba(0,0,0,0)',plot_bgcolor='rgba(0,0,0,0)',height=370,
       legend={'orientation':'h','y':-0.25},colorway=colors)
    return fig,table,cross

@app.post('/api/chart')
def chart(body:dict):
    with lock:
        df=a.filter_frame(a.transform(get(body['session'])['current']),body.get('query'))
        try: fig,table,cross=figure(df,body.get('chart','Country customers'))
        except (KeyError, AttributeError) as exc: raise ValueError(f'This chart needs fields absent from your file: {exc}')
        return {'figure':json.loads(fig.to_json()),'table':a.records(table.head(500)),'table_rows':len(table),'cross_filter':cross,
        'note':'Snapshot analysis; no historical trend or causal claim. Missing values are excluded per measure. Table preview is limited to 500 rows; chart uses all matching rows.'}

@app.post('/api/export')
def export(body:dict):
    with lock:
        s=get(body['session']);kind=body.get('kind','filtered');df=s['raw'].copy() if kind=='raw' else s['current'].copy() if kind=='cleaned' else a.transform(s['current'])
        if kind in {'filtered','selected','excel','report','statistics'}: df=a.filter_frame(df,body.get('query'))
        if kind=='statistics': df=a.statistics(df)
        if kind=='selected': df=df.loc[df.index.isin(body.get('selected',[]))]
        if kind=='audit': return Response(json.dumps(safe(s['audit']),indent=2),media_type='application/json',headers={'Content-Disposition':'attachment; filename="cleaning_audit.json"'})
        cols=body.get('columns',[])
        if cols: df=df[[c for c in cols if c in df]]
        if kind=='excel': content=a.workbook(df,s['audit'],a.profile(s['current']));ext='xlsx';mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        else: content=a.excel_safe(df).to_csv(index=False).encode('utf-8-sig');ext='csv';mime='text/csv'
        return Response(content,media_type=mime,headers={'Content-Disposition':f'attachment; filename="bankscope_{kind}.{ext}"'})

@app.get('/vendor/plotly.js')
def plotly_js():
    import plotly
    return FileResponse(Path(plotly.__file__).parent/'package_data'/'plotly.min.js',media_type='application/javascript')

@app.get('/')
def home(): return FileResponse(ROOT/'web'/'index.html')
app.mount('/static',StaticFiles(directory=ROOT/'web'),name='static')
