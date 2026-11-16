import { useState } from "react";

/** Shows a link that cannot be retrieved again, with a copy button. */
export function OneTimeLink({ label, link }: { label: string; link: string }) {
  const [copied, setCopied] = useState<"no" | "yes" | "failed">("no");

  async function copy() {
    try {
      await navigator.clipboard.writeText(link);
      setCopied("yes");
    } catch {
      setCopied("failed");
    }
  }

  return (
    <div className="notice" role="status">
      <p>
        {label} No email is sent. Copy this link and send it yourself. It is
        shown only once.
      </p>
      <input
        readOnly
        aria-label="One-time link"
        value={link}
        onFocus={(e) => e.target.select()}
      />
      <button type="button" onClick={copy}>
        {copied === "yes" ? "Copied" : "Copy link"}
      </button>
      {copied === "failed" && (
        <p role="alert">Could not copy. Select the link and copy it.</p>
      )}
    </div>
  );
}
