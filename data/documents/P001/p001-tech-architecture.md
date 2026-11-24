---
id: p001-tech-architecture
title: E-Commerce Platform — Technical Architecture
project: P001
doc_type: technical
version: "1.4"
owner: Sara (Developer)
date: 2026-09-02
---

# E-Commerce Platform — Technical Architecture

## 1. System Overview

- **Storefront:** Next.js 15 (SSR) deployed on AWS (eu-central-1) behind CloudFront.
- **API:** NestJS modular monolith (modules: auth, catalog, cart, orders, payments, admin).
- **Database:** PostgreSQL 16 (RDS), read replica for catalog queries.
- **Search:** OpenSearch with an Arabic analyzer.
- **Cache/queues:** Redis (sessions, rate limits) + BullMQ for background jobs.
- **Integrations:** Paymob (cards, wallets), Bosta (courier), Odoo ERP (inventory), Twilio (SMS OTP).

## 2. Authentication Flow

1. **Email + password:** passwords hashed with Argon2id. On login the API issues a **15-minute JWT access
   token** and a **7-day rotating refresh token**.
2. **Google sign-in:** OAuth 2.0 Authorization Code flow with PKCE. If the Google email matches an
   existing verified account, the accounts are linked; otherwise a new customer is created.
3. **Token storage:** both tokens are stored in `httpOnly`, `Secure`, `SameSite=Lax` cookies — never in
   localStorage.
4. **Refresh rotation:** each refresh issues a new refresh token and revokes the old one. Reusing a
   revoked refresh token revokes the whole token family (theft detection).
5. **Guest checkout:** phone OTP via Twilio Verify; a verified guest gets a short-lived (2-hour)
   checkout-scoped token.
6. **Admin back office:** separate login with mandatory TOTP 2FA; admin tokens expire after 30 minutes
   of inactivity.

## 3. Database Schema (core tables)

```
customers(id, email, phone, password_hash, google_sub, created_at)
products(id, sku, name_en, name_ar, category_id, base_price, is_active)
product_variants(id, product_id, size, colour, sku, price_override)
inventory(variant_id, location_id, qty_available, updated_at)
carts(id, customer_id NULL, guest_token NULL, updated_at)
orders(id, customer_id, status, payment_method, total, vat, created_at)
order_items(order_id, variant_id, qty, unit_price)
payments(id, order_id, provider, provider_ref, status, amount_captured)
refunds(id, payment_id, amount, reason, status)
```

## 4. Key Technical Decisions

- **ADR-007:** Modular monolith over microservices — team of 6, one deployable keeps ops simple.
- **ADR-011:** Inventory sync is pull-based every 15 minutes from Odoo, with a nightly full reconciliation,
  because Odoo webhooks are unreliable on NRG's version.
- **ADR-014:** Order totals are computed server-side only; the client total is display-only.

## 5. API Conventions

- REST, JSON, versioned under `/api/v1`.
- Idempotency keys required on `POST /orders` and `POST /payments`.
- Rate limits: 10 login attempts per IP per 10 minutes; 3 OTP requests per phone per hour.
