import { useEffect, useRef, type ReactNode } from "react";
import { ArrowDownRight, ArrowUpRight, Inbox, X } from "lucide-react";
import type { Amount } from "./types";

export const money = (value: Amount | null | undefined, digits = 2) =>
  value === null || value === undefined
    ? "—"
    : Number(value).toLocaleString("en-US", {
        style: "currency",
        currency: "USD",
        minimumFractionDigits: digits,
        maximumFractionDigits: digits,
      });
export const number = (value: Amount | null | undefined, digits = 4) =>
  value === null || value === undefined
    ? "—"
    : Number(value).toLocaleString("en-US", { maximumFractionDigits: digits });
export const percent = (value: Amount | null | undefined, digits = 2) =>
  value === null || value === undefined
    ? "—"
    : `${(Number(value) * 100).toFixed(digits)}%`;
export const timestamp = (value: string | null | undefined) =>
  value
    ? new Date(value).toLocaleString("en-US", {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
        timeZone: "UTC",
      }) + " UTC"
    : "Unavailable";
export function Badge({
  children,
  tone = "neutral",
}: {
  children: ReactNode;
  tone?: string;
}) {
  return <span className={`badge ${tone}`}>{children}</span>;
}
export function StatusBadge({ value }: { value: string }) {
  const tone = [
    "BUY",
    "APPROVED",
    "COMPLETED",
    "RECONCILED",
    "AVAILABLE",
  ].includes(value)
    ? "positive"
    : [
          "REJECTED",
          "FAILED",
          "EMERGENCY_STOP",
          "REVERTED",
          "UNAVAILABLE",
          "OFFLINE",
        ].includes(value)
      ? "negative"
      : [
            "RUNNING",
            "REDUCED",
            "FIXTURE",
            "AWAITING_AUTHORIZATION",
            "PAUSED",
            "BLOCKED",
            "STALE",
          ].includes(value)
        ? "accent"
        : "neutral";
  return <Badge tone={tone}>{value.replaceAll("_", " ")}</Badge>;
}
export function Delta({ value }: { value: Amount | null | undefined }) {
  const positive = Number(value) >= 0;
  return (
    <span
      className={
        value == null ? "muted" : positive ? "text-positive" : "text-negative"
      }
    >
      {value != null &&
        (positive ? <ArrowUpRight size={13} /> : <ArrowDownRight size={13} />)}
      {percent(value)}
    </span>
  );
}
export function Coin({ symbol }: { symbol: string }) {
  return (
    <span className={`coin coin-${symbol.toLowerCase()}`}>
      {symbol === "BTC"
        ? "₿"
        : symbol === "ETH"
          ? "Ξ"
          : symbol === "SOL"
            ? "≋"
            : "$"}
    </span>
  );
}
export function Panel({
  title,
  subtitle,
  action,
  children,
  className = "",
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`panel ${className}`}>
      <div className="panel-head">
        <div>
          <h2>{title}</h2>
          {subtitle && <p>{subtitle}</p>}
        </div>
        {action}
      </div>
      {children}
    </section>
  );
}
export function Empty({
  title,
  description,
  action,
}: {
  title: string;
  description: string;
  action?: ReactNode;
}) {
  return (
    <div className="empty">
      <span className="empty-icon">
        <Inbox size={22} />
      </span>
      <h3>{title}</h3>
      <p>{description}</p>
      {action}
    </div>
  );
}
export function Modal({
  title,
  children,
  close,
  wide = false,
}: {
  title: string;
  children: ReactNode;
  close: () => void;
  wide?: boolean;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = ref.current;
    const trigger = document.activeElement;
    dialog?.showModal();
    return () => {
      dialog?.close();
      if (trigger instanceof HTMLElement && trigger.isConnected)
        trigger.focus({ preventScroll: true });
    };
  }, []);
  return (
    <dialog
      ref={ref}
      onCancel={close}
      onClick={(e) => {
        if (e.target === ref.current) close();
      }}
      className={wide ? "modal wide" : "modal"}
      aria-label={title}
    >
      <div className="modal-head">
        <h2>{title}</h2>
        <button
          className="icon-button"
          onClick={close}
          aria-label="Close dialog"
        >
          <X size={19} />
        </button>
      </div>
      <div className="modal-body">{children}</div>
    </dialog>
  );
}
export function JsonDetails({
  data,
  label = "Structured evidence",
}: {
  data: unknown;
  label?: string;
}) {
  return (
    <details className="json-details">
      <summary>{label}</summary>
      <pre>{JSON.stringify(data, null, 2)}</pre>
    </details>
  );
}
