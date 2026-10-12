"""Generate the self-contained teaching notebook from the tested analytics engine."""
from pathlib import Path
import nbformat as nbf

ROOT=Path(__file__).resolve().parent
cells=[]
def md(s):cells.append(nbf.v4.new_markdown_cell(s))
def code(s):cells.append(nbf.v4.new_code_cell(s))
md('''# Banking Customer Behaviour & Asset Analytics
### Extraction → profiling → justified cleaning → segmentation → interactive analysis

**Deliverables:** this reproducible cleaning notebook, exported datasets/audit reports, and the BankScope dashboard website.

The default source is `data/banking_raw.csv`, copied from the supplied 70-country file. Its `DataOrigin` explicitly says **Synthetic classroom simulation**. It is not live banking data. The alternative `data/bank_churn_original.csv` is supplied separately and is not merged with it.

**Important:** imputation cannot recover the true missing value. It is a documented assumption for exploratory analysis. Never impute customer IDs, outcomes, exchange rates or provenance. Preserve the raw file and report unresolved issues instead of forcing completeness to 100%.

Run all cells in order. Python dependencies: pandas, numpy, plotly, openpyxl (see `requirements.txt`). The utilities below are embedded so this notebook can travel with just its input CSV.''')
code('''from pathlib import Path
import hashlib, json, sys
import pandas as pd
import numpy as np
import plotly.express as px
from IPython.display import display, Markdown
pd.set_option('display.max_columns', 40)
ROOT = Path.cwd()
DATA_PATH = ROOT / 'data' / 'banking_raw.csv'
if not DATA_PATH.exists():
    candidates = [ROOT/'banking_raw.csv', ROOT/'banking_70_countries_10000_messy.csv']
    DATA_PATH = next((p for p in candidates if p.exists()), DATA_PATH)
assert DATA_PATH.exists(), 'Place the supplied CSV in data/banking_raw.csv, or change DATA_PATH.'
OUT = ROOT / 'outputs'
OUT.mkdir(exist_ok=True)
print('Input:', DATA_PATH.name)
print('SHA-256:', hashlib.sha256(DATA_PATH.read_bytes()).hexdigest())
print('Python:', sys.version.split()[0], '| pandas:', pd.__version__, '| numpy:', np.__version__)''')
md('''## 1. Reusable, auditable pipeline utilities
This cell embeds the same tested engine used by the website. It defines extraction, schema mapping, missing-token recognition, domain validation, cleaning, transformations, filtering, segmentation and safe exports.

**Project validation assumptions:** adult age 18–110, credit score 300–850, tenure 0–80 and no greater than age, integer-valued counts, nonnegative recorded holdings, binary fields 0/1, positive FX and Bitcoin price. These are configurable project rules, not universal banking laws. Invalid cells become missing in an analytical copy; original strings remain available for review.

Empty/whitespace strings, NA, N/A, null, NaN, ?, -, missing and not available are missing markers. `None` means no loan when it appears in loan type; it is not discarded there. Valid zero balances remain zero.''')
code((ROOT/'analytics.py').read_text(encoding='utf-8').replace('from __future__ import annotations\n',''))
md('## 2. Extract and inspect the actual schema\nRead as strings first so pandas does not silently interpret legitimate category labels as missing. Header mapping is explicit and collisions are rejected.')
code('''raw, mapping = read_csv(DATA_PATH)
raw_snapshot = raw.copy(deep=True)
display(pd.DataFrame(mapping.items(), columns=['source_header','analytical_header']))
print('Shape:', raw.shape)
display(raw.head(10))
display(raw.tail(10))
display(pd.DataFrame([{'column':c,'definition':DICTIONARY.get(c,c.replace('_',' '))} for c in raw]))
print('Provenance:', raw.get('data_origin',pd.Series(dtype=str)).unique())''')
md('## 3. Profile before choosing a cleaning method\nCount textual missingness separately from invalid numeric values. Exact duplicate rows and repeated customer IDs represent different problems. Never automatically merge conflicting IDs.')
code('''typed, conversion_issues = canonical(raw)
before = profile(raw)
display(pd.DataFrame(before['profile']))
display(conversion_issues)
print({k:v for k,v in before.items() if k not in ['profile','definition']})
print(before['definition'])
duplicate_ids = typed.loc[typed.customer_id.notna() & typed.customer_id.duplicated(keep=False)]
display(duplicate_ids.head(20))
invalid_examples=[]
for c in raw:
    mask = ~blank_mask(raw[c],c) & typed[c].isna()
    for row in raw.index[mask][:8]:
        invalid_examples.append({'source_row':int(row)+2,'column':c,'original_value':raw.loc[row,c]})
display(pd.DataFrame(invalid_examples))''')
code('''quality = pd.DataFrame(before['profile'])
px.bar(quality,x='column',y='missing_pct',title='Missing / invalid cells before cleaning (%)',labels={'missing_pct':'Missing or invalid (%)'}).show()
px.imshow(typed.isna().head(300).astype(int).T,aspect='auto',color_continuous_scale=['#e9edf5','#ee7298'],title='Missingness matrix — first 300 source rows').show()''')
md('''## 4. Why mean, median or mode? A defensible decision

- **Mean**: uses every observed value; useful for approximately symmetric continuous measurements without influential extremes. It is pulled toward large outliers. Do not average identifiers, binary labels or mixed local currencies.
- **Median**: the middle observed value; more robust to skew and extreme balances. For money, calculate it **within currency**. Rounded medians preserve integer counts. It reduces variance and is still only an assumption.
- **Mode**: most frequent observed value; applies to categories or discrete values. It can inflate the largest group and conceal missingness. Ties here use pandas' first sorted mode and are not evidence of a uniquely correct replacement.
- **Unknown / keep missing**: preserves uncertainty. Default text treatment is `Unknown`. IDs, churn, binary ownership/status, currency, FX and pricing fields remain missing for review. Missing Bitcoin quantities and contract terms remain missing.
- **Remove rows**: explicit option when essential fields are absent; disclose sample loss and potential selection bias. Never silently remove valid extremes.

The plan below is computed from the observed columns and their distributions. You can edit the plan before the next cell. Exploratory imputation does not justify using the same procedure for a predictive model: fit imputers on training data only to avoid leakage.''')
code('''decision_rows=[]
for c in typed:
    method, reason = recommendation(typed,c)
    s=typed[c]
    decision_rows.append({'column':c,'missing':int(s.isna().sum()),'method':method,'why':reason,
        'skew':s.skew() if c in NUMERIC else None})
decisions=pd.DataFrame(decision_rows)
display(decisions)
plan = dict(zip(decisions.column, decisions.method))
# Examples of explicit overrides:
# plan['age'] = 'median'
# plan['gender'] = 'mode'  # Only if you can justify majority-category substitution.
# plan['industry'] = {'method':'constant','value':'Unknown'}
# plan['churn'] = 'drop'  # Explicitly drop unknown outcomes; never invent labels.
display(pd.DataFrame({'illustrative_values':[10,11,12,13,1000]}).agg(['mean','median']))
print('The small example above is illustrative, not banking records.')''')
md('## 5. Apply the reviewed plan to a copy\nNormalize labels, quarantine invalid entries as missing, remove exact source duplicates, then apply the documented per-column strategy. Conflicting IDs remain flagged. No default outlier removal.')
code('''cleaned, audit = clean(raw, plan=plan, deduplicate=True)
after = profile(cleaned)
comparison=pd.DataFrame([
    {'stage':'Before','rows':before['rows'],'missing_or_invalid_cells':before['missing_cells'],'exact_duplicates':before['exact_duplicates'],'extra_repeated_ids':before['duplicate_ids']},
    {'stage':'After','rows':after['rows'],'missing_or_invalid_cells':after['missing_cells'],'exact_duplicates':after['exact_duplicates'],'extra_repeated_ids':after['duplicate_ids']}])
display(comparison)
display(pd.DataFrame(audit))
display(pd.DataFrame(after['profile']).query('missing > 0')[['column','missing','missing_pct']])
print('Unresolved missing values are intentional when a defensible replacement is unavailable.')
pd.testing.assert_frame_equal(raw,raw_snapshot)
assert len(cleaned)==len(raw)-int(raw.duplicated().sum())
assert cleaned.churn.dropna().isin([0,1]).all()''')
md('''## 6. Missing text, currency and binary cross-checks
`Unknown` is an explicit category and must not be mistaken for observed demographic information. Remaining missing outcomes are excluded from churn denominators. Missing currency is kept for review even when FX is recorded; USD conversion uses the supplied FX only.

The audit reports affected cell counts. The cell-level provenance export records raw values, typed values, final values and whether a value was replaced. Removed exact duplicates have no final row.''')
code('''kept = raw.loc[~raw.duplicated()].copy()
typed_kept = canonical(kept)[0].reset_index(drop=True)
provenance=[]
for c in raw:
    original = kept[c].reset_index(drop=True)
    old = typed_kept[c]
    new = cleaned[c]
    changed = old.astype('string').fillna('<MISSING>').ne(new.astype('string').fillna('<MISSING>'))
    review = changed | old.isna()
    for i in np.flatnonzero(review.to_numpy()):
        provenance.append({'source_csv_row':int(kept.index[i])+2,'customer_id':str(original.iloc[i]) if c=='customer_id' else str(cleaned.customer_id.iloc[i]),
            'column':c,'raw_value':original.iloc[i],'typed_value':old.iloc[i],'cleaned_value':new.iloc[i],
            'imputed':bool(old.isna().iloc[i] and pd.notna(new.iloc[i]))})
cell_audit=pd.DataFrame(provenance)
display(cell_audit.head(30))
print('Missing churn excluded:',int(cleaned.churn.isna().sum()))
print('Valid zero balances retained:',int(cleaned.balance.eq(0).sum()))''')
md('''## 7. Transform without destroying the original scale
Derive age, tenure and credit bands. Convert local money with the row-level FX rate. Bitcoin uses BTC × USD price; it is never multiplied by the local FX rate. Loans are liabilities, excluded from assets. No invented transactions, historical returns, or current market prices.''')
code('''data=transform(cleaned)
display(data.head(10))
print('Derived columns:',[c for c in data if c not in cleaned])
display(outliers(data,'IQR'))
display(outliers(data,'Z-score'))
print('Outliers are retained. IQR flags can include legitimate zeros or large holdings.')
numeric=statistics(data)
display(numeric)''')
md('''## 8. Segregation, dynamic sorting, filtering and extraction
Edit the controls dictionary and rerun this cell. The website provides these controls without editing code. Filters can combine with AND/OR; text search is literal, and sorting is stable. All summaries below use this same selected dataframe.''')
code('''controls = {
    'categories': {'country':['India','United States','Germany']},
    'ranges': {'age':[25,65]},
    'logic':'AND',
    'search':'',
    'sort':[{'column':'balance_usd','ascending':False}]
}
selected=filter_frame(data,controls)
print(f'{len(selected):,} matching records out of {len(data):,}')
display(selected.head(20))
known=selected.churn.count()
print('Known outcomes:',known,'| churn rate:', f'{100*selected.churn.mean():.2f}%' if known else 'Unavailable')
country_summary=segments(selected,'country')
display(country_summary)
for group in ['gender','age_band','credit_band','tenure_band','industry','activity_label']:
    display(segments(selected,group))
display(pd.crosstab(selected.country,selected.churn_label,dropna=False))
high_balance=selected.loc[selected.balance_usd>=100000]
inactive_churned=selected.loc[(selected.active_member==0)&(selected.churn==1)]
print('Selected high-balance records:',len(high_balance),'| inactive and churned:',len(inactive_churned))''')
md('''## 9. Interactive visualization gallery
All charts in this section use `selected`, not the full source. Hover, zoom and export with the Plotly toolbar. Sample sizes and missingness matter when comparing countries. Holding more of an asset does not establish that the asset performs better.''')
code('''if not selected.empty:
    px.bar(country_summary,x='country',y='customers',title='Selected records by country').show()
    px.pie(selected,names='churn_label',hole=.6,title='Selected churn outcomes; Unknown shown separately').show()
    px.histogram(selected,x='age',color='churn_label',title='Selected age distribution').show()
    px.scatter(selected,x='age',y='balance_usd',color='churn_label',opacity=.45,title='Age and account balance (USD)').show()
    px.box(selected,x='country',y='balance_usd',color='country',title='Balance box plots (USD)').show()
    px.violin(selected,x='country',y='balance_usd',color='country',box=True,points=False,title='Balance violin distributions (USD)').show()
    nums=selected.select_dtypes('number').drop(columns=list(MONEY)+['customer_id'],errors='ignore')
    px.imshow(nums.corr(),zmin=-1,zmax=1,color_continuous_scale='RdBu_r',title='Pairwise-complete correlation matrix').show()
    tenure=selected.groupby('tenure',as_index=False).balance_usd.mean()
    px.line(tenure,x='tenure',y='balance_usd',markers=True,title='Balance by tenure — cross-sectional, not historical').show()
    assets=['balance_usd','bitcoin_usd','fixed_deposit_usd','stocks_usd','mutual_funds_usd']
    asset_summary=selected.groupby('country')[assets].sum(min_count=1).reset_index().melt(id_vars='country',var_name='asset',value_name='usd')
    px.bar(asset_summary,x='country',y='usd',color='asset',title='Recorded asset allocation by selected country (USD)').show()
else:
    print('No matching records. Broaden controls and rerun section 8.')''')
