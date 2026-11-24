---
id: p001-brd
title: E-Commerce Platform — Business Requirements Document
project: P001
doc_type: brd
version: "1.3"
owner: Hamed (Project Manager)
date: 2026-06-12
---

# E-Commerce Platform — Business Requirements Document

## 1. Purpose <!-- visibility: client_shared -->

Nile Retail Group (NRG) sells fashion and accessories through 14 physical stores in Egypt. Online sales
today run through a third-party marketplace that takes an 18% commission and gives NRG no customer data.
This project delivers NRG's own e-commerce platform ("NRG Online") so the company owns its customers,
pricing and brand experience.

## 2. Business Objectives <!-- visibility: client_shared -->

| # | Objective | Target | Measured by |
|---|-----------|--------|-------------|
| BO-1 | Move online sales off the marketplace | 70% of online revenue via NRG Online within 6 months of launch | Monthly sales report |
| BO-2 | Grow online conversion | ≥ 2.4% session-to-order conversion | Analytics |
| BO-3 | Build a customer base | 50,000 registered customers in year one | User database |
| BO-4 | Reduce cart abandonment | Below 65% | Checkout funnel |
| BO-5 | Support cash-on-delivery and cards | 100% of orders payable by COD, card or wallet | Payment reports |

## 3. Stakeholders <!-- visibility: client_shared -->

| Name / Group | Organization | Interest |
|--------------|--------------|----------|
| Amina Fathy — Head of Digital | NRG | Product owner, signs off milestones |
| NRG Store Operations | NRG | Click-and-collect, inventory sync |
| NRG Finance | NRG | Payments, refunds, reconciliation |
| Hamed — Project Manager | XYZ Software | Delivery, scope, schedule |
| XYZ Engineering & QA | XYZ Software | Build and quality |

## 4. Scope <!-- visibility: client_shared -->

**In scope**
- Customer web storefront (Arabic and English, RTL support) and responsive mobile web.
- Product catalog with variants (size, colour), search and filters.
- Cart, checkout, cash-on-delivery, card payments via Paymob, and mobile wallets.
- Customer accounts, order history, returns requests.
- Admin back office: products, orders, promotions, refunds.
- Inventory sync with NRG's ERP (Odoo) every 15 minutes.

**Out of scope (phase 1)**
- Native iOS/Android apps (phase 2).
- Loyalty points programme.
- Marketplace for third-party sellers.

## 5. Delivery Milestones <!-- visibility: client_shared -->

| Milestone | Description | Target date | Status |
|-----------|-------------|-------------|--------|
| M1 | Discovery & BRD sign-off | 2026-06-30 | Done |
| M2 | Design system & storefront UI approved | 2026-08-15 | Done |
| M3 | Catalog, cart and checkout (COD) on staging | 2026-10-31 | Done |
| M4 | Card & wallet payments, admin back office | 2026-12-20 | In progress |
| M5 | ERP inventory sync + UAT | 2027-01-31 | Planned |
| M6 | Go-live (NRG Online public launch) | 2027-02-15 | Planned |

Post-launch hypercare runs for 30 days after M6.

## 6. Business Rules <!-- visibility: client_shared -->

- BR-1: Orders above EGP 25,000 require card or wallet payment (no COD).
- BR-2: Returns are accepted within 14 days of delivery for unworn items with tags.
- BR-3: Refunds go back to the original payment method within 7 business days; COD orders are refunded
  to a wallet or bank account.
- BR-4: Prices shown include 14% VAT.

## 7. Internal Delivery Risks

*Internal — not for client distribution.*

- R-1: NRG's Odoo instance is on an old version with an undocumented API. Integration estimate carries
  ±40% uncertainty. We may need to bill the ERP connector as a change request.
- R-2: Paymob sandbox has been unstable; card payments (M4) are at risk of slipping 1–2 weeks.
- R-3: Amina's team takes on average 9 working days to approve designs; the plan assumed 5.
- R-4: Internal codename for the margin-protection plan if M5 slips: **"Project Papyrus"**.
