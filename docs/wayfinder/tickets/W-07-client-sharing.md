# W-07 — What exactly may a client see?

**Type:** grilling · **Mode:** HITL · **Blocked by:** W-04 · **Status:** closed 2026-11-26

Documents say "client receives approved summary only", "no client sharing of technical details",
"client contacts listed in CRM may see this proposal", "explicitly shareable extracts". Today a client
reads entire BRDs/PRDs/proposals of their project. Options: per-document `client_shareable`, per-section
"approved for client" (like the old client_shared level), generated approved summaries, per-contact grants.

## Resolution

**Keep it simple** (user direction: "just upload documents by the user authorized, then the user asks questions and gets answers with respect to their permission only").

- No approved extracts, no generated summaries, no per-section "share with client" flag.
- A client reads exactly what the role table ∩ document ceiling (W-04) allows — nothing more.
- A document saying "client receives approved summary only" gives the client **nothing** from that document. If a client version is wanted, the PM uploads it as a normal document the client can read.
- Clients still never get Internal finance or Unclassified (W-03/W-05).
