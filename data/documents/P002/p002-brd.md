---
id: p002-brd
title: Droop LMS — Business Requirements Document
project: P002
doc_type: brd
version: "1.1"
owner: XYZ Project Management Office
date: 2026-08-04
---

# Droop LMS — Business Requirements Document

## 1. Purpose <!-- visibility: client_shared -->

Delta Academy runs accredited online courses for 6 partner universities in Egypt and Saudi Arabia.
Their current LMS (a self-hosted Moodle) is slow, hard to brand per university and has no mobile
experience. Droop LMS replaces it with a multi-tenant learning platform where each university gets its
own branded portal.

## 2. Business Objectives <!-- visibility: client_shared -->

- BO-1: Migrate all 6 universities and 38,000 active learners by September 2027.
- BO-2: Course completion rate up from 41% to 55%.
- BO-3: Onboard a new university portal in under 5 working days.
- BO-4: Reduce support tickets about login problems by 60%.

## 3. Scope <!-- visibility: client_shared -->

In scope: university portals, course builder, video lessons, quizzes, assignments with plagiarism check,
gradebook, certificates, single sign-on with university identity providers, learner mobile web.
Out of scope: live virtual classrooms (integrated via Zoom links only), payments.

## 4. Delivery Milestones <!-- visibility: client_shared -->

| Milestone | Target date |
|-----------|-------------|
| Platform core + first university pilot (Cairo Tech University) | 2027-01-15 |
| Assessments, gradebook, certificates | 2027-04-30 |
| Migration of remaining 5 universities | 2027-08-31 |

## 5. Internal Risks

- Two partner universities still use on-premise Active Directory without SAML; we may need an LDAP bridge.
- Video hosting cost is above the client's budget assumption by about 30%.
