---
id: p003-prd
title: Hub Drives — Product Requirements Document
project: P003
doc_type: prd
version: "2.3"
owner: XYZ Project Management Office
date: 2026-05-02
---

# Hub Drives — Product Requirements Document

## 1. Key User Flows <!-- visibility: client_shared -->

**Booking flow**
1. Renter searches by city, dates and car type.
2. Opens a listing → sees daily price, deposit, mileage limit (250 km/day) and owner rating.
3. Verifies identity (UAE Pass) on first booking.
4. Pays the rental + refundable deposit (AED 1,000 hold on card).
5. Owner accepts within 2 hours, or the booking auto-cancels with a full refund.

**Trip check-out / check-in**
- Both parties take at least 8 photos at handover; photos are timestamped and geotagged.
- Fuel level and odometer are recorded at both ends.

## 2. Functional Requirements <!-- visibility: client_shared -->

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-01 | Owner sets daily price, availability calendar and instant-book option | Must |
| FR-02 | Renter must be 21+ with a licence held for 1+ year | Must |
| FR-03 | Deposit hold released 48 h after trip end if no claim is opened | Must |
| FR-04 | Damage claim with photo comparison and admin decision | Must |
| FR-05 | Two-way ratings after each trip | Should |

## 3. Pricing Rules

- Commission: 20% of the rental price, charged to the owner.
- Renter service fee: 8%.
- Late return: 1.5× the hourly rate per hour late.
