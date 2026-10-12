"""Shared, deterministic analytics pipeline for the notebook and local website."""
from __future__ import annotations
import io
import csv
import re
from datetime import datetime, timezone
import numpy as np
import pandas as pd

MISSING = {'', 'na', 'n/a', 'null', 'nan', '?', '-', 'missing', 'not available'}
ALIASES = {'countryname':'country', 'countries':'country', 'sex':'gender', 'customerage':'age', 'accountbalance':'balance', 'customerid':'customer_id', 'geography':'country', 'creditscore':'credit_score',
 'numofproducts':'products_number', 'numofproduct':'products_number', 'numproducts':'products_number',
 'hascreditcard':'credit_card', 'isactivemember':'active_member', 'estimatedsalary':'estimated_salary',
 'exited':'churn', 'fxtousd':'fx_to_usd', 'bitcoinholdingsbtc':'bitcoin_btc',
 'bitcoinpriceusd':'bitcoin_price_usd', 'fixeddepositbalance':'fixed_deposit',
 'fixeddepositratepct':'fd_rate_pct', 'fixeddeposittermmonths':'fd_term_months',
 'loanbalance':'loan_balance', 'loantype':'loan_type', 'loanratepct':'loan_rate_pct',
 'stocksbalance':'stocks', 'mutualfundsbalance':'mutual_funds', 'hasbitcoin':'has_bitcoin',
 'hasfixeddeposit':'has_fixed_deposit', 'hasloan':'has_loan', 'employmentstatus':'employment_status',
 'accounttype':'account_type', 'bankingchannel':'banking_channel', 'risktolerance':'risk_tolerance',
 'snapshotdate':'snapshot_date', 'dataorigin':'data_origin'}
NUMERIC = {'age','tenure','credit_score','balance','estimated_salary','products_number','fx_to_usd',
 'bitcoin_btc','bitcoin_price_usd','fixed_deposit','fd_rate_pct','fd_term_months','loan_balance',
 'loan_rate_pct','stocks','mutual_funds','churn','credit_card','active_member','has_bitcoin','has_fixed_deposit','has_loan'}
BINARY = {'churn','credit_card','active_member','has_bitcoin','has_fixed_deposit','has_loan'}
PROTECTED = {'customer_id','churn','surname','snapshot_date','data_origin','currency','fx_to_usd','bitcoin_price_usd'}
MONEY = {'balance','estimated_salary','fixed_deposit','loan_balance','stocks','mutual_funds'}
RANGES = {'age':(18,110), 'tenure':(0,80), 'credit_score':(300,850), 'products_number':(0,30),
 'fx_to_usd':(0.00000001,1e6), 'bitcoin_price_usd':(0.000001,1e9), 'fd_rate_pct':(0,100),
 'loan_rate_pct':(0,100), 'fd_term_months':(0,1200)}
DICTIONARY = {'customer_id':'Source customer identifier; never imputed. Repeated IDs require review.',
 'country':'Country recorded by the source; no inference from names or currencies.',
 'churn':'Observed outcome: 1 = churned, 0 = retained. Missing outcomes are excluded from rate denominators.',
 'balance':'Account balance in the row currency. Zero is a valid balance.',
 'fx_to_usd':'Snapshot exchange rate: multiply local currency by this value to obtain USD.',
 'bitcoin_btc':'Bitcoin quantity in BTC; multiply by the supplied USD price, not the FX rate.',
 'loan_balance':'Liability, shown separately from assets.',
 'estimated_salary':'Estimated salary in row currency; not bank revenue.',
 'credit_score':'Source credit score; project validation assumption: 300–850.',
 'age':'Age in years; project validation assumption: adult customers aged 18–110.',
 'tenure':'Bank relationship duration in years; must not exceed age.',
 'snapshot_date':'Snapshot date, not transaction history. Charts do not imply historical trends.',
 'data_origin':'Source provenance. The 70-country file declares synthetic classroom simulation.'}

