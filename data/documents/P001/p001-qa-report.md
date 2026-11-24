---
id: p001-qa-report
title: E-Commerce Platform — Sprint 7 QA Report
project: P001
doc_type: qa
version: "1.0"
owner: Omar (QA Engineer)
date: 2026-11-18
---

# E-Commerce Platform — Sprint 7 QA Report

## 1. Summary

Sprint 7 covered card payments (Paymob), partial refunds and the admin promotions screen.
212 test cases executed: 196 passed, 11 failed, 5 blocked. Regression suite pass rate: 94.3%.

## 2. Open Defects

| ID | Severity | Title | Status |
|----|----------|-------|--------|
| BUG-412 | Critical | Partial refund can exceed captured amount when two admins refund at the same time (race condition) | Open — fix in progress |
| BUG-418 | High | Promo code stacking: applying a code, removing it, then applying another leaves the first discount active | Open |
| BUG-421 | High | Arabic search returns no results for words with "ة" vs "ه" spelling variants | Open |
| BUG-427 | Medium | Order confirmation SMS sent twice when Paymob callback retries | In review |
| BUG-430 | Low | Wishlist icon misaligned in RTL layout on iPhone SE | Open |

## 3. Blocked Tests

- 5 wallet-payment tests blocked: Paymob sandbox returned HTTP 502 for 3 days (vendor incident).

## 4. Regression Results

| Area | Cases | Pass | Fail |
|------|-------|------|------|
| Auth | 34 | 34 | 0 |
| Catalog & search | 41 | 38 | 3 |
| Cart & checkout | 52 | 49 | 3 |
| Payments & refunds | 47 | 42 | 5 |
| Admin | 38 | 33 | 0 (5 blocked) |

## 5. QA Recommendation

Do **not** promote Sprint 7 to UAT until BUG-412 and BUG-418 are fixed and re-tested. Internal note:
BUG-412 could cause real money loss for NRG; do not mention it to the client until the fix is verified.
