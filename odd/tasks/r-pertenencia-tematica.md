# R · topical membership (D-119) + new TVN data

## Objective
Make the attention score actually rank: restore the topical half of R ("relation with Panama **and with the modality's topics**", PDF section 4) without depending on fine-grained classifier confidence, and test the resulting order on the real snapshot, with an exploratory DeepSeek cross-check.

## Problem
Last run (`outputs/puntaje.json`, 60 groups): R mean 0.92 (almost always 1) and N 0.9986 (almost constant) → 45 of 100 points fixed; 70 % of groups land in "alto", 0 % in "bajo". D-103 removed the topical part of R.

## Scope (authorized 2026-10-08)
- Integrate the 2026-10-08 TVN RSS capture into `noticias.csv` + manifest v1.4 (branch `datos-tvn-20261008`).
- D-119: R = foco × pertenencia temática (discrete, values in `config/reglas_v1.3.yaml`, documented in `docs/parametros.md`, with tests).
- Run the scoring pipeline on the real snapshot and compare the order before/after.
- Exploratory DeepSeek check of the order (scratchpad script, not part of the deterministic pipeline; reported as LLM judgment, never as human — D-101).

## Constraints
- Score stays deterministic code; no magic numbers in `src/`; no `if modalidad`.
- Do not weaken existing asserts; D-103 still forbids using classifier *confidence* in R.
- N stays as is (near-constant because the corpus has few duplicates: a data limitation to declare).
- TDD: off (project has no TDD configuration); ordinary checks: `poetry run pytest -v`.

## Tasks
- [x] T1 · Commit data integration (268 news, 117 useful; manifest v1.4) — route: inline · commit `ccb2a8e` · pytest 2862 passed, 3 skipped, 6 xfailed (fixed: 47 new rows in docs/exploracion_revision.csv)
- [x] T2 · D-119 R topical membership: code + config + parametros + tests — route: delegated writer (2+ non-trivial files)
- [x] T3 · Re-run puntaje on real data; before/after distribution and top 10 — route: inline
- [x] T4 · DeepSeek exploratory cross-check of the order — route: inline (scratchpad script)
- [x] T5 · Labeling sample extension for the 47 new news, pre-filled with DeepSeek proposals; a person reviews every row (D-85/D-101; method declared in docs/etiquetado.md) — route: delegated writer after T2 (shares src/configuracion.py). Proposals generated: 47/47 (scratchpad `propuestas_llm_20261008.csv`): ruido ninguno 11, fuera_de_temas 23, no_es_panama 13; 9 with doubt. Authorized 2026-10-08 (user will review).

- [x] T6 · Relabel the 13 "Trump redirige ayuda" rows in eval/etiquetas/javier_acosta.csv to no_es_panama (user decision 2026-10-08: "no tiene nada que ver con Panamá"); `eval.etiquetar --validar` OK — route: inline
- [x] T7 · D-120 regional exception needs impact evidence (international outlet + no Panama name + no guide phenomenon → no_es_panama); El Niño and Panamanian outlets stay — route: delegated writer (config + limpieza + configuracion + tests + docs). User first proposed "all GDELT without Panama mention → noise"; rejected with evidence (44/59 incl. 20 El Niño protected by D-84 and Panamanian-outlet notes).
- Claude label proposals for the 47 (eval/propuestas/llm_claude_20261008.csv; precedence over DeepSeek verified). Labeling app running at http://localhost:8501 for the user's review.

- T7 result (writer): config/ruido.yaml `panama.fenomenos_regionales_con_impacto`, src/limpieza.py `_medio_panameno`/`_regional_sin_impacto`, 6 tests, test_ruido updated, parametros + guia. Checks: config OK; test_d120 6 passed; -k ruido|regional|limpieza|exploracion 160 passed. 18 records → no_es_panama (14 Trump copies + BID Miami, Latin America FDI, Central America Trade Squeeze, Centroamérica ranking, Gilinski/Ecopetrol); El Niño 0/20 affected; Panamanian outlets unchanged. Useful news 117 → 99.

## Re-measurement 2026-10-08 (labels consolidated with the Trump relabel; D-119 + D-120)
- Official `eval.clasificacion` e5/A macro-F1: 0.430 (n=64, IC95 0.28–0.54) → **0.492** (n=46, IC95 0.31–0.62).
- Topic per headline: 35/59 (59 %) → **35/46 (76 %, IC95 62–86 %)**, macro-F1 0.574; per event 15/24 (63 %, IC95 43–79 %).
- Noise vs human: 92/100 (IC95 85–96 %): 4 leaks (Barcelona DJ, electoral reform, tree at hospital, RSE week) + 4 false noise from D-120 (BID Miami, LatAm FDI, Central America Trade Squeeze, Centroamérica ranking — human labeled them economía regional).
- Score ranges (72 groups): alto 52, medio 20, bajo 0.