def read_csv(source):
    try:
        content = source.read() if hasattr(source, 'read') else __import__('pathlib').Path(source).read_bytes()
        text = content.decode('utf-8-sig') if isinstance(content, bytes) else content
        try: delimiter = csv.Sniffer().sniff(text[:65536], delimiters=',;\t|').delimiter
        except csv.Error: delimiter = ','
        df = pd.read_csv(io.StringIO(text), dtype=str, keep_default_na=False, sep=delimiter)
    except (UnicodeError, pd.errors.ParserError, pd.errors.EmptyDataError, csv.Error) as exc:
        raise ValueError('Could not read this CSV. Save it as UTF-8 with a header row and consistent columns.') from exc
    if df.empty or len(df.columns)>150 or len(df)>100000:
        raise ValueError('Use a nonempty CSV with at most 100,000 rows and 150 columns.')
    mapping = {c:ALIASES.get(re.sub(r'[^a-z0-9]', '', c.lower()), re.sub(r'\W+', '_', c.strip().lower())) for c in df}
    if len(set(mapping.values())) != len(mapping):
        raise ValueError('Multiple headers map to the same column. Rename ambiguous columns first.')
    return df.rename(columns=mapping), mapping


def identifier(column):
    return column == 'id' or column.endswith(('_id', '_code')) or any(t in column for t in ('phone', 'postal', 'zip', 'account_number'))


def numeric_column(series, column):
    if column in NUMERIC or column.endswith(('_zscore', '_normalized')):
        return True
    if identifier(column):
        return False
    if pd.api.types.is_numeric_dtype(series):
        return True
    values = series.astype('string').str.strip().mask(blank_mask(series, column)).dropna()
    # Infer only unambiguous numbers; preserve codes with significant leading zeros.
    return bool(len(values) and not values.str.match(r'^[+-]?0\d+').any()
                and pd.to_numeric(values, errors='coerce').notna().all())

def blank_mask(series, column):
    s = series.astype('string').str.strip().str.lower()
    markers = MISSING | ({'none'} if column != 'loan_type' else set())
    return series.isna() | s.isin(markers)

def canonical(raw):
    """Typed analytical view. Invalid cells become NA; raw remains unchanged."""
    df = raw.copy(deep=True)
    issues = []
    for c in df:
        missing = blank_mask(df[c], c)
        s = df[c].astype('string').str.strip().mask(missing)
        invalid = pd.Series(False, index=df.index)
        if numeric_column(raw[c], c):
            if c in BINARY:
                s = s.str.lower().replace({'yes':'1','no':'0','true':'1','false':'0','active':'1','inactive':'0', 'churned':'1','retained':'0'})
            # Accept properly grouped thousands; never strip arbitrary punctuation.
            s = s.str.replace(r'(?<=\d),(?=\d{3}(?:\D|$))','',regex=True)
            out = pd.to_numeric(s, errors='coerce').astype(float)
            invalid = (~missing & out.isna()) | (~np.isfinite(out) & out.notna())
            if c in BINARY: invalid |= out.notna() & ~out.isin([0,1])
            if c in RANGES: invalid |= out.notna() & ~out.between(*RANGES[c])
            if c in MONEY | {'bitcoin_btc'}: invalid |= out.notna() & (out<0)
            if c in {'age','tenure','credit_score','products_number','fd_term_months'}:
                invalid |= out.notna() & (out % 1 != 0)
            df[c] = out.mask(invalid)
        else:
            if c == 'currency': s = s.str.upper()
            elif c in {'country','gender','loan_type','industry','employment_status','account_type','banking_channel','risk_tolerance'}:
                s = s.str.title()
                if c == 'country': s = s.replace({'Usa':'United States','Us':'United States','Uk':'United Kingdom','Uae':'United Arab Emirates'})
                if c == 'gender': s = s.replace({'M':'Male','F':'Female'})
            if c == 'snapshot_date':
                parsed = pd.to_datetime(s, errors='coerce', format='%Y-%m-%d')
                invalid = s.notna() & parsed.isna()
                s = s.mask(invalid)
            df[c] = s
        issues.append({'column':c,'text_or_null_missing':int(missing.sum()),'invalid_values':int(invalid.sum())})
    if {'age','tenure'} <= set(df):
        bad = df.tenure > df.age
        df.loc[bad,'tenure'] = np.nan
        for i in issues:
            if i['column']=='tenure': i['invalid_values'] += int(bad.sum())
    return df, pd.DataFrame(issues)

