# BankScope — Banking Customer & Asset Analytics

A local, working data-cleaning notebook and dashboard website for an academic banking analytics demonstration. Built with Python/pandas, FastAPI and Plotly, plus a responsive HTML/CSS/JavaScript frontend. No cloud account, API key or internet connection is required after installation.

## Open the website

Double-click **start_dashboard.bat**. Open **http://127.0.0.1:8765**. Keep the server window open.

Manual setup (Python 3.11+):

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn server:app --host 127.0.0.1 --port 8765
```

Open `Banking_Data_Cleaning_Analysis.ipynb` in VS Code/Jupyter with the project Python interpreter, or use its executed companion `Banking_Data_Cleaning_Analysis_EXECUTED.ipynb`. All pipeline functions are embedded in the notebook, so it can also run separately with the CSV and listed Python dependencies. Notebook outputs are saved under `outputs/`.

## Demonstration sequence

### Use your own CSV

Click **Upload CSV**, then choose or drop a UTF-8 CSV (comma, semicolon or tab separated; up to 25 MB, 100,000 rows and 150 columns). Upload opens a recommended cleaning preview. Review the before/after counts and sample rows, then click **Apply this cleaning plan**. Download the result with **Download cleaned CSV**. The original is preserved and cleaning can be undone.

Countries, genders and other categorical filters use the uploaded records. Headers such as `Country Name`, `Geography`, `Sex` and `Customer ID` are recognized. Additional unambiguous numeric columns support numerical cleaning and statistics; codes with leading zeros remain text. Missing categories become `Unknown`, numeric replacements use the displayed recommendation, and exact duplicate rows can be removed. Missing identifiers and outcomes remain missing. No customers or country data are invented. Banking charts require the corresponding source columns; USD totals require supplied exchange rates.

**New: World explorer opens first.** Drag the Earth to spin, scroll or use +/− to zoom, and click a highlighted country or cyan marker. Small countries such as Singapore and Bahrain have markers. The country dropdown provides keyboard-accessible selection. Auto-rotate and Reset view are available. Country selection updates the global filters and country profile, asset ownership, customer records, charts and exports. Country focus switches to AND logic so results cannot include other countries through an OR condition. Other filters remain active. Countries outside the dataset show an explicit no-data message. All 70 supplied countries have corresponding local map geometry.

The globe uses D3 orthographic projection and Natural Earth country boundaries packaged locally through world-atlas. Boundary geometry is independent of banking data. Attribution and dependency versions are in `web/vendor/NOTICE.md`.

Additional workspaces include **Exploratory analysis** (frequencies, cross-tabs, outcome comparisons and product distribution) and **Insights** (filtered segment findings and coverage). Overview now exposes retained/churned counts, credit score, average balance/salary, active-member and card ownership percentages. Advanced global filters include tenure, salary and card ownership. Segmentation includes side-by-side comparison. Transformations include safe calculated columns and renamed copies, with preview/apply and persistence. Select IQR or Z-score for outlier inspection. Statistics CSV, before/after missingness charts, file size, tail previews, CSV drag-and-drop, numeric plot-range filtering and return-from-sandbox controls are included.

1. **Dataset & source**: inspect the source, explicit column mapping and raw/working previews. Choose either supplied CSV or upload a compatible one.
2. **Data quality**: inspect textual missingness, invalid values, completeness and duplicate-ID conflicts.
3. **Cleaning studio**: preview recommended cleaning, explain the displayed mean/median/mode rationale, then apply. Compare missing counts. Undo, redo or reset.
4. **Transformations**: inspect currency conversion and outliers. Preview scaling or explicit outlier treatment before applying.
5. Set country, gender, age, membership, outcome and optional balance/credit/industry filters. Click **Apply filters**. Ctrl-select multiple countries. Every analytical chart/table uses the resulting selection. Quality and cleaning explicitly refer to the full dataset.
6. **Customer explorer**: sort by two columns, select output columns, page through records, inspect a record, select rows, and export.
7. **Segmentation / Asset intelligence**: compare countries and groups. Check observed counts and denominators.
8. **Chart laboratory**: compare any two of 26 chart views including bar, box, violin, matrix, line, pie, scatter and histogram. Use the plot camera icon to export PNG. Supported numeric plots accept box-selection range filters.
9. **Reports & exports**: download CSV, workbook or audit; use Print / Save PDF for a browser-generated report.
10. **Cleaning studio sandbox**: inject defects into a separate copy. Load a source again to leave the sandbox.

## Data provenance and analytical assumptions

- `data/banking_raw.csv` copies the supplied `banking_70_countries_10000_messy.csv`: **synthetic classroom simulation**, 34 columns, 70 normalized country categories. It is not real-time data.
- `data/bank_churn_original.csv` copies the supplied `Bank Churn Modelling.csv`. It has a different schema and does not provide FX/asset fields; unsupported asset charts display an explanation. No currency is invented for it.
- Source extraction preserves strings; missing tokens, whitespace and invalid numeric domains are profiled before treatment. Loan type `None` is a legitimate category. Zero balances are valid.
- Schema assumptions: adult age 18–110, score 300–850, tenure at most age, binary fields 0/1 and nonnegative holdings. These configurable rules are not universal banking standards.
- Recommended cleaning removes **exact source duplicates only**. Repeated conflicting IDs remain for review. Customer cards distinguish records from distinct IDs.
- Numeric core fields use rounded medians. Monetary replacements use within-currency medians; missing-currency/all-missing groups remain unresolved. Text defaults to `Unknown`; mode is an explicit alternative with a bias explanation.
- IDs, churn, binary status/ownership, currency, FX and Bitcoin price are not automatically imputed. Missing BTC quantities and contract terms stay missing. Missingness is not proof of zero holdings.
- USD money = local amount × supplied FX. Bitcoin USD = BTC quantity × supplied price. Loans are liabilities and are excluded from asset allocation. Aggregate amounts may include explicitly imputed values after cleaning; inspect the audit.
- Churn rate = churned / known outcomes. Unknown outcomes are excluded from the denominator and shown separately in outcome charts. Small groups are flagged. Standard deviation/variance use n−1, correlation uses pairwise observations.
- No fabricated customer histories, return estimates, predictions, causal findings, or historical trends.

## Architecture and reproducibility

- `analytics.py`: shared extraction, validation, cleaning, filtering, segmentation and export engine.
- `server.py`: local API, revision checks, CSV upload, chart generation, persistence, preview/apply and history.
- `web/`: dashboard UI and locally served Plotly JavaScript. No CDN or external font dependency.
- `build_notebook.py`: generates the self-contained notebook from the same engine.
- `tests/`: semantic pipeline and API tests, including currency-aware imputation, protected fields, filter/export agreement, all chart choices, session restoration and sandbox isolation.
- `outputs/`: executed notebook exports, cleaning decisions, audit and analytical workbook.
- `runtime/<session UUID>/`: immutable source bytes, mapped raw CSV, working CSV, metadata and audit. The browser remembers the session identifier. Restart restores working data/audit; undo/redo is in-memory only (up to 15 versions).

API documentation: **http://127.0.0.1:8765/docs**. POST endpoints require the local bootstrap token in `X-Bankscope-Token`. These protections and loopback binding are for a local demonstration, not Internet authentication.

```powershell
.\.venv\Scripts\python.exe -m pytest -q
node tests/globe_interactions.cjs
.\.venv\Scripts\python.exe build_notebook.py
```

## Scope and limits

This is a substantive academic project with tested analytics and production-minded safeguards, **not a certified production banking system**. It runs locally rather than on a public hosting service. No authentication, multi-user authorization, encryption-at-rest or disaster recovery is included. Do not expose the server on a public interface. Uploads are limited to 25 MB, 100,000 rows and 150 columns. Chart source-table previews are capped at 500 rows (charts use all filtered rows); duplicate review previews at 200. Sessions are retained locally until manually removed. State history is bounded and processing is synchronous. CSV headers are mapped explicitly; unexpected extra columns are retained, but charts require their corresponding banking concepts.

The reference brief mentions React and several cloud-style features. This implementation uses a lightweight browser frontend and Python analytics to deliver an offline local demonstration; it does not claim to implement a React stack or public deployment. PDF export uses your browser's print dialog. The notebook and website are the requested deliverables; no presentation deck is included.
