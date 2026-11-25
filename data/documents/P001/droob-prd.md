---
id: droob-prd
title: Droob AI — Product Requirements Document
project: P001
doc_type: prd
version: "1.0"
---
# Product Requirements Document (PRD)

Product: Droob AI · Version 1.0 · Status: Draft (DPRD-DET)

## 1. Product Overview

Students upload educational documents and chat with them; answers cite source pages (DPRD-OVR).

## 2. Problem Statement

Students struggle to find specific information in long PDFs and lecture notes.

## 3. Product Objectives

- Reduce search time and hallucinations by grounding answers in the documents.

## 4. Target Users

Primary user: a student reviewing or searching course material.

## 5. Scope

In scope for the MVP: login, PDF upload, indexing, AI chat, citations, document management. Out of scope: voice and quizzes (DPRD-SCP).

## 6. Functional Requirements

FR-04 AI Chat: the AI must say when the uploaded material doesn't contain enough information (DPRD-REQ).

FR-05 Source References: answers include page references the user can open.

## 7. User Flow

Log in → upload a PDF → wait for processing → ask a question → open the source.

## 8. User Stories & Acceptance Criteria

US-02: Given a processed document, when the student asks a question, the answer is based on retrieved content.

## 9. Non-Functional Requirements

Answers within 10 seconds; 99.5% monthly availability.

## 10. Success Metrics (KPIs)

Upload-to-first-question conversion of 70% or higher (DPRD-DLV).

## 11. Dependencies

LLM provider, embedding provider, vector database.

## 12. Risks & Mitigation

AI fails to retrieve relevant content — tune retrieval with a test set.

## 13. MVP Release Criteria

Document-level access control verified; QA completed.

## 14. Future Enhancements

Quizzes, flashcards, summaries and study plans.
