# Land risk monitor

Turns oil and gas lease documents into structured, confidence-scored records, links them to public Texas Railroad Commission (RRC) production, and flags leases at risk of lapsing: shut-in payments coming due, production gaps, primary terms ending undeveloped.

A lease becomes a record in seconds, a person checks only the shaky fields, and the record lands in a risk view that shows which leases need action and by when. It runs end to end on synthetic leases (offline, two minutes), and on 20 real signed leases from SEC filings joined to 3.4 million months of RRC production.

![Risk dashboard on the synthetic demo](docs/img/dashboard.png)

## What real data taught me

The synthetic demo scores almost perfectly, because the generator and the extractor were written together. The useful work started when the same pipeline met real leases and real RRC data.

| | Synthetic demo (18 leases) | Real leases (20, SEC exhibits) |
| --- | --- | --- |
| Fields a person still has to check | 10% | 36% |
| Pugh clause accuracy | 100% | **50%** (10/20), then **75%** after sharpening the definition |
| Fields skipped review that were wrong | 0 | 1 of 166 (a Pugh false alarm at 99% confidence) |

- **The model mistakes lookalike clauses for Pugh clauses.** All 9 Pugh false alarms were a voluntary surrender clause ("Lessee may at any time ... deliver a release") or a shut-in clause, neither of which ends the lease as to non-producing land. Naming both in the field definition fixed all 9, including the one wrong answer at 99% confidence, and moved accuracy from 50% to 75%. It also overcorrected: the model now misses 2 real Pugh clauses and flags 2 leases it got right before. All 5 remaining errors are below the review threshold, so none would skip a person.
- **My first labels just agreed with the model.** All 260 matched its output, so `evaluate` reported a meaningless 100%. Labeling is now blind by option: the model's answer stays hidden until you record yours. The re-run made the cost concrete: where it disagreed with labels copied from the first run (continuous drilling of 180 days, quoted from the lease, against a copied 90), the new run looked right and the label wrong.
- **Checks tuned on synthetic text misfire on real text.** The two-royalty-rates check flagged 3 real leases for late-payment interest and an overriding royalty (now 0); the verbatim-evidence check fails quotes the model shortens with "...", which drives much of the 36%.
- **RRC's newest months aren't real yet.** The PDQ dump carries unfiled placeholder months (zero production everywhere) and a partly filed newest month. Measuring gaps to the newest row overstated every production gap by 3 to 4 months and raised false shut-in alerts. The latest month is now the last one whose filed reports reach 90% of normal, using RRC's report-filed flag. A version based on producing leases was rejected because a wave of shut-ins would move the date.
- **Recorded leases and RRC leases share no key.** Linking is suggest-and-confirm: candidates in the lease's county scored on lessor surname against RRC lease name, operator against lessee, and timing. The land description turned out to be the best signal: leases on producing land name the RRC lease ("The F. C. Hinds oil and gas lease") or cite its number.
- **Once linked, the alerts are real.** A Milam County lease's RRC lease stopped producing in February 2026 and its 90-day shut-in deadline has passed; a Johnson County lease is held by 34 Barnett Shale gas wells drilled after it was signed; an undated Shackelford County lease shows no production since 1997 (which also exposed a bug: an unknown primary term silenced every production rule).

<table><tr>
<td width="62%"><img src="docs/img/lease.png" alt="Lease page with production history and abstracted terms"></td>
<td><img src="docs/img/conflict.png" alt="Review card showing both royalty rates a lease states, each with its clause"><br><sub>When a lease contradicts itself (here an Exhibit A rider), the review card shows every reading with its clause.</sub></td>
</tr></table>

## What's real and what isn't

