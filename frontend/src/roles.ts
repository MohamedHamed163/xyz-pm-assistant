export const ROLE_LABEL: Record<string, string> = {
  pm: "Project Manager",
  developer: "Developer",
  qa: "QA Engineer",
  ceo: "CEO",
  client: "Client",
  finance: "Finance Manager",
};

// Suggested questions per role: some are answered, some show how the rules explain a restriction.
export const SUGGESTIONS: Record<string, string[]> = {
  developer: ["What are the business requirements?", "How long will the project take?", "What are the business rules?"],
  qa: ["What are the business rules?", "What are the acceptance criteria for the project?", "How much does Plan 2 cost?"],
  pm: ["Summarise the BRD's business goals", "What are the payment terms?", "Which documents still need review?"],
  ceo: ["Compare the scope of Droob AI and Hub Drives", "What is the total project investment?", "What are the main business risks?"],
  client: ["What is the project timeline?", "What are the payment terms?", "What is in scope for the MVP?"],
  finance: ["What are the payment terms?", "What is the total project investment?", "What are the functional requirements?"],
};
