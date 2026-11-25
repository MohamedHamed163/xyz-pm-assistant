---
id: droob-brd
title: Droob AI — Business Requirements Document
project: P001
doc_type: brd
version: "1.0"
---
# Business Requirements Document (BRD)

Version 1.0 · Status: Draft · Project: Droob AI · Target release: MVP (DBRD-DET)

## 1. Executive Summary

Droob AI is an AI learning assistant: students upload course PDFs, ask questions in natural language and get answers grounded in their own material (DBRD-CTX).

## 2. Business Background

Students spend hours searching lecture notes and textbooks; generic AI tools don't stay focused on their course material.

## 3. Business Problem

- Manual search through long PDFs is slow.
- Answers from generic AI may not match the course material.
- Students can't easily verify AI answers against the source.

## 4. Business Goals & Objectives

- Improve students' efficiency when reviewing course material (DBRD-GOAL).
- Build trust in AI answers with source references.
- Validate demand before investing in broader features.

## 5. Stakeholders

| Stakeholder | Responsibility |
|---|---|
| Business Owner | Approves business scope (DBRD-GOV) |
| QA Team | Validates quality and business requirements |

## 6. Target Users

Students who study from PDF lecture notes, textbooks and course packs.

## 7. Proposed Business Solution

A web assistant where students upload PDFs, ask questions and see the source pages behind each answer.

## 8. Business Scope

Included: registration, PDF upload, indexing, document chat, source references. Excluded: voice, video, quizzes, mobile apps.

## 9. Business Requirements

| ID | Requirement |
|---|---|
| BR-01 | Students can upload educational PDFs (DBRD-REQ) |
| BR-06 | Documents are protected from unauthorized access |

## 10. Business Process / High-Level User Journey

1. Student logs in and uploads a course document.
2. The platform processes it and the student asks questions.

## 11. Business Rules

- Only authenticated users can access their workspace (DBRD-RULE).
- A document must be processed before it can be used in chat.
- If the document lacks the information, the product says so clearly.

## 12. Assumptions

- The first release supports PDF files only (DBRD-PLAN).

## 13. Constraints

- MVP scope and delivery time are limited.
- Pilot budget ceiling: USD 3,000 for development (DBRD-COM).

## 14. Business Risks

| Risk | Mitigation |
|---|---|
| Incorrect AI answers | Ground answers in source content (DBRD-RISK) |

## 15. Success Criteria & Business KPIs

- At least 95% of documents processed successfully.

## 16. Implementation Considerations

- Text chunking, embeddings and vector retrieval.

## 17. Business Acceptance / Sign-Off

The business owner approves the pilot release once QA has passed.

## 18. Future Business Opportunities

Quizzes, flashcards, multi-document chat and a mobile app.
