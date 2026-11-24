import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import type { Citation, Message } from "./api";

// Markdown is rendered WITHOUT raw HTML (react-markdown's default), and unsafe URLs such as
// javascript: are stripped, so document text cannot inject markup or scripts into the page.

const CITE = /\[(\d+)\]/g;

export function MessageBody({
  message,
  onOpenSource,
  bare = false,
}: {
  message: Message;
  onOpenSource: (c: Citation) => void;
  bare?: boolean;
}) {
  if (message.role === "user") {
    return (
      <div className="msg user">
        <div className="bubble">{message.content}</div>
      </div>
    );
  }

  const byNumber = new Map(message.citations.map((c) => [c.number, c]));
  // Turn [n] markers into links we render as citation buttons; unknown numbers stay plain text.
  const content = message.content.replace(CITE, (m, n) => (byNumber.has(Number(n)) ? `[${n}](#cite-${n})` : m));

  const components: Components = {
    a({ href, children }) {
      const match = href?.match(/^#cite-(\d+)$/);
      if (match) {
        const c = byNumber.get(Number(match[1]))!;
        return (
          <button className="cite" onClick={() => onOpenSource(c)} title={`${c.document_title} — ${c.heading}`}>
            {match[1]}
          </button>
        );
      }
      // react-markdown blanks unsafe URLs (javascript:, data:, …); show those as plain text.
      if (!href) return <span>{children}</span>;
      return (
        <a href={href} target="_blank" rel="noopener noreferrer">
          {children}
        </a>
      );
    },
  };

  const markdown = (
    <div className="md">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {content}
      </ReactMarkdown>
    </div>
  );
  if (bare) return markdown;

  if (message.outcome === "no_answer") {
    return (
      <div className="msg assistant">
        <div className="bubble notice">
          <span className="notice-icon" aria-hidden>
            i
          </span>
          {message.content}
        </div>
      </div>
    );
  }
  if (message.outcome === "error") {
    return (
      <div className="msg assistant">
        <div className="bubble notice error">{message.content}</div>
      </div>
    );
  }

  return (
    <div className="msg assistant">
      <div className="bubble">
        {markdown}
        {message.citations.length > 0 && (
          <div className="sources">
            <span className="sources-label">Sources</span>
            {message.citations.map((c) => (
              <button key={c.number} className="source-chip" onClick={() => onOpenSource(c)}>
                <span className="source-chip-num">{c.number}</span>
                <span className="source-chip-text">
                  {c.document_title} <span className="muted">· {c.heading}</span>
                </span>
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