def profile(raw):
    df, issues = canonical(raw)
    rows=[]
    for c in df:
        s=df[c]; num=pd.api.types.is_numeric_dtype(s)
        r={'column':c,'type':'identifier' if c=='customer_id' else 'binary' if c in BINARY else 'numeric' if num else 'text',
           'missing':int(s.isna().sum()),'missing_pct':round(100*s.isna().mean(),2), 'unique':int(s.nunique()),
           'zeros':int(s.eq(0).sum()) if num else None,'mode':None if s.mode().empty else s.mode().iloc[0]}
        if num:
            r.update({'mean':s.mean(),'median':s.median(),'std_sample':s.std(),'variance_sample':s.var(),
                'min':s.min(),'max':s.max(),'q1':s.quantile(.25),'q3':s.quantile(.75),'skew':s.skew()})
        r.update(issues.set_index('column').loc[c].to_dict()); rows.append(r)
    missing=int(df.isna().sum().sum())
    ids=df.customer_id.dropna() if 'customer_id' in df else pd.Series(dtype=str)
    return {'rows':len(df),'columns':len(df.columns),'missing_cells':missing,
      'completeness_pct':round(100*(1-missing/max(1,df.size)),2),
      'exact_duplicates':int(raw.duplicated().sum()),'normalized_duplicates':int(df.duplicated().sum()),
      'duplicate_ids':int(ids.duplicated().sum()),'profile':rows,
      'definition':'Completeness = 100 × (1 − missing or invalid cells / all cells). It is not a correctness score.'}

def recommendation(df,c):
    s=df[c].dropna()
    if c in PROTECTED or c in BINARY or identifier(c):
        return 'leave','Protected identity, outcome, provenance, exchange rate or binary field: keep missing and review; do not invent facts.'
    if s.empty: return 'leave','No observed values: mean, median and mode cannot be estimated.'
    if not pd.api.types.is_numeric_dtype(df[c]):
        return 'unknown','Use Unknown to preserve missingness; mode is available only when majority-category substitution is justified.'
    if c in MONEY:
        if 'currency' in df:
            return 'group_median','Money is skewed and currencies differ: use the median within each currency, never one pooled local-currency mean. All-missing groups stay missing.'
        return 'median','Median resists extreme financial values; zero is valid. Imputation changes distributions and must be disclosed.'
    if c in {'bitcoin_btc','fd_rate_pct','fd_term_months','loan_rate_pct'}:
        return 'leave','Missing holdings or contract terms are not evidence of zero ownership. Retain for review.'
    skew=s.skew()
    if c in {'age','tenure','credit_score','products_number'} or pd.isna(skew) or abs(skew)>.5:
        return 'median','Median is robust to skew/outliers. For discrete fields the result is rounded to a whole value.'
    return 'mean','Mean uses all observed values and is suitable for an approximately symmetric numeric distribution. Check outliers first.'