- **The demo leases are synthetic**: generated, watermarked on every page, and naming a fictional lessee. Nothing here is a bpx record. The production data is real public RRC data.
- **The 20 real leases** are signed leases small operators filed as SEC exhibits, mostly Texas Producers 88 forms from 1989 to 2026. They name real people, so they stay local (`data/` is gitignored) and none appear in this repo.
- **The real-lease answer key is partial.** Pugh labels were made blind against quoted clauses (by an AI assistant, with each label's deciding quote saved for audit; a landman's review would make them authoritative). The other fields were labeled by accepting the model's output, so their scores measure agreement, not accuracy, and aren't reported above.
- **6 of the 20 leases are linked to RRC production** with confidence; the rest need legal descriptions or well locations a landman would check.
- **Built with an AI pair programmer** (Claude Code). The design decisions and their tradeoffs are written up in [docs/decisions.md](docs/decisions.md).

## How it works

```mermaid
flowchart LR
    PDF[Lease PDFs] --> X[LLM extraction<br/>Groq]
    X --> V[Validation checks<br/>can only lower confidence]
    V -->|confident| W[(DuckDB raw)]
    V -->|low confidence| Q[Review queue<br/>Next.js]
    Q -->|accept / correct| W
    RRC[RRC PDQ dump<br/>filtered to an operator<br/>or counties] --> W
    W --> DBT[dbt models + tests]
    DBT --> R[lease_risk mart]
    R --> API[FastAPI] --> UI[Risk dashboard<br/>Next.js]
```

1. **Extract.** Each PDF's text goes to an LLM, which returns every field with a value, a self-reported confidence and a verbatim evidence quote.
2. **Validate.** Deterministic checks can only lower confidence: the evidence must appear in the document (a hallucination guard), values must be in plausible ranges, and documents that state two royalty rates (an Exhibit A rider) or separate execution and effective dates are capped below the review threshold.
3. **Review.** Fields under the threshold (default 0.85) go to a review queue that shows the field, the evidence and the PDF side by side.
4. **Model.** dbt applies reviews, pivots the fields into a typed `leases` table, attributes RRC production to each tract, and builds `lease_risk`.
5. **Act.** The dashboard shows a plat-style grid of tracts by risk, a "what to do next" list ordered by deadline, and a page per lease.

### Risk rules

| Flag | Rule | Severity |
| --- | --- | --- |
| Shut-in payment overdue | Production stopped, the lease has a shut-in clause, and the payment deadline (cessation + grace days) has passed | High |
| Term ended, never produced | Primary term is over and no production is linked to the tract | High |
| Production stopped | Past the primary term and no production for 3+ months (high at 6+, or with no shut-in clause) | Medium to high |
| Term ending, undeveloped | Primary term ends within 180 days and nothing has produced (high within 90) | Medium to high |
| Shut-in payment due soon | Payment deadline within 60 days | Medium |
| Fields awaiting review | Any field still in the review queue | Low |

Production gaps are measured against the latest month RRC has reported, not today, because RRC data lags two to three months. Thresholds live in `dbt/dbt_project.yml` vars.

## Quick start (offline, about two minutes)

Runs everything on a synthetic RRC sample and a mock extractor, so you need no data download and no API key.

Requires Python 3.11+ and Node 20+ (CI runs Python 3.12 and Node 22).

```bash
python -m venv .venv
# macOS/Linux: source .venv/bin/activate     Windows: .venv\Scripts\activate
pip install -r requirements.txt

python cli.py demo      # sample RRC data -> 18 synthetic leases -> mock extraction -> dbt build -> evaluation
python cli.py serve     # API on http://localhost:8000

# in a second terminal
cd web
npm install
npm run dev             # app on http://localhost:3000
```

DuckDB allows one writer at a time, so stop `serve` before re-running `demo`, `build` or any other pipeline command.

## Real run: one operator's wells and Groq extraction

