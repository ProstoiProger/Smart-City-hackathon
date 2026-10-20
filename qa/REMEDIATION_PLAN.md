# RAG remediation contract

Objective: source-grounded 1–3 walking recommendations for Astana, with identity, time, evidence and price-kind constraints. Unit: canonical venue / source record; field evidence has branch or subvenue scope.

Theory: ranking under constraints, not supervised prediction. No model training, CV significance, probability calibration or causal claim is made. Fixed 20-case retrieval regression suite covers RU/KK names, inflections, aliases and categories; API tests cover uncertainty, schedules and graph budgets. This is a product regression suite, not a representative relevance benchmark.

Assumptions: catalogue facts may be stale; listing != physically open; source rating != probability of recommendation success; Wi-Fi != sockets; entry access != full wheelchair route; proximity != entity identity. Unknown facts remain unknown.

Root causes: template/address noise, mixed rubrics, split entity evidence, weak scenario signals and branch/subvenue scope. Fixes: evidence summaries, normalized taxonomy, source-id merge logs, diversity groups with separate facts, typed prices/constraints, source-linked missing-data backlog and public schedule verification.

Verification gates: no invented fields, original records retained, source URLs and dates preserved, alias consistency, duplicate suggestion suppression, named POIs, route budget, map UI, current-weather failure handling, archive secret scan and extracted archive startup.

Remaining externally dependent work is tracked per venue in data/missing_data_backlog.jsonl. No messages or calls to venue operators are authorized or sent.
