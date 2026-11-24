---
id: p002-prd
title: Droop LMS — Product Requirements Document
project: P002
doc_type: prd
version: "1.4"
owner: XYZ Project Management Office
date: 2026-09-10
---

# Droop LMS — Product Requirements Document

## 1. Personas <!-- visibility: client_shared -->

- **Learner** — university student, mostly on mobile, watches lessons offline on campus Wi-Fi.
- **Instructor** — builds courses, grades assignments, posts announcements.
- **University admin** — manages enrolments, branding and reports for one university.
- **Delta super-admin** — manages all university tenants.

## 2. Key User Flows <!-- visibility: client_shared -->

**Learner sign-in:** the learner opens `<university>.droop.academy`, clicks "Sign in with my university",
and is redirected to the university's identity provider. Learners without a university account (external
short-course learners) receive a one-time magic link by email.

**Course completion:** learner finishes all required lessons and passes the final quiz (≥ 60%) → a
certificate with a QR verification code is generated.

## 3. Functional Requirements <!-- visibility: client_shared -->

| ID | Requirement | Priority |
|----|-------------|----------|
| FR-01 | Per-university branding: logo, colours, custom domain | Must |
| FR-02 | Course builder with sections, video, PDF, quiz, assignment blocks | Must |
| FR-03 | Quiz bank with randomised questions and time limits | Must |
| FR-04 | Assignment upload with plagiarism score (Turnitin) | Should |
| FR-05 | Gradebook export to CSV and to the university SIS | Must |
| FR-06 | Offline video download in the mobile web app | Could |

## 4. Acceptance Criteria

- Quiz timer continues server-side if the learner closes the tab; late submissions are auto-submitted.
- A university admin can never see learners from another university (tenant isolation test required).
