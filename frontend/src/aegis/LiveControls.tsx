import { useEffect, useState } from "react";
import { api } from "../api";
import { Panel, number } from "../ui";
import { useAegis } from "./context";
import type { Change, FieldBounds, Preview } from "./types";
import { inputRange, utcTime } from "./types";

/** Recorded preference versions; restoring one goes through the same preview rules. */
export function SettingsHistory() {
  const { state, act, busy, setPreview, setNotice } = useAegis();
  if (!state?.params_history?.length) return null;
  return (
    <Panel
      title="Settings history"
      subtitle="Restore an earlier version. A restore that affects open positions asks for confirmation first."
    >
      <ul className="aegis-history">
        {state.params_history.map((h) => (
          <li key={h.version} className="inline gap">
            <span>
              v{h.version} · {h.source.replaceAll("_", " ")} ·{" "}
              {h.at ? utcTime(h.at) : "initial"}
            </span>
            {h.version === state.params_version ? (
              <strong>current</strong>
            ) : (
              <button
                className="button secondary"
                disabled={busy}
                aria-label={`Restore settings version ${h.version}`}
                onClick={() =>
                  void act(async () => {
                    const r = await api<{ changes: Change } & Partial<Preview>>(
                      "/aegis/settings/rollback",
                      "POST",
                      {
                        version: h.version,
                        expected_version: state.params_version,
                      },
                    );
                    if (r.kind === "params_change") {
                      setPreview(r as Preview);
                      return;
                    }
                    setNotice(`Restored settings version ${h.version}.`);
                  })
                }
              >
                Restore
              </button>
            )}
          </li>
        ))}
      </ul>
    </Panel>
  );
}

type Selection = {
  config: Record<string, number | string | boolean>;
  version: number;
  bounds: Record<string, FieldBounds>;
};

/** Strategy selector settings, shared with research; saving invalidates library snapshots. */
export function SelectorSettings() {
  const { act, busy, setNotice } = useAegis();
  const [selection, setSelection] = useState<Selection | null>(null);
  const [draft, setDraft] = useState<Selection["config"] | null>(null);
  const reload = async () => {
    const value = await api<Selection>("/selection");
    setSelection(value);
    setDraft(value.config);
  };
  useEffect(() => {
    void reload().catch(() => setSelection(null));
  }, []);
  if (!selection || !draft) return null;
  const numeric = Object.keys(selection.bounds);
  return (
    <Panel
      title="Strategy selector"
      subtitle="Chooses which enabled library strategy may enter each asset. Applies from the next market check."
    >
      <form
        className="aegis-form"
        onSubmit={(e) => {
          e.preventDefault();
          void act(async () => {
            await api("/selection", "PUT", {
              expected_version: selection.version,
              config: draft,
            });
            await reload();
            setNotice(
              `Strategy selector saved: ${draft.enabled ? String(draft.mode) : "off"}.`,
            );
          });
        }}
      >
        <label className="inline gap">
          <input
            type="checkbox"
            aria-label="Strategy selector enabled"
            checked={Boolean(draft.enabled)}
            onChange={(e) => setDraft({ ...draft, enabled: e.target.checked })}
          />
          Rank strategies by market fit (off: every enabled strategy may enter)
        </label>
        <label>
          Mode
          <select
            aria-label="Strategy selector mode"
            value={String(draft.mode)}
            onChange={(e) => setDraft({ ...draft, mode: e.target.value })}
          >
            <option value="dominant">One strategy per asset</option>
            <option value="consensus">All qualifying strategies</option>
          </select>
        </label>
        <details>
          <summary>Weights and switching</summary>
          {numeric.map((key) => (
            <label key={key}>
              {key.replaceAll("_", " ")}
              <input
                aria-label={`Selector ${key.replaceAll("_", " ")}`}
                type="number"
                step="any"
                {...inputRange(selection.bounds[key])}
                value={String(draft[key])}
                onChange={(e) =>
                  setDraft({ ...draft, [key]: Number(e.target.value) })
                }
              />
            </label>
          ))}
        </details>
        <button className="button primary" disabled={busy} type="submit">
          Save selector
        </button>
      </form>
    </Panel>
  );
}

const SCOPE_TEXT = {
  new_entries: "New entries only: open positions keep their current exit rules",
  all: "Open positions too: the new exit rules apply on the next market check",
};

/** Human confirmation of a settings change that affects open positions. */
export function ParamsConfirmation({
  preview,
}: {
  preview: Extract<Preview, { kind: "params_change" }>;
}) {
  const { act, busy, setPreview } = useAegis();
  const { impact } = preview;
  const [scope, setScope] = useState<"new_entries" | "all">("new_entries");
  const [closeRemoved, setCloseRemoved] = useState(false);
  const [trim, setTrim] = useState(false);
  return (
    <>
      <ul>
        {Object.entries(preview.changes).map(([key, value]) => (
          <li key={key}>
            {key.replaceAll("_", " ")}: {JSON.stringify(value.before)} →{" "}
            {JSON.stringify(value.after)}
          </li>
        ))}
      </ul>
      {impact.changed_exit_rules.length > 0 && (
        <fieldset>
          <legend>
            Exit rules for {impact.open_positions} open position(s)
          </legend>
          {(["new_entries", "all"] as const).map((value) => (
            <label key={value} className="inline gap">
              <input
                type="radio"
                name="exit-scope"
                checked={scope === value}
                onChange={() => setScope(value)}
              />
              {SCOPE_TEXT[value]}
            </label>
          ))}
          {impact.immediate_exits.length > 0 && (
            <p className="muted">
              Applying to open positions would close{" "}
              {impact.immediate_exits
                .map((e) => `${e.asset} (${e.trigger.replaceAll("_", " ")})`)
                .join(", ")}{" "}
              on the next check.
            </p>
          )}
        </fieldset>
      )}
      {impact.removed_held_assets.length > 0 && (
        <label className="inline gap">
          <input
            type="checkbox"
            checked={closeRemoved}
            onChange={(e) => setCloseRemoved(e.target.checked)}
          />
          Close positions in {impact.removed_held_assets.join(", ")} (otherwise
          they stay until their stops or targets)
        </label>
      )}
      {impact.oversized_positions.length > 0 && (
        <label className="inline gap">
          <input
            type="checkbox"
            checked={trim}
            onChange={(e) => setTrim(e.target.checked)}
          />
          Trim{" "}
          {impact.oversized_positions
            .map(
              (p) =>
                `${p.asset} from ${number(p.value_usdt, 4)} to ${number(p.target_value_usdt, 4)} USDT`,
            )
            .join(", ")}
        </label>
      )}
      {!impact.valuation_fresh && (
        <p className="muted">
          Marks are not fresh; follow-up exits use fresh quotes when they run.
        </p>
      )}
      <p>
        Preview expires at {utcTime(preview.expires_at)}. Nothing has changed
        yet.
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
              await api("/aegis/settings/confirm", "POST", {
                confirmation: preview.confirmation,
                exit_scope: scope,
                close_removed: closeRemoved,
                trim_to_size: trim,
              });
              setPreview(null);
            }, "Settings change applied.")
          }
        >
          Confirm settings change
        </button>
      </div>
    </>
  );
}
