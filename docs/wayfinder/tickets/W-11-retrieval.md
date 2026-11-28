# W-11 — Which retrieval changes earn their place on the baseline?

**Type:** grilling · **Mode:** HITL · **Blocked by:** W-01 · **Status:** open

Candidates: hybrid keyword (Postgres full-text) + vector for IDs like BR-02/US-03; reranking;
standalone-question rewrite for follow-ups (permission filter applied after rewrite, never by it).
Keep only changes that move W-01 metrics with unauthorized-retrieval rate still 0.
