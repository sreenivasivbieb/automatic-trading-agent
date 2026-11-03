import { useCallback, useEffect, useRef, useState } from "react";
import {
  Activity,
  ArrowRight,
  BookOpen,
  Bot,
  CheckCircle2,
  ChevronDown,
  Command,
  FlaskConical,
  Globe2,
  History,
  LayoutDashboard,
  LoaderCircle,
  Menu,
  MessageSquare,
  Newspaper,
  Radio,
  Search,
  Send,
  Settings2,
  ShieldCheck,
  ShieldOff,
  SlidersHorizontal,
  Wallet,
  X,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { api } from "./api";
import { AegisDesk } from "./AegisDesk";
import { AegisProvider, useAegis } from "./aegis/context";
import { AegisChat, AegisConfirmations } from "./aegis/Chat";
import { AegisSearch } from "./aegis/Search";
import {
  AEGIS_VIEWS,
  readRoute,
  routeHash,
  type Route,
  type Workspace,
} from "./aegis/navigation";
import type { AegisView } from "./aegis/types";
import { KronoBrand, KronoMark } from "./brand";
import { WorkspaceHighlights, WorkspaceSearch } from "./discovery";
import { PlatformWorkspace } from "./platform/Platform";
import { TradingDesk } from "./TradingDesk";
import { platform } from "./platform/client";
import type {
  Dashboard,
  Intent,
  MarketDetail,
  Page,
  Run,
  Status,
} from "./types";
import { ActionFeedbackContext, Panel, StatusBadge } from "./ui";
import {
  Executions,
  Markets,
  NewsWorkspace,
  Observatory,
  Overview,
  PortfolioMetrics,
  Positions,
  RiskWorkspace,
  Settings,
  Strategies,
  WalletWorkspace,
  type WorkspaceProps,
} from "./workspaces";

const NAV: { id: Page; name: string; icon: LucideIcon; group?: string }[] = [
  { id: "overview", name: "Overview", icon: LayoutDashboard },
  { id: "desk", name: "Trading Desk", icon: Activity },
  { id: "platform", name: "Agent Platform", icon: Bot },
  { id: "aegis", name: "AEGIS · HSKSwap", icon: ShieldCheck },
  { id: "markets", name: "Markets", icon: Activity },
  { id: "news", name: "News Intelligence", icon: Newspaper },
  { id: "strategies", name: "Strategies", icon: SlidersHorizontal },
  { id: "positions", name: "Positions", icon: BookOpen, group: "EXECUTION" },
  { id: "executions", name: "Execution History", icon: History },
  {
    id: "observatory",
    name: "Agent Observatory",
    icon: Radio,
    group: "CONTROL",
  },
  { id: "risk", name: "Risk Controls", icon: ShieldCheck },
  { id: "wallet", name: "Wallet", icon: Wallet },
  { id: "settings", name: "Settings", icon: Settings2 },
];
const CLOUD_PLATFORM = import.meta.env.VITE_KRONO_PLATFORM === "true";
const PRIMARY_PAGES: Page[] = [
  "overview",
  "desk",
  "strategies",
  "positions",
  "risk",
  "settings",
];
const focusPlatform = () =>
  document
    .querySelector<HTMLTextAreaElement>(".platform-composer textarea")
    ?.focus();
const TITLES: Record<Page, [string, string]> = {
  aegis: [
    "AEGIS on HSKSwap",
    "Verified pool data, autonomous paper trading and bounded human control.",
  ],
  platform: [
    "Agent platform",
    "Create, deploy and operate your agents through a private AWS workspace.",
  ],
  desk: [
    "Trading desk",
    "Price action, risk-aware tickets and recorded execution in one workstation.",
  ],
  overview: [
    "Command center",
    "Your market, research and execution — in one auditable workspace.",
  ],
  markets: [
    "Market intelligence",
    "Measured price action. Transparent indicators. Verified provenance.",
  ],
  news: [
    "News intelligence",
    "Follow the story. Inspect the evidence. Understand what is missing.",
  ],
  strategies: [
    "Strategy lab",
    "Deterministic signals, explicit assumptions and controlled parameters.",
  ],
  positions: [
    "Positions & portfolio",
    "Owned inventory, marked exposure and a consistent simulation ledger.",
  ],
  executions: [
    "Execution terminal",
    "From candidate to risk approval, authorization and reconciliation.",
  ],
  observatory: [
    "Agent observatory",
    "Every stage, every decision, and the evidence behind it.",
  ],
  risk: [
    "Risk controls",
    "Independent enforcement, conservative limits and explicit human control.",
  ],
  wallet: [
    "Wallet & network",
    "Read-only inspection. Your signing keys stay with you.",
  ],
  settings: [
    "Workspace settings",
    "Providers, autonomous operation and the persistent audit trail.",
  ],
};

const AEGIS_TITLES: Record<AegisView, [string, string]> = {
  overview: [
    "AEGIS on HSKSwap",
    "Market monitoring, on-chain analysis, signals and risk-controlled paper execution.",
  ],
  desk: [
    "HSKSwap trading desk",
    "Observed pool prices, current opportunities and the agent's execution decisions.",
  ],
  markets: [
    "HSKSwap markets",
    "Verified V3 pools and recorded on-chain price observations.",
  ],
  strategies: [
    "HSKSwap strategies",
    "Position sizing, frequency, risk appetite and target assets used by the agent.",
  ],
  positions: [
    "HSKSwap positions & P&L",
    "The active paper ledger, marked exposure and cost-inclusive performance.",
  ],
  executions: [
    "HSKSwap executions",
    "Recorded gateway fills, source quote blocks and modeled costs.",
  ],
  observatory: [
    "HSKSwap decision feed",
    "Signals, risk checks, controls and execution outcomes from the same agent.",
  ],
  risk: [
    "HSKSwap risk controls",
    "Stop-loss, take-profit, exposure limits and emergency controls.",
  ],
  wallet: [
    "Owner wallet & funding",
    "Connect your device wallet and review registered vault funding operations.",
  ],
  settings: [
    "HSKSwap agent settings",
    "Persistent agent preferences bounded by the reviewed trading policy.",
  ],
};

interface ChatMessage {
  id: number;
  role: "user" | "assistant";
  content: string;
  tool?: string;
  error?: boolean;
}

function Chat({
  close,
  act,
}: {
  close: () => void;
  act: WorkspaceProps["act"];
}) {
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: 0,
      role: "assistant",
      content:
        "I can inspect recorded signals, summarize available news, show exposure, lower the equity-per-trade limit, and pause entries. Trade requests always go through the execution preview.",
    },
  ]);
  const [input, setInput] = useState(""),
    [pending, setPending] = useState(false);
  const bottom = useRef<HTMLDivElement>(null);
  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [messages]);
  const send = async (text: string) => {
    if (pending || !text.trim()) return;
    setInput("");
    setPending(true);
    setMessages((v) => [...v, { id: Date.now(), role: "user", content: text }]);
    try {
      await act(async () => {
        try {
          const response = await api<{ response: string; tool: string }>(
            "/chat",
            "POST",
            { message: text },
          );
          setMessages((v) => [
            ...v,
            {
              id: Date.now() + 1,
              role: "assistant",
              content: response.response,
              tool: response.tool,
            },
          ]);
        } catch (error) {
          setMessages((rows) => [
            ...rows,
            {
              id: Date.now() + 1,
              role: "assistant",
              content:
                error instanceof Error
                  ? error.message
                  : "The command could not complete. Check the backend and retry.",
              error: true,
            },
          ]);
          throw error;
        }
      });
    } finally {
      setPending(false);
    }
  };
  return (
    <aside className="chat-panel" role="dialog" aria-label="Trading assistant">
      <div className="chat-head">
        <span className="chat-avatar">
          <KronoMark />
        </span>
        <div>
          <strong>Krono assistant</strong>
          <small>Command mode · no API key required</small>
        </div>
        <button
          className="icon-button right"
          aria-label="Close assistant"
          onClick={close}
        >
          <X size={17} />
        </button>
      </div>
      <div className="chat-messages">
        {messages.map((m) => (
          <div
            className={`chat-message ${m.role}${m.error ? " error" : ""}`}
            key={m.id}
          >
            <span className="eyebrow">
              {m.role === "assistant" ? "KRONO ASSISTANT" : "YOU"}
            </span>
            <p>{m.content}</p>
            {m.tool && (
              <span className="tool-chip">
                <CheckCircle2 size={11} />
                {m.tool}
              </span>
            )}
          </div>
        ))}
        {messages.length === 1 && (
          <div className="chat-prompts">
            {[
              "Analyze BTC using enabled strategies",
              "Show my exposure by token",
              "Lower trade allocation to 0.5% of equity",
              "Explain the last risk decision",
            ].map((q) => (
              <button key={q} onClick={() => void send(q)}>
                {q}
                <ArrowRight size={12} />
              </button>
            ))}
          </div>
        )}
        {pending && (
          <p className="muted inline gap">
            <LoaderCircle size={14} className="spin" />
            Running validated tool…
          </p>
        )}
        <div ref={bottom} />
      </div>
      <form
        className="chat-input"
        onSubmit={(e) => {
          e.preventDefault();
          void send(input);
        }}
      >
        <input
          aria-label="Message assistant"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask about your workspace…"
          maxLength={2000}
        />
        <button
          type="submit"
          aria-label="Send message"
          disabled={pending || !input.trim()}
        >
          <Send size={16} />
        </button>
      </form>
      <small className="chat-policy">
        Command mode uses recorded research data. Free-form AI tool calling is
        available in AEGIS with a configured model provider. Typed actions are
        audited; raw messages stay in this tab.
      </small>
    </aside>
  );
}

