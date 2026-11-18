// Renders LLM-written Markdown (reports, chat replies, RAG answers) SAFELY.
//
// LLM output is UNTRUSTED: it can repeat text from a malicious web page, e.g.
// <img src=x onerror="steal()"> or [click](javascript:steal()). react-markdown is safe
// by default: raw HTML is shown as text (we deliberately do NOT add rehype-raw), and
// dangerous link protocols like javascript: are removed.
// Never use dangerouslySetInnerHTML for model output.

import ReactMarkdown from "react-markdown";

function ExternalLink({ href, children }) {
  // noopener: the opened page can't control this tab (window.opener).
  // noreferrer: it doesn't learn which run page linked to it.
  return (
    <a href={href} target="_blank" rel="noopener noreferrer">
      {children}
    </a>
  );
}

export default function Markdown({ children }) {
  return (
    <div className="markdown">
      <ReactMarkdown components={{ a: ExternalLink }}>{children || ""}</ReactMarkdown>
    </div>
  );
}
