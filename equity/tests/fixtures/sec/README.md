# SEC fixtures (synthetic)

Hand-written for `equity/tests/test_filings.py` (mini fund Stage 2 §1). **None of these files was downloaded.**
They follow the documented shapes of the EDGAR submissions JSON, the tagged `.hdr.sgml` header and the
"KEY: value" lines of a full-submission header, for a fictional company (CIK 9999999).

| Accession | Case |
|---|---|
| -22-000001 | 8-K, daylight time, JSON time equal to the header's UTC time |
| -21-000002 | 8-K, standard time, colon-style header; JSON time differs by -5 h |
| -22-000003 | 8-K, daylight time; JSON time differs by +4 h (the shape seen once on 2026-10-23) |
| -21-000004 | 8-K/A |
| -21-000005 | accepted 18:02 ET on Wed 24 Nov 2021, dated Fri 26 Nov (Thanksgiving on the 25th) |
| -21-000006 | empty `items` in JSON and no `<ITEMS>` in the header |
| -21-000007 | 8-K whose header was not fetched |
| -21-000008 | 10-Q, ignored |

The JSON offsets are invented to exercise the reporting; they say nothing about real SEC data. Before any bulk
use the parser must be run on real headers (owner approval U3).