def clean(raw, plan=None, deduplicate=True):
    df, issues=canonical(raw)
    audit=[{'timestamp':datetime.now(timezone.utc).isoformat(),'column':r['column'],'method':'normalize / validate',
       'affected':int(r['text_or_null_missing']+r['invalid_values']), 'reason':f"Text/null missing: {r['text_or_null_missing']}; invalid: {r['invalid_values']}. Invalid values quarantined as missing; raw preserved."} for r in issues.to_dict('records') if r['text_or_null_missing'] or r['invalid_values']]
    if deduplicate:
        # Remove only exact raw duplicates; never merge IDs or normalized lookalikes.
        n=int(raw.duplicated().sum()); df=df.loc[~raw.duplicated()].copy()
        audit.append({'column':'all','method':'exact duplicate removal','affected':n,'reason':'Identical source rows only; conflicting IDs retained.'})
    plan = plan if plan is not None else {c:recommendation(df,c)[0] for c in df}
    recommendations={c:recommendation(df,c) for c in df}
    for c,config in plan.items():
        if c not in df: raise ValueError(f'Unknown column: {c}')
        cfg=config if isinstance(config,dict) else {'method':config}
        method=cfg.get('method','leave'); missing=df[c].isna(); n=int(missing.sum())
        if method=='leave' or n==0: continue
        if (c in PROTECTED or identifier(c)) and method!='drop': raise ValueError(f'{c} is protected. Keep missing or explicitly remove incomplete rows.')
        if method=='drop': df=df.loc[~missing].copy(); value='row removed'
        elif method in {'mean','median','group_median'}:
            if not pd.api.types.is_numeric_dtype(df[c]) or c in BINARY: raise ValueError('Numeric imputation requires a continuous numeric field.')
            if method=='group_median':
                if 'currency' not in df: raise ValueError('Currency column required for currency-group imputation.')
                value=df.groupby('currency',dropna=True)[c].transform('median')
            else: value=getattr(df[c],method)()
            if c in {'age','tenure','credit_score','products_number'}: value=np.round(value)
            df[c]=df[c].fillna(value)
        elif method=='mode':
            mode=df[c].mode()
            value=mode.iloc[0] if len(mode) else np.nan
            df[c]=df[c].fillna(value)
        elif method in {'unknown','constant'}:
            value='Unknown' if method=='unknown' else cfg.get('value')
            if pd.api.types.is_numeric_dtype(df[c]):
                try: value=float(value)
                except (ValueError,TypeError): raise ValueError('Provide a numeric replacement.')
            df[c]=df[c].fillna(value)
        else: raise ValueError(f'Unsupported cleaning method: {method}')
        if method!='drop':
            validated,_=canonical(df)
            if (missing & df[c].notna() & validated[c].isna()).any(): raise ValueError('Replacement violates the column validation rules.')
            if c in {'age','tenure'} and {'age','tenure'}<=set(df) and (df.tenure>df.age).any():
                raise ValueError('Imputation creates tenure greater than age. Choose another method or retain missing values.')
        affected=n if method=='drop' else n-int(df[c].isna().sum())
        audit.append({'column':c,'method':method,'affected':affected,'reason':recommendations[c][1] if config==recommendations[c][0] else 'Explicit user-selected method; review assumptions before applying.',
            'replacement':'within-currency median' if method=='group_median' else str(value)})
    stamp=datetime.now(timezone.utc).isoformat()
    for a in audit: a.setdefault('timestamp',stamp)
    return df.reset_index(drop=True),audit

def transform(frame):
    df=frame.copy()
    bands={'age':([0,25,35,45,60,110],['18–25','26–35','36–45','46–60','61+'],'age_band'),
       'credit_score':([299,579,669,739,799,850],['300–579','580–669','670–739','740–799','800–850'],'credit_band'),
       'tenure':([-1,2,5,8,80],['0–2','3–5','6–8','9+'],'tenure_band')}
    for c,(bins,labels,name) in bands.items():
        if c in df: df[name]=pd.cut(df[c],bins,labels=labels).astype('string')
    for c,name,labels in [('churn','churn_label',{0:'Retained',1:'Churned'}),('active_member','activity_label',{0:'Inactive',1:'Active'}),('credit_card','card_label',{0:'No card',1:'Has card'})]:
        if c in df: df[name]=df[c].map(labels).astype('string').fillna('Unknown')
    if 'fx_to_usd' in df:
        for c in MONEY & set(df): df[c+'_usd']=df[c]*df.fx_to_usd
    if {'bitcoin_btc','bitcoin_price_usd'} <= set(df): df['bitcoin_usd']=df.bitcoin_btc*df.bitcoin_price_usd
    if 'balance_usd' in df:
        df['balance_band']=pd.cut(df.balance_usd,[-.01,0,10000,50000,100000,np.inf],labels=['Zero','0–10k','10–50k','50–100k','100k+']).astype('string')
    return df

def filter_frame(df,query=None):
    q=query or {}; masks=[]
    for c,values in q.get('categories',{}).items():
        if c in df and values:
            if pd.api.types.is_numeric_dtype(df[c]):
                masks.append(df[c].isin(pd.to_numeric(pd.Series(values),errors='coerce').dropna()))
            else: masks.append(df[c].fillna('Unknown').astype(str).isin([str(v) for v in values]))
    for c,bounds in q.get('ranges',{}).items():
        if c in df and bounds and len(bounds)==2:
            masks.append(pd.to_numeric(df[c],errors='coerce').between(float(bounds[0]),float(bounds[1])))
    if masks:
        mask=masks[0]
        for m in masks[1:]: mask=mask|m if q.get('logic')=='OR' else mask&m
        df=df.loc[mask]
    term=str(q.get('search','')).strip()
    if term: df=df.loc[df.astype('string').apply(lambda x:x.str.contains(term,case=False,regex=False,na=False)).any(axis=1)]
    sort=q.get('sort',[])
    if sort:
        cols=[s['column'] for s in sort if s['column'] in df]
        if cols: df=df.sort_values(cols,ascending=[s.get('ascending',True) for s in sort if s['column'] in df],kind='stable',na_position='last')
    return df