1. **Set up secrets.** Copy `.env.example` to `.env` and add your `GROQ_API_KEY`. `.env` is gitignored; never commit it.
2. **Download the RRC production dump.** From the RRC [Data Sets Available for Download](https://www.rrc.texas.gov/resource-center/research/data-sets-available-for-download/) page, get the Production Data Query Dump (`PDQ_DSV.zip`, about 3.7 GB, refreshed monthly).
3. **Load an operator's leases.** This streams the zip and keeps only operators matching `RRC_OPERATOR_PATTERN` (default `^BPX`, bpx Energy). Check the matched names it prints and tighten the pattern if needed.
   ```bash
   python cli.py ingest-rrc --zip path/to/PDQ_DSV.zip --since 201801
   ```
4. **Generate leases tied to those RRC leases,** extract them with Groq, score the extraction and build:
   ```bash
   python cli.py generate --count 18
   python cli.py extract --provider groq
   python cli.py evaluate
   python cli.py build
   python cli.py serve
   ```

`evaluate` prints per-field accuracy plus the two numbers that matter: **auto-accept precision** (how often fields that skipped review were right) and **review load** (the share of fields a person still checks).

## Real leases from SEC EDGAR

The synthetic leases have a perfect answer key but read like what the generator was written to produce. To test extraction on real documents, `ingest-edgar` collects signed oil and gas leases that small operators attached to SEC filings. They are mostly Texas Producers 88 forms; the command searches EDGAR full text, rejects blank forms, bundles, duplicates and documents that only mention a lease, and writes each lease as a PDF.

They are real documents that name real people, so everything stays under `data/` (gitignored). They also come with no answer key, so you label them yourself.

1. Add `SEC_USER_AGENT="Your Name you@example.com"` to `.env`. SEC requires a name and contact email on every request; the command stays at five requests a second, half of SEC's limit.
2. Collect 20 leases and write `data/real/edgar/pdfs/`, `manifest.csv` (source filing for each) and a blank `labels.csv`:
   ```bash
   python cli.py ingest-edgar --count 20
   ```
3. Extract with Groq into a separate database, so real leases stay out of the demo dashboard. Leases longer than `GROQ_MAX_INPUT_TOKENS` (default 4000, sized for Groq's free tier) are extracted in parts and merged; parts that disagree go to review.
   ```bash
   python cli.py --db data/real/edgar.duckdb extract --provider groq --pdf-dir data/real/edgar/pdfs
   python cli.py --db data/real/edgar.duckdb build
   ```
4. Label them in the browser. Run a second copy of the app against the EDGAR database (the demo keeps running on 3000/8000):
   ```bash
   LANDRISK_DB=data/real/edgar.duckdb LANDRISK_PDF_DIR=data/real/edgar/pdfs \
     LANDRISK_PRODUCTION_LINKED=false LANDRISK_REVIEW_SKIP_FIELDS=tract_id python cli.py serve --port 8001

   # in web/
   NEXT_DIST_DIR=.next-real NEXT_PUBLIC_API_URL=http://localhost:8001 NEXT_PUBLIC_LABEL_SKIP=tract_id \
     NEXT_PUBLIC_LINKING=1 NEXT_PUBLIC_SITE_NOTE="Real leases from SEC EDGAR filings" npx next dev -p 3001
   ```
   `LANDRISK_PRODUCTION_LINKED=false` tells the risk rules these leases aren't linked to RRC production yet, so the dashboard says production is unknown instead of flagging them as never produced. `LANDRISK_REVIEW_SKIP_FIELDS=tract_id` stops the missing tract IDs counting as fields awaiting review.

   Open http://localhost:3001/review?mode=label. **Label all fields** shows every field, not only the low-confidence ones, next to the PDF: accept it, correct it, or mark it **Not in lease**. Checking the confident fields too is what makes the labels able to measure auto-accept precision. Labels save as you go. `tract_id` is left out because real leases describe land by survey and abstract, not tract IDs.
5. Export and score. `export-labels` uses only leases with every field labeled, writes `labels.csv` and `training.jsonl` (document text plus correct fields), and loads them as the answer key:
   ```bash
   python cli.py --db data/real/edgar.duckdb export-labels
   python cli.py --db data/real/edgar.duckdb evaluate
   ```

6. Link production. Recorded leases and RRC leases share no key, so this is a suggest-and-confirm step. The easiest way is the **Link production** screen (start the web app with `NEXT_PUBLIC_LINKING=1`): each lease's PDF and land description beside its candidate RRC leases with production charts, a search for ones the shortlist missed, and This one / No match buttons that save as you go. Many leases on land that already produced name the RRC lease in the land description ("The F. C. Hinds oil and gas lease") or cite its number; those rank first. The CSV route below does the same in bulk. Load every RRC lease with wells in the leases' counties (production from 1993), then score candidates for each lease on the RRC lease name against the lessor, the operator against the lessee, and production timing against the effective date:
   ```bash
   python cli.py --db data/real/edgar.duckdb ingest-rrc --zip path/to/PDQ_DSV.zip --county Milam --county Caldwell ...
   python cli.py --db data/real/edgar.duckdb link-rrc
   ```
   Open `data/real/edgar/rrc_candidates.csv`, put `y` in the `confirm` column of the right RRC lease for each lease (more than one if the lease feeds several), and leave a lease unmarked when none fits. Then load the links and restart the labeling API without `LANDRISK_PRODUCTION_LINKED=false`:
   ```bash
   python cli.py --db data/real/edgar.duckdb apply-links
   python cli.py --db data/real/edgar.duckdb build
   ```
   A linked lease gets its RRC lease's whole production; real leases rarely say how a pooled unit is split.

You can also fill in `labels.csv` by hand and run `load-labels` instead of steps 4 and 5: a blank cell means the lease doesn't state the field and `-` means don't score it.

## Commands

| Command | What it does |
| --- | --- |
| `python cli.py demo` | Full offline run on sample data |
| `python cli.py sample-rrc` | Write and load the synthetic RRC sample only |
| `python cli.py ingest-rrc --zip ...` | Load the real PDQ dump, filtered to one operator (or `--county`, repeatable) |
| `python cli.py link-rrc` | Suggest RRC leases for each lease document (writes `rrc_candidates.csv`) |
| `python cli.py apply-links` | Load the RRC links confirmed in `rrc_candidates.csv` |
| `python cli.py generate` | Generate synthetic lease PDFs and their answer key |
| `python cli.py extract --provider groq` | Extract fields (`--provider mock` works offline) |
| `python cli.py ingest-edgar` | Collect real executed leases from SEC EDGAR exhibits |
| `python cli.py export-labels` | Turn label-mode reviews into `labels.csv`, `training.jsonl` and the answer key |
| `python cli.py load-labels` | Load a hand-filled `labels.csv` as the answer key |
| `python cli.py evaluate` | Score extraction against the answer key |
| `python cli.py --db PATH ...` | Run any command against another DuckDB file |
| `python cli.py build` | Run dbt models and tests |
| `python cli.py serve` | Start the API |

## Project layout

```
landrisk/         Python pipeline: RRC ingest, lease generator, extraction, evaluation
dbt/              dbt project (DuckDB): staging, intermediate, marts, tests
api/              FastAPI service
web/              Next.js app: risk dashboard, lease pages, review queue, labeling, production linking
docs/             Design decisions and screenshots
data/             Local database, PDFs and downloads (gitignored)
```

## Data notes

- **RRC leases are not mineral leases.** RRC assigns regulatory lease numbers per district; production is reported per RRC lease, not per well. `raw.tract_rrc_xref` plays the role of the land system's mapping from tracts to the RRC leases they feed, with an allocation share.
- **The PDQ dump** is `}`-delimited with a header row, no quoting and space-padded values, one `.dsv` per table ([RRC PDQ dump manual](https://rrc.texas.gov/media/50ypu2cg/pdq-dump-user-manual.pdf)).
- **Scanned leases** need OCR before extraction; the generated PDFs have a text layer.
- **The SQL is Snowflake-ready.** Models use standard SQL plus a few DuckDB functions (`list_filter`, `arg_max`, `date_diff`) that have direct Snowflake equivalents.

## Next steps

- "Ask Land": natural-language questions over the marts, with citations to the source lease.
- Continuous drilling clause tracking from RRC permit and completion dates.
- Louisiana (SONRIS) production for the Haynesville.
- A Palantir Foundry slice: Lease, Tract, Well and Owner as ontology objects with a "flag for review" action.