export default function App() {
  const [route, setRoute] = useState<Route>(readRoute);
  useEffect(() => {
    const changed = () => setRoute(readRoute());
    window.addEventListener("hashchange", changed);
    return () => window.removeEventListener("hashchange", changed);
  }, []);
  return (
    <AegisProvider active={route.workspace === "aegis"}>
      <AppContent route={route} setRoute={setRoute} />
    </AegisProvider>
  );
}

function AppContent({
  route,
  setRoute,
}: {
  route: Route;
  setRoute: (route: Route) => void;
}) {
  const page = route.page,
    isAegis = route.workspace === "aegis",
    isResearch = route.workspace === "research";
  const aegis = useAegis();
  const [data, setData] = useState<Dashboard | null>(null),
    [status, setStatus] = useState<Status | null>(null),
    [detail, setDetail] = useState<MarketDetail | null>(null),
    [selected, setSelected] = useState("BTC"),
    [busy, setBusy] = useState(false),
    [toast, setToast] = useState<{ text: string; error: boolean } | null>(null),
    [connectionError, setConnectionError] = useState<string | null>(null),
    [chat, setChat] = useState(false),
    [search, setSearch] = useState(false),
    [sidebar, setSidebar] = useState(false),
    [override, setOverride] = useState<Intent | null>(null),
    [account, setAccount] = useState<string | null>(null);
  const fetching = useRef<Promise<void> | null>(null);
  const refreshRequested = useRef(false);
  const switchWorkspace = (workspace: Workspace, next: Page = "overview") => {
    const page = workspace === "platform" ? "platform" : next;
    setRoute({ workspace, page });
    window.location.hash = routeHash(workspace, page);
    setSidebar(false);
    setSearch(false);
    window.scrollTo({ top: 0 });
  };
  const navigate = useCallback(
    (next: Page) => {
      const workspace =
        next === "aegis"
          ? "aegis"
          : next === "platform"
            ? "platform"
            : route.workspace === "aegis"
              ? "aegis"
              : "research";
      const page = next === "aegis" ? "overview" : next;
      setRoute({ workspace, page });
      window.location.hash = routeHash(workspace, page);
      setSidebar(false);
      window.scrollTo({ top: 0 });
    },
    [route.workspace, setRoute],
  );
  const reload = useCallback(
    async (afterMutation = false) => {
      if (!isResearch) return;
      if (afterMutation) refreshRequested.current = true;
      if (fetching.current) return fetching.current;
      const request = (async () => {
        do {
          refreshRequested.current = false;
          try {
            const [dashboard, serverStatus] = await Promise.all([
              api<Dashboard>("/dashboard"),
              api<Status>("/status"),
            ]);
            setData(dashboard);
            setStatus(serverStatus);
            setConnectionError(null);
          } catch (e) {
            setConnectionError(
              e instanceof Error ? e.message : "Backend connection unavailable",
            );
          }
        } while (refreshRequested.current);
      })();
      fetching.current = request;
      try {
        await request;
      } finally {
        fetching.current = null;
      }
    },
    [isResearch],
  );
  useEffect(() => {
    void reload();
    const id = setInterval(
      () => void reload(),
      (status?.providers.refresh?.ticker_seconds ?? 5) * 1000,
    );
    return () => clearInterval(id);
  }, [reload, status?.providers.refresh?.ticker_seconds]);
  useEffect(() => {
    if (!isResearch) return;
    let alive = true;
    void api<MarketDetail>(`/markets/${selected}`)
      .then((m) => {
        if (alive) setDetail(m);
      })
      .catch(() => {
        if (alive) setDetail(null);
      });
    return () => {
      alive = false;
    };
  }, [
    isResearch,
    selected,
    status?.providers.market,
    data?.markets.find((m) => m.asset.symbol === selected)?.price_at,
  ]);
  useEffect(() => {
    const listener = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key === "k") {
        event.preventDefault();
        if (CLOUD_PLATFORM || window.location.hash === "#/platform")
          focusPlatform();
        else if (isAegis) aegis.setChatOpen(!aegis.chatOpen);
        else setChat((v) => !v);
      }
      if (event.key === "Escape") {
        setSidebar(false);
        setChat(false);
        aegis.setChatOpen(false);
        setSearch(false);
      }
      if (
        event.key === "/" &&
        !(
          event.target instanceof HTMLElement &&
          (event.target.isContentEditable ||
            ["INPUT", "SELECT", "TEXTAREA"].includes(event.target.tagName))
        )
      ) {
        event.preventDefault();
        setSearch(true);
      }
    };
    window.addEventListener("keydown", listener);
    return () => window.removeEventListener("keydown", listener);
  }, [isAegis, aegis.chatOpen, aegis.setChatOpen]);
  useEffect(() => {
    if (!toast) return;
    const id = setTimeout(() => setToast(null), toast.error ? 9000 : 4500);
    return () => clearTimeout(id);
  }, [toast]);
  const act = useCallback(
    async (work: () => Promise<unknown>, message?: string) => {
      setBusy(true);
      setToast(null);
      try {
        await work();
        if (message) setToast({ text: message, error: false });
      } catch (e) {
        setToast({
          text:
            e instanceof Error
              ? e.message
              : "The action could not be completed.",
          error: true,
        });
      } finally {
        // Failed actions can still record a run or a rejection. Refresh that evidence too.
        await reload(true);
        setBusy(false);
      }
    },
    [reload],
  );
  const analyze = () => {
    setOverride(null);
    void act(async () => {
      const run = await api<Run>("/runs", "POST", {
        symbol: selected,
        notional: "100",
      });
      if (run.status === "FAILED")
        throw new Error(
          "Analysis recorded a failed stage. Inspect the Observatory for safe error details.",
        );
    }, "Analysis recorded. Review the hypothesis, risk checks and execution preview.");
  };
  const openIntent = (intent: Intent) => {
    setOverride(intent);
    navigate("executions");
  };
  const base =
    data && status
      ? {
          data,
          status,
          selected,
          setSelected,
          navigate,
          act,
          busy,
          analyze,
          openIntent,
        }
      : null;
  const workspacePages = isAegis
    ? NAV.filter((n) => AEGIS_VIEWS.includes(n.id as AegisView))
    : NAV.filter((n) => !CLOUD_PLATFORM || n.id === "platform");
  const navItems = workspacePages.filter(
    (n) => CLOUD_PLATFORM || PRIMARY_PAGES.includes(n.id),
  );
  const nav = workspacePages.find((n) => n.id === page) || workspacePages[0];
  const titles = isAegis ? AEGIS_TITLES[page as AegisView] : TITLES[page];
  const agentActive = isAegis
    ? aegis.state?.available && !aegis.state.paused && !aegis.state.emergency
    : data?.scheduler.state === "RUNNING";
  return (
    <div
      className={`app-shell rail-shell ${isAegis && aegis.chatOpen ? "aegis-chat-open" : ""} ${!isAegis && (page === "overview" || page === "strategies") ? "discovery-page" : ""}`}
    >
      <aside className={`sidebar ${sidebar ? "is-open" : ""}`}>
        <a
          href={`#${routeHash(CLOUD_PLATFORM ? "platform" : "research")}`}
          className="brand"
          aria-label="Krono home"
          onClick={(event) => {
            event.preventDefault();
            switchWorkspace(CLOUD_PLATFORM ? "platform" : "research");
          }}
        >
          <KronoBrand />
        </a>
        <div className="workspace-label">
          <span className="workspace-icon">
            <FlaskConical size={13} />
          </span>
          <div>
            <strong>
              {isAegis
                ? "HSKSwap agent"
                : page === "platform"
                  ? "Agent platform"
                  : "Research desk"}
            </strong>
            <small>
              {isAegis
                ? "Autonomous paper trading"
                : page === "platform"
                  ? "Private AWS workspace"
                  : "Simulation mode"}
            </small>
          </div>
          <ChevronDown size={13} />
        </div>
        {!CLOUD_PLATFORM && (
          <label className="workspace-switcher">
            <span>Execution workspace</span>
            <select
              aria-label="Execution workspace"
              value={route.workspace}
              onChange={(e) => switchWorkspace(e.target.value as Workspace)}
            >
              <option value="aegis">HSKSwap · AEGIS paper</option>
              <option value="research">Research · simulation</option>
              {page === "platform" && (
                <option value="platform">Agent platform · AWS</option>
              )}
            </select>
          </label>
        )}
        <button
          className="sidebar-search"
          onClick={() => {
            setSidebar(false);
            setSearch(true);
          }}
        >
          <Search size={17} />
          Search workspace
        </button>
        <nav aria-label="Main navigation">
          <span className="nav-section">WORKSPACE</span>
          {navItems.map((item) => (
            <div key={item.id}>
              {item.group && <span className="nav-section">{item.group}</span>}
              <button
                className={page === item.id ? "nav-item active" : "nav-item"}
                onClick={() => navigate(item.id)}
                aria-label={item.name}
                title={item.name}
                aria-current={page === item.id ? "page" : undefined}
              >
                <item.icon size={17} />
                <span className="nav-label">{item.name}</span>
                {item.id === "observatory" && (
                  <span className={`nav-dot ${agentActive ? "running" : ""}`} />
                )}
              </button>
            </div>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="sidebar-agent">
            <Radio size={20} className="sidebar-status-icon" />
            <span className={`agent-dot ${agentActive ? "is-running" : ""}`} />
            <div>
              <strong>
                Agent{" "}
                {isAegis
                  ? !aegis.state?.available
                    ? "connecting"
                    : aegis.state.emergency
                      ? "stopped"
                      : aegis.state.paused
                        ? "paused"
                        : "running"
                  : (data?.scheduler.state
                      ?.toLowerCase()
                      .replaceAll("_", " ") ?? "connecting")}
              </strong>
              <small>
                {isAegis
                  ? `${aegis.state?.data_status === "LIVE" ? "Live pool data" : aegis.state?.data_status || "Awaiting data"} · ${aegis.state?.mode === "testnet" ? "TESTNET" : "PAPER"}`
                  : status?.research.enabled
                    ? "Research provider configured"
                    : "LLM research unconfigured"}
              </small>
            </div>
          </div>
        </div>
      </aside>
      {sidebar && (
        <button
          className="sidebar-backdrop"
          onClick={() => setSidebar(false)}
          aria-label="Close navigation"
        />
      )}
      <div className="workspace">
        <header className="topbar">
          <button
            className="icon-button mobile-menu"
            onClick={() => setSidebar(!sidebar)}
            aria-label="Toggle navigation"
            aria-expanded={sidebar}
          >
            <Menu size={19} />
          </button>
          <a
            href={`#${routeHash(CLOUD_PLATFORM ? "platform" : "research")}`}
            className="mobile-brand"
            onClick={(event) => {
              event.preventDefault();
              switchWorkspace(CLOUD_PLATFORM ? "platform" : "research");
            }}
            aria-label="Krono home"
          >
            <KronoMark />
            <span>Krono.</span>
          </a>
          <div className="breadcrumb">
            <span className="muted">Workspace</span>
            <span>/</span>
            <strong>{nav.name}</strong>
          </div>
          <div className="header-controls">
            <button
              className="header-search"
              onClick={() => setSearch(true)}
              aria-label="Search workspace"
            >
              <Search size={18} />
              <span>Search</span>
              <kbd>/</kbd>
            </button>
            {CLOUD_PLATFORM ? (
              <span className="network-pill">
                <Globe2 size={13} />
                <span>AWS workspace</span>
                <span className="muted">Bedrock</span>
              </span>
            ) : (
              <label className="network-pill">
                <span className="network-dot" />
                <Globe2 size={13} />
                <select
                  className="header-workspace"
                  aria-label="Active workspace"
                  title="Switch execution workspace"
                  value={route.workspace}
                  onChange={(e) => switchWorkspace(e.target.value as Workspace)}
                >
                  <option value="aegis">
                    {aegis.state?.mode === "testnet"
                      ? "HSKSwap · 133 · TESTNET"
                      : "HSKSwap · 177 · PAPER"}
                  </option>
                  <option value="research">Research · SIMULATION</option>
                  {page === "platform" && (
                    <option value="platform">Agent platform · AWS</option>
                  )}
                </select>
              </label>
            )}
            <span
              className={`freshness ${isAegis && !aegis.state?.valuation_fresh ? "is-stale" : ""}`}
            >
              <span className="data-dot" />
              {page === "platform"
                ? "TENANT WORKSPACE"
                : isAegis
                  ? `${aegis.state?.data_status === "LIVE" ? "LIVE POOLS" : aegis.state?.data_status || "CONNECTING"}`
                  : status?.providers.market === "fixture"
                    ? "FIXTURE DATA"
                    : "REFERENCE DATA"}
            </span>
            <span className="mode-label">
              <FlaskConical size={12} />
              {isAegis
                ? aegis.state?.mode === "testnet"
                  ? "TESTNET"
                  : "PAPER"
                : "SIMULATION"}
            </span>
            {page !== "platform" &&
              !!(isAegis ? aegis.ownerAccount : account) && (
                <button
                  className="button secondary header-wallet"
                  onClick={() => navigate("wallet")}
                >
                  <Wallet size={13} />
                  {(isAegis ? aegis.ownerAccount : account)
                    ? `${(isAegis ? aegis.ownerAccount : account)!.slice(0, 6)}…${(isAegis ? aegis.ownerAccount : account)!.slice(-4)}`
                    : "Connect wallet"}
                </button>
              )}
            <button
              className="emergency-button"
              onClick={() =>
                isAegis
                  ? void act(async () => {
                      await aegis.control("panic");
                      await aegis.load();
                    }, "AEGIS emergency stop latched; bounded unwind requested.")
                  : void act(
                      () =>
                        page === "platform"
                          ? platform("/emergency-stop", "POST", {})
                          : api("/emergency-stop", "POST"),
                      "Emergency stop latched. New executions are blocked.",
                    )
              }

              aria-label="Emergency stop"
            >
              <ShieldOff size={14} />
              <span>{isAegis ? "PANIC" : "E-stop"}</span>
            </button>
          </div>
        </header>
        <main>
          <section
            className={`workspace-intro ${!isAegis && (page === "overview" || page === "strategies") ? "discovery-intro" : ""}`}
          >
            {!isAegis && (page === "overview" || page === "strategies") && (
              <div className="hero-art" aria-hidden="true">
                <img
                  src="/art/krono-orbit.webp"
                  alt=""
                  fetchPriority="high"
                  width="720"
                  height="720"
                />
              </div>
            )}
            <div className="page-heading">
              <div>
                <div className="eyebrow page-kicker">
                  {page === "overview"
                    ? "KRONO / WORKSPACE 01"
                    : `KRONO / WORKSPACE ${String(NAV.findIndex((n) => n.id === page) + 1).padStart(2, "0")}`}
                </div>
                <h1>{titles[0]}</h1>
                <p>{titles[1]}</p>
              </div>
              <div className="page-actions">
                {page === "platform" && (
                  <button
                    className="button secondary assistant-shortcut"
                    onClick={() =>
                      page === "platform"
                        ? focusPlatform()
                        : isAegis
                          ? aegis.setChatOpen(true)
                          : setChat(true)
                    }
                  >
                    <MessageSquare size={14} />
                    Ask agent
                    <kbd>
                      <Command size={10} />K
                    </kbd>
                  </button>
                )}
                {page !== "platform" && !isAegis && (
                  <>
                    <select
                      aria-label="Analysis asset"
                      value={selected}
                      onChange={(e) => setSelected(e.target.value)}
                    >
                      {["BTC", "ETH", "SOL"].map((s) => (
                        <option key={s}>{s}</option>
                      ))}
                    </select>
                  </>
                )}
              </div>
            </div>
            {data &&
              !isAegis &&
              (page === "overview" || page === "strategies") && (
                <WorkspaceHighlights data={data} page={page} />
              )}
            {data && !isAegis && page === "overview" && (
              <PortfolioMetrics data={data} />
            )}
          </section>
          {connectionError && page !== "platform" && !isAegis && (
            <div className="connection-warning" role="alert">
              Backend connection interrupted: {connectionError}.{" "}
              {data
                ? "Showing the last loaded records; actions require a current backend connection."
                : "Start the backend to load the workspace."}
              <button onClick={() => void reload()}>Retry</button>
            </div>
          )}
          {(isAegis ? aegis.state?.emergency : data?.scheduler.emergency) && (
            <div className="emergency-banner" role="alert">
              <ShieldOff size={18} />
              <strong>EMERGENCY STOP ACTIVE</strong>
              <span>
                {isAegis
                  ? "Entries are blocked. Bounded stable exits require fresh quotes and risk approval."
                  : "New executions are blocked. Positions are held for review."}
              </span>
              <button onClick={() => navigate("risk")}>
                Review incident
                <ArrowRight size={13} />
              </button>
            </div>
          )}
          {page === "settings" && !CLOUD_PLATFORM && (
            <Panel
              title="Workspace setup"
              subtitle="Secondary tools and integrations"
            >
              <div className="aegis-risk">
                <details className="json-details">
                  <summary>More tools and setup</summary>
                  <div className="settings-form">
                    {workspacePages
                      .filter((item) => !PRIMARY_PAGES.includes(item.id))
                      .map((item) => (
                        <a
                          key={item.id}
                          className="text-button"
                          href={`#${routeHash(item.id === "platform" ? "platform" : item.id === "aegis" ? "aegis" : route.workspace, item.id === "aegis" ? "overview" : item.id)}`}
                          onClick={(event) => {
                            event.preventDefault();
                            navigate(item.id);
                          }}
                        >
                          {item.name}
                        </a>
                      ))}
                    {isAegis && (
                      <a
                        className="text-button"
                        href="#/settings"
                        onClick={(event) => {
                          event.preventDefault();
                          switchWorkspace("research", "settings");
                        }}
                      >
                        Data providers
                      </a>
                    )}
                    {isAegis && (
                      <a
                        className="text-button"
                        href="#/platform"
                        onClick={(event) => {
                          event.preventDefault();
                          switchWorkspace("platform");
                        }}
                      >
                        Agent Platform
                      </a>
                    )}
                    <a
                      className="text-button"
                      href="https://github.com/vishal88736/automatic-trading-agent#readme"
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      Documentation
                    </a>
                  </div>
                </details>
              </div>
            </Panel>
          )}
          {page === "platform" ? (
            <PlatformWorkspace />
          ) : isAegis ? (
            <AegisDesk
              view={page as AegisView}
              openResearchStrategies={() =>
                switchWorkspace("research", "strategies")
              }
            />
          ) : base ? (
            <ActionFeedbackContext.Provider value={toast}>
              {(status!.providers.market === "fixture" ||
                status!.providers.news === "fixture") && (
                <div className="simulation-notice">
                  <FlaskConical size={13} />
                  <strong>SIMULATION WORKSPACE</strong>
                  <span>
                    {status!.providers.market === "fixture"
                      ? "Seeded synthetic candles"
                      : "Coinbase reference candles"}{" "}
                    ·{" "}
                    {status!.providers.news === "fixture"
                      ? "synthetic news fixtures"
                      : "hosted news API"}{" "}
                    · no live funds or signing
                  </span>
                  <button onClick={() => navigate("settings")}>
                    Configure sources
                    <ArrowRight size={12} />
                  </button>
                </div>
              )}
              {page === "overview" && <Overview {...base} detail={detail} />}{" "}
              {page === "desk" && <TradingDesk {...base} />}
              {page === "markets" && <Markets {...base} detail={detail} />}{" "}
              {page === "news" && <NewsWorkspace {...base} />}{" "}
              {page === "strategies" && <Strategies {...base} />}{" "}
              {page === "positions" && <Positions {...base} />}{" "}
              {page === "executions" && (
                <Executions
                  {...base}
                  override={override}
                  setOverride={setOverride}
                />
              )}{" "}
              {page === "observatory" && <Observatory {...base} />}{" "}
              {page === "risk" && <RiskWorkspace {...base} />}{" "}
              {page === "wallet" && (
                <WalletWorkspace
                  {...base}
                  account={account}
                  setAccount={setAccount}
                />
              )}{" "}
              {page === "settings" && <Settings {...base} />}
            </ActionFeedbackContext.Provider>
          ) : (
            <div className="initial-loading">
              <KronoMark />
              <LoaderCircle size={22} className="spin" />
              <h2>Opening the trading workspace</h2>
              <p>Loading source-tagged records from the backend.</p>
            </div>
          )}
          <footer className="workspace-footer">
            <span className="inline gap">
              <ShieldCheck size={12} />
              Independent risk enforcement<span>·</span>Human-controlled
              execution
            </span>
            <span>
              KRONO / v0.1 <span className="footer-divider">|</span>{" "}
              <StatusBadge
                value={
                  isAegis
                    ? aegis.state?.mode === "testnet"
                      ? "TESTNET"
                      : "PAPER"
                    : "SIMULATION"
                }
              />
            </span>
          </footer>
        </main>
      </div>
      {!(isAegis ? aegis.chatOpen : chat) && page !== "platform" && (
        <button
          className="chat-launcher"
          onClick={() => (isAegis ? aegis.setChatOpen(true) : setChat(true))}
          aria-label="Open trading assistant"
        >
          <Bot size={19} />
          <span>{isAegis ? "Ask AEGIS" : "Ask Krono"}</span>
          <kbd>⌘ K</kbd>
        </button>
      )}
      {chat && page !== "platform" && !isAegis && (
        <Chat close={() => setChat(false)} act={act} />
      )}{" "}
      {isAegis && aegis.chatOpen && <AegisChat />}
      {isAegis && <AegisConfirmations />}
      {search && isAegis && (
        <AegisSearch
          pages={workspacePages}
          close={() => setSearch(false)}
          navigate={navigate}
        />
      )}
      {search && !isAegis && (
        <WorkspaceSearch
          data={data}
          pages={NAV}
          close={() => setSearch(false)}
          navigate={navigate}
          setSelected={setSelected}
        />
      )}
      {toast && (
        <div
          className={`toast ${toast.error ? "error" : ""}`}
          role={toast.error ? "alert" : "status"}
        >
          {toast.error ? <ShieldOff size={17} /> : <CheckCircle2 size={17} />}
          <span>{toast.text}</span>
          <button
            onClick={() => setToast(null)}
            aria-label="Dismiss notification"
          >
            <X size={14} />
          </button>
        </div>
      )}
    </div>
  );
}