def segments(df,by):
    if by not in df: return pd.DataFrame()
    groups=df.groupby(by,dropna=False,observed=True)
    out=groups.size().rename('customers').to_frame()
    out['share_pct']=100*out.customers/max(1,len(df))
    if 'churn' in df:
        out['known_outcomes']=groups.churn.count(); out['churned']=groups.churn.sum(min_count=1)
        out['retained']=out.known_outcomes-out.churned
        out['churn_rate_pct']=100*out.churned/out.known_outcomes.replace(0,np.nan)
    for c in ['age','credit_score','balance_usd','estimated_salary_usd','bitcoin_usd','fixed_deposit_usd','stocks_usd','mutual_funds_usd','loan_balance_usd']:
        if c in df:
            out['mean_'+c]=groups[c].mean(); out['observed_'+c]=groups[c].count()
    out['small_sample']=out.customers<30
    return out.reset_index().sort_values('customers',ascending=False)

def outliers(df,method='IQR'):
    rows=[]
    for c in df.select_dtypes('number'):
        if c in BINARY or c=='customer_id': continue
        # Original money must be inspected within currency; compare normalized USD here.
        if c in MONEY and 'currency' in df: continue
        s=df[c]; q1=s.quantile(.25);q3=s.quantile(.75);iqr=q3-q1
        lo,hi=(q1-1.5*iqr,q3+1.5*iqr) if method=='IQR' else (s.mean()-3*s.std(),s.mean()+3*s.std())
        rows.append({'column':c,'q1':q1,'q3':q3,'iqr':iqr,'lower':lo,'upper':hi,'flagged':int(((s<lo)|(s>hi)).sum()),'method':method})
    return pd.DataFrame(rows)

def statistics(df):
    n=df.select_dtypes('number').drop(columns=['customer_id'],errors='ignore')
    if 'currency' in df: n=n.drop(columns=list(MONEY),errors='ignore')
    if n.empty: return pd.DataFrame()
    result=n.describe(percentiles=[.05,.25,.5,.75,.95]).T
    result['median']=n.median();result['variance_sample']=n.var(); result['skew']=n.skew()
    result['iqr']=n.quantile(.75)-n.quantile(.25)
    result['range']=n.max()-n.min()
    result['mode']=n.apply(lambda s: s.mode().iloc[0] if len(s.mode()) else np.nan)
    return result.reset_index(names='column')

def records(df):
    import json
    return json.loads(df.to_json(orient='records',date_format='iso'))

def excel_safe(df):
    """Prevent exported text from being interpreted as spreadsheet formulas."""
    d=df.copy()
    for c in d.select_dtypes(include=['object','string']).columns:
        d[c]=d[c].map(lambda x:"'"+x if isinstance(x,str) and x.lstrip().startswith(('=','+','-','@','\t','\r')) else x)
    return d

def workbook(df,audit,quality):
    b=io.BytesIO()
    with pd.ExcelWriter(b,engine='openpyxl') as w:
        excel_safe(df).to_excel(w,sheet_name='Active data',index=False)
        statistics(df).to_excel(w,sheet_name='Statistics',index=False)
        excel_safe(pd.DataFrame(audit)).to_excel(w,sheet_name='Cleaning audit',index=False)
        pd.DataFrame(quality['profile']).to_excel(w,sheet_name='Quality',index=False)
        if 'country' in df: excel_safe(segments(df,'country')).to_excel(w,sheet_name='Countries',index=False)
        if {'country','churn_label'}<=set(df):
            excel_safe(pd.crosstab(df.country.fillna('Unknown'),df.churn_label.fillna('Unknown')).reset_index()).to_excel(w,sheet_name='Country outcome cross-tab',index=False)
        if {'country','products_number'}<=set(df):
            excel_safe(df.groupby(['country','products_number'],dropna=False).size().reset_index(name='records')).to_excel(w,sheet_name='Product distribution',index=False)
    return b.getvalue()