## Next (2026-10-09)
1. User decision: the 4 generic regional notes hit by D-120 — keep human label (economía regional, then D-120 needs tuning) or relabel no_es_panama.
2. User reviews the 47 new headlines in `poetry run streamlit run eval/etiquetar.py` → "Qué titulares ver" = tvn_20261008 (Claude proposals prefilled); then `eval.etiquetar --validar` and `--consolidar --forzar`.
3. Economía vocabulary in temas.yaml (main remaining topic error), validated on the 47 new labels (no eval leakage).
4. Full `poetry run pytest -v` once, then commit by work unit (D-119; labeling extension; D-120 + relabel) and PR per repo flow. Nothing of T2–T7 is committed yet.
5. Exploratory scripts persisted in odd/scripts/ (juez_deepseek.py, comparar_vs_humano.py, proponer_etiquetas.py).

## Acceptance
- `poetry run pytest -v` passes.
- R is no longer near-constant; the "bajo"/"medio"/"alto" split is reported with n and 95 % CI.
- DeepSeek agreement reported with n, labeled as exploratory LLM judgment.

## Progress / evidence
- Baseline (new data, old R, `--sin-llm`): 79 groups; alto 55 (IC95 0.59–0.79), medio 24, bajo 0. R mean 0.94, N 0.998 (near-constant).
- DeepSeek blind baseline (exploratory LLM, D-101): Spearman 0.219, range agreement 24/79, top-10 overlap 1, top-5 overlap 0. Our top is driven by U (sports pilot, Christmas festival, Middle East statement); DeepSeek's top: Canal budget law, copper mine, fuel price formula.
- T2 done (writer): config + `pertenencia_de` in src/puntaje.py + PertenenciaTematica model + 13 tests + parametros. Checks: src.config --validar OK (33); test_d119 13 passed; -k puntaje|prioridad|d103|relevancia|ficha|interfaz|sensibilidad 644 passed, 3 skipped. Full suite deferred to pre-commit (user request). Gap: modality yamls have no topic list → 6 topics of temas.yaml for all modalities (documented).
- T3 done: after D-119 (`--sin-llm`): alto 52 (IC95 0.55–0.75), medio 26, bajo 1. R mean 0.906 (sd 0.218). Only 4 groups changed (−21: Tu Cara Me Suena, sports pilot, Middle East statement; −10.5 German Trump note): the classifier gives a topic to almost every non-noise headline.
- T4 done: judge stability (DeepSeek run1 vs run2) Spearman 0.887. Against the averaged judge: before 0.233 → after 0.362; paired bootstrap diff IC95 [0.000, 0.293] (n=79, 2000 resamples): improvement not strictly demonstrated (lower bound touches 0). Remaining disagreements are by design: Canal budget law and copper mine have U=0.14 (≈6 days old; PDF U = time available to review), DeepSeek ignores recency; mine I=0.4 because classifier says servicios_publicos.
- T5 done (writer, uncommitted): original 100 frozen in eval/muestra_original.csv (seed replay over original strata reproduces exactly the 100 labeled IDs; a date cutoff did not, since es_ruido was recomputed); extension `tvn_20261008` (47, stratum ampliacion_tvn_20261008, weight 1.0, census); LLM prefill banner in eval/etiquetar.py, nothing saved without "Guardar y seguir"; docs/etiquetado.md + parametros. Checks: src.config --validar OK; test_etiquetado_ampliacion 15 passed; -k etiquet|exploracion|ruido|clasificacion 332 passed; --muestra n=147; --validar OK (parent spot check repeated: OK, 15 passed). Pending: human review of the 47 (user).
- Exploratory (scratchpad comparar_vs_humano.py): vs human labels, noise pipeline 95/100 vs DeepSeek 79/100; topic 35/59 vs 34/59 (macro-F1 diff IC95 [−0.21, 0.13], tie). 13 of 24 topic errors are one syndicated event (Trump redirects aid, de/cs/ru); without it 35/46; per event 15/25. Open labeling decision for the user: is that event economía regional or no_es_panama?
