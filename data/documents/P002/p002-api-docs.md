---
id: p002-api-docs
title: Droop LMS — API Documentation
project: P002
doc_type: technical
version: "0.9"
owner: Youssef (Developer)
date: 2026-10-27
---

# Droop LMS — API Documentation

## 1. Overview

Base URL: `https://api.droop.academy/v2`. JSON over HTTPS. Every request is scoped to a tenant
(university) resolved from the `X-Droop-Tenant` header or the request host. Backend: Django 5 + Django
REST Framework, PostgreSQL with schema-per-tenant.

## 2. Authentication Flow

1. **University SSO:** SAML 2.0 via the university's IdP (most partners run **Shibboleth**; one runs
   Azure AD). Droop is the Service Provider; assertions are validated against the tenant's stored IdP
   metadata and certificate.
2. **Magic link:** for learners without a university account, `POST /auth/magic-link` emails a single-use
   link valid for 20 minutes.
3. **Session:** after SSO or magic link, the API issues an opaque session token (not a JWT) stored
   server-side in Redis with a 12-hour sliding expiry.
4. **Service integrations:** university SIS systems call the API with per-tenant API keys
   (`Authorization: Api-Key <key>`), rotated every 90 days.

## 3. Endpoints

| Method | Path | Description | Roles |
|--------|------|-------------|-------|
| GET | `/courses` | List courses in the tenant | any |
| POST | `/courses` | Create a course | instructor, uni_admin |
| GET | `/courses/{id}/lessons` | List lessons | enrolled learner, instructor |
| POST | `/quizzes/{id}/attempts` | Start a quiz attempt | learner |
| POST | `/attempts/{id}/submit` | Submit answers | learner |
| GET | `/gradebook/{course_id}` | Gradebook | instructor, uni_admin |
| GET | `/gradebook/{course_id}/export` | CSV export | uni_admin |
| POST | `/auth/magic-link` | Send magic link | public |

## 4. Errors

Standard error body: `{"error": {"code": "QUIZ_CLOSED", "message": "..."}}`. Rate limit: 600 requests
per minute per tenant; 5 magic-link requests per email per hour.
