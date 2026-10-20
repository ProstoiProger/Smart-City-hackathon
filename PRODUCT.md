# Astana Walk

Browser-based walking assistant for Astana, built for the Smart City task in the supplied hackathon PDF.
Users specify an activity, starting point and time budget; receive 1–3 places, sources, approximate walking time and an optional itinerary.
Confirmed scope: clustered map, chat, place cards, retrieval, RAG, FastAPI, comparison; Gemini API only (with a deterministic no-model fallback); review-derived attribute evidence from 2GIS.
All 7,570 collected POIs are bundled. Missing venue prices, rules and opening/closure information remain unknown.
No stored user accounts, precise location history or chat logs. Frontend supports Russian and Kazakh navigation; source data and detailed factual responses currently remain primarily Russian.
Visual authority: the functional AFM map/list/chat application. This is a new domain-specific implementation of those patterns; housing/legal/risk logic is excluded.
Audience: hackathon judges and people planning short visits in Astana. Success: a verifiable recommendation and a feasible approximate pedestrian route.