md('''## 10. Export the evidence and reproduce the website
Exports include cleaned and transformed data, the exact filtered extraction, before/after profile, column-level decisions, cell-level provenance and an Excel report. CSV text is escaped to avoid spreadsheet formula execution.

To open the full website, run `start_dashboard.bat` from the project folder, then visit http://127.0.0.1:8765. The website uses this same pipeline with cleaning preview/apply, undo/redo, uploads, 23 chart choices, sorting, extraction and report exports.''')
code('''excel_safe(cleaned).to_csv(OUT/'banking_cleaned.csv',index=False)
excel_safe(data).to_csv(OUT/'banking_transformed.csv',index=False)
excel_safe(selected).to_csv(OUT/'filtered_extraction.csv',index=False)
excel_safe(cell_audit).to_csv(OUT/'cell_level_audit.csv',index=False)
decisions.to_csv(OUT/'cleaning_decisions.csv',index=False)
comparison.to_csv(OUT/'quality_before_after.csv',index=False)
pd.DataFrame(audit).to_csv(OUT/'cleaning_audit.csv',index=False)
(OUT/'analytics_report.xlsx').write_bytes(workbook(selected,audit,after))
manifest={'input_sha256':hashlib.sha256(DATA_PATH.read_bytes()).hexdigest(),'input_rows':len(raw),'output_rows':len(cleaned),
          'filters':controls,'plan':plan,'synthetic_source':True,'pandas':pd.__version__,'numpy':np.__version__}
(OUT/'run_manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
print('Saved:',*[p.name for p in OUT.iterdir() if p.is_file()],sep='\\n')''')
md('''## 11. Isolated missing-value demonstration
This is an explicitly artificial four-row illustration, separate from the supplied dataset. It demonstrates empty text, numeric placeholders, the preservation of zero, and currency-aware medians. It is not presented as evidence about the banking source.''')
code('''demo=pd.DataFrame({'customer_id':['demo1','demo2','demo3','demo4'], 'currency':['USD','USD','JPY','JPY'],
                   'balance':['0','NA','10000',' '], 'gender':['Female','  ','Male','null'], 'churn':['1','0','','1']})
demo_clean,demo_log=clean(demo,{'balance':'group_median','gender':'unknown'})
display(demo);display(demo_clean);display(pd.DataFrame(demo_log))
assert demo_clean.balance.tolist()==[0,0,10000,10000]
assert demo_clean.churn.isna().sum()==1
assert demo.loc[1,'balance']=='NA'
pd.testing.assert_frame_equal(raw,raw_snapshot)
assert segments(data,'country').customers.sum()==len(data)
assert len(selected)==len(filter_frame(data,controls))
print('Reproducibility and integrity checks passed.')''')
md('''## 12. Conclusions and viva discussion
1. Report observed source defects and unresolved cells; do not claim all data is now true or complete.
2. Explain why numeric distributions, valid zeros and currency units determine cleaning choices.
3. Disclose the bias introduced by median/mode imputation; compare before/after profiles.
4. Explain repeated customer IDs separately from exact row duplicates. Dashboard counts are records, not necessarily unique people.
5. Compare asset holdings and ownership only within the selected records, with observed counts. These are not real-world investment recommendations.
6. The source is a synthetic snapshot; it cannot support real-time market or historical trend claims.
7. For production: add authenticated multi-user isolation, encrypted storage, retention controls, independent schema review, background processing and deployment monitoring. The delivered website is designed for a local academic demonstration.''')
nb=nbf.v4.new_notebook(cells=cells,metadata={'kernelspec':{'display_name':'Python 3','language':'python','name':'python3'},'language_info':{'name':'python','version':'3.14'}})
nbf.validate(nb)
nbf.write(nb,ROOT/'Banking_Data_Cleaning_Analysis.ipynb')
print('Created notebook with',len(cells),'cells')
