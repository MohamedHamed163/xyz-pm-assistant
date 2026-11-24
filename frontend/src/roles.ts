export const ROLE_LABEL: Record<string, string> = {
  pm: "Project Manager",
  developer: "Developer",
  qa: "QA Engineer",
  ceo: "CEO",
  client: "Client",
  finance: "Finance",
};

// Questions from the acceptance scenarios, so a demo viewer sees both answers and refusals.
export const SUGGESTIONS: Record<string, string[]> = {
  developer: [
    "What is the authentication flow in P001?",
    "What is the authentication flow in P002?",
    "Which API rate limits apply to login?",
  ],
  pm: [
    "What are the milestones of P001?",
    "What is the contract payment amount of P001?",
    "What are the open critical bugs?",
  ],
  qa: ["What are the open critical bugs?", "What were the regression results?", "What is the Hub Drives booking flow?"],
  ceo: [
    "What is the financial performance of all projects?",
    "What are the portfolio risks?",
    "What is the payment schedule in the P001 contract?",
  ],
  client: ["What are the delivery milestones?", "What are the internal QA issues?", "What are the payment terms?"],
  finance: ["What is the payment schedule in the P001 contract?", "What is the company gross margin?"],
};
