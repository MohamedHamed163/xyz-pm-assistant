# Business Scenario — XYZ Software

## The company

XYZ Software is a 40-person software agency in Cairo that builds custom platforms for clients.
It runs three active projects in parallel. Each project has its own team, its own client, and its
own confidential documents (requirements, architecture, test results, contracts).

## The problem

Project knowledge is spread across dozens of documents. People waste hours searching for answers like
"what is the refund rule?" or "which endpoints need auth?" — and when they do find a document, nobody
is sure whether they were *supposed* to see it. Sharing everything is not an option: contracts contain
pricing, executive reports contain margins, and clients must never see internal QA findings.

## The solution

A centralized **Project Management AI Assistant**. Anyone in the company (and invited clients) can ask
questions in plain language and get answers with citations — but **only from the documents and
sections they are authorized to read**. Permissions are enforced by the backend and the database
*before* retrieval; the AI never receives content the user cannot see.

## Projects

| ID   | Name                | Client                      | Description                          | Status          |
|------|---------------------|-----------------------------|--------------------------------------|-----------------|
| P001 | E-Commerce Platform | Nile Retail Group           | Online shop for a fashion retailer   | Build (Sprint 7)|
| P002 | Droop LMS           | Delta Academy               | Learning platform for universities   | Build (Sprint 4)|
| P003 | Hub Drives          | Hub Drives Mobility LLC     | Peer-to-peer car rental marketplace  | QA / UAT        |

## People

| User    | Role            | Assigned projects | Notes                                         |
|---------|-----------------|-------------------|-----------------------------------------------|
| Hamed   | Project Manager | P001              | No contract access by default                 |
| Sara    | Developer       | P001              |                                               |
| Omar    | QA Engineer     | P001              |                                               |
| Youssef | Developer       | P002              |                                               |
| Mona    | CEO             | All (company-wide)| Sees everything, including executive reports  |
| Amina   | Client          | P001              | Nile Retail Group; shared sections + her contract |
| Khaled  | Finance         | —                 | Access only through explicit document grants  |

## Documents in the demo (12)

| ID                         | Project | Type             | Classification |
|----------------------------|---------|------------------|----------------|
| p001-brd                   | P001    | BRD              | Standard       |
| p001-prd                   | P001    | PRD              | Standard       |
| p001-tech-architecture     | P001    | Technical        | Standard       |
| p001-qa-report             | P001    | QA               | Standard       |
| p001-client-contract       | P001    | Contract         | Restricted     |
| p002-brd                   | P002    | BRD              | Standard       |
| p002-prd                   | P002    | PRD              | Standard       |
| p002-api-docs              | P002    | Technical        | Standard       |
| p003-brd                   | P003    | BRD              | Standard       |
| p003-prd                   | P003    | PRD              | Standard       |
| p003-qa-test-cases         | P003    | QA               | Standard       |
| company-profitability-2026 | —       | Executive report | Restricted     |

`p001-qa-report` was added beyond the original 11 so the "client asks about internal QA issues"
test has real content to block. `p003-qa-test-cases` contains a deliberately planted
prompt-injection string for Stage 5 security testing.

## Acceptance scenarios

| # | User    | Question                                          | Expected |
|---|---------|---------------------------------------------------|----------|
| 1 | Sara    | What is the authentication flow in P001?          | Answered from P001 tech architecture |
| 2 | Sara    | What is the authentication flow in P002?          | Neutral "couldn't find" — no P002 content retrieved |
| 3 | Hamed   | What are the milestones of P001?                  | Answered from P001 BRD §5 |
| 4 | Hamed   | What is the contract payment amount of P001?      | Neutral — no grant on the contract |
| 5 | Mona    | What is the financial performance of all projects?| Answered from the profitability report |
| 6 | Amina   | What is the project delivery timeline?            | Answered from BRD §5 (client-shared) |
| 7 | Amina   | What are the internal QA issues?                  | Neutral — QA docs not available to clients |
