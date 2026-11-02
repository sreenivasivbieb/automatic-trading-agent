import { useEffect, useRef, useState } from "react";
import { Bot, Send, X } from "lucide-react";
import { api } from "../api";
import { Modal } from "../ui";
import { useAegis } from "./context";
import { ParamsConfirmation } from "./LiveControls";
import { utcTime } from "./types";

export function AegisChat() {
  const { messages, busy, send, setChatOpen, state } = useAegis();
  const [message, setMessage] = useState("");
  const bottom = useRef<HTMLDivElement>(null),
    input = useRef<HTMLTextAreaElement>(null);
  useEffect(() => {
    input.current?.focus();
  }, []);
  useEffect(() => {
    bottom.current?.scrollIntoView({ block: "nearest" });
  }, [messages.length]);
  const submit = (text: string) => {
    if (!text.trim() || busy) return;
    setMessage("");
    void send(text);
  };
  return (
    <aside
      className="chat-panel aegis-assistant"
      role="dialog"
      aria-label="AEGIS trading assistant"
    >
      <div className="chat-head">
        <span className="chat-avatar">
          <Bot size={20} />
        </span>
        <div>
          <strong>AEGIS assistant</strong>
          <small>
            {state?.ai_engine?.label ?? "AI Engine: Deterministic Fallback"} ·
            PAPER
          </small>
        </div>
        <button
          className="icon-button right"
          aria-label="Close AEGIS assistant"
          onClick={() => setChatOpen(false)}
        >
          <X size={18} />
        </button>
      </div>
      <div className="chat-messages" aria-live="polite">
        {!messages.length && (
          <div className="chat-message assistant">
            <p>
              Ask about positions, P&L or a trading decision. Adjust sizing,
              frequency, risk appetite and target assets through the same
              controls used by the strategy screen.
            </p>
          </div>
        )}
        {messages.map((m) => (
          <div
            key={m.id}
            className={`chat-message ${m.who === "you" ? "user" : "assistant"}`}
          >
            <span className="eyebrow">{m.who === "you" ? "YOU" : "AEGIS"}</span>
            <p>{m.text}</p>
            {m.tool && <span className="tool-chip">{m.tool}</span>}
            {m.engine && (
              <small className="aegis-chat-engine">{m.engine}</small>
            )}
          </div>
        ))}
        <div ref={bottom} />
      </div>
      <div className="aegis-chips">
        {[
          "Show my open positions and real-time P&L",
          "Set position size to 25 USDT and frequency to 30s",
          "Switch risk appetite to conservative with a 1.5% stop-loss",
          "Focus target assets on WHSK and WETH arbitrage spreads",
        ].map((text) => (
          <button disabled={busy} key={text} onClick={() => submit(text)}>
            {text}
          </button>
        ))}
      </div>
      <form
        className="aegis-composer"
        onSubmit={(e) => {
          e.preventDefault();
          submit(message);
        }}
      >
        <textarea
          ref={input}
          id="aegis-chat-input"
          aria-label="Message AEGIS"
          maxLength={1000}
          rows={2}
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              submit(message);
            }
          }}
          placeholder="Cut position size to 3%…"
        />
        <button
          className="button primary"
          type="submit"
          aria-label="Send to AEGIS"
          disabled={busy || !message.trim()}
        >
          <Send size={16} />
        </button>
      </form>
      <small className="chat-policy">
        Conversation stays in this tab. Typed actions are audited. Closing
        positions requires confirmation.
      </small>
    </aside>
  );
}

export function AegisConfirmations() {
  const { preview, setPreview, busy, act } = useAegis();
  if (!preview) return null;
  if (preview.kind === "params_change")
    return (
      <Modal title="Confirm settings change" close={() => setPreview(null)}>
        <ParamsConfirmation key={preview.confirmation} preview={preview} />
      </Modal>
    );
  return (
    <Modal title="Confirm paper position unwind" close={() => setPreview(null)}>
      <p>
        Close {preview.positions.length} paper position(s) into virtual USDT.
        Entries will pause. Fresh quotes and risk limits apply to each exit.
      </p>
      <p>
        Preview expires at {utcTime(preview.expires_at)}. Changed holdings
        require another preview.
      </p>
      <div className="inline gap">
        <button
          className="button secondary"
          disabled={busy}
          onClick={() => setPreview(null)}
        >
          Cancel
        </button>
        <button
          className="button primary"
          disabled={busy}
          onClick={() =>
            void act(async () => {
              await api("/aegis/control", "POST", {
                action: "close_all_confirm",
                confirmation: preview.confirmation,
              });
              setPreview(null);
              await api("/aegis/check", "POST");
            }, "Confirmed paper unwind requested; entries paused.")
          }
        >
          Confirm paper unwind
        </button>
      </div>
    </Modal>
  );
}
