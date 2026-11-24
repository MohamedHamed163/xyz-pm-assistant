---
id: p001-prd
title: E-Commerce Platform — Product Requirements Document
project: P001
doc_type: prd
version: "2.1"
owner: Hamed (Project Manager)
date: 2026-07-20
---

# E-Commerce Platform — Product Requirements Document

## 1. Product Overview <!-- visibility: client_shared -->

NRG Online is a bilingual (Arabic/English) storefront with a back office for NRG staff. Primary users are
shoppers in Egypt on mobile devices (78% of current marketplace traffic is mobile).

## 2. Personas <!-- visibility: client_shared -->

- **Nour, the shopper** — 27, shops on her phone in the evening, prefers cash on delivery, wants easy returns.
- **Karim, the store manager** — prepares click-and-collect orders and needs a clear pick list.
- **Dina, the e-commerce admin** — manages products, promotions and refunds.

## 3. Key User Flows <!-- visibility: client_shared -->

**Checkout flow**
1. Shopper reviews cart → enters or selects a saved address.
2. Chooses delivery (home delivery 2–4 days, or click-and-collect from a store).
3. Chooses payment: COD, card (Paymob hosted page), or mobile wallet.
4. Confirms order → receives SMS + email confirmation with order number.

**Returns flow**
1. Shopper opens order history → "Request return" on an eligible item (within 14 days).
2. Selects reason and pickup slot.
3. After courier pickup and warehouse inspection, refund is issued per BR-3.

## 4. Functional Requirements <!-- visibility: client_shared -->

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-01 | Customers register with email + password or "Continue with Google" | Must |
| FR-02 | Guest checkout with phone number verification by OTP | Must |
| FR-03 | Product search with Arabic stemming and typo tolerance | Must |
| FR-04 | Filters: size, colour, price, category, in-stock-at-store | Must |
| FR-05 | Cart persists across devices for logged-in users | Should |
| FR-06 | Promo codes: percentage, fixed amount, free shipping | Must |
| FR-07 | Admin can issue full or partial refunds | Must |
| FR-08 | Wishlist | Could |

## 5. Acceptance Criteria

*Internal working detail for engineering and QA.*

- AC-FR-01: Registration rejects passwords under 10 characters; Google sign-in links to an existing
  account when the email matches and is verified.
- AC-FR-02: OTP expires after 5 minutes; max 3 attempts, then a 15-minute cooldown.
- AC-FR-03: Searching "فستان" and "fustan" both return dresses; "jens" returns jeans.
- AC-FR-06: Only one promo code per order; promo codes cannot reduce the total below EGP 0.
- AC-FR-07: Partial refund total can never exceed the captured payment amount.

## 6. Non-Functional Requirements

- Storefront Largest Contentful Paint < 2.5 s on a mid-range Android over 4G.
- 99.5% monthly availability.
- Handle 300 orders/minute during campaign peaks (White Friday).
- Card data never touches XYZ servers (Paymob hosted fields; PCI-DSS SAQ-A).
