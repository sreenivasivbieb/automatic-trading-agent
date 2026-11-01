import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { api } from "../api";
import type { AegisState, Preview } from "./types";

type Message = {
  id: number;
  who: "you" | "aegis";
  text: string;
  tool?: string;
  error?: boolean;
  engine?: string;
};
type Context = {
  state: AegisState | null;
  connectionError: string;
  error: string;
  notice: string;
  busy: boolean;
  load: () => Promise<void>;
  act: (work: () => Promise<unknown>, success?: string) => Promise<void>;
  setNotice: (value: string) => void;
  clearError: () => void;
  control: (action: string, acknowledgement?: string) => Promise<unknown>;
  preview: Preview | null;
  setPreview: (value: Preview | null) => void;
  messages: Message[];
  chatOpen: boolean;
  setChatOpen: (value: boolean) => void;
  send: (text: string) => Promise<void>;
  selectedAsset: string;
  setSelectedAsset: (value: string) => void;
  ownerAccount: string;
  setOwnerAccount: (value: string) => void;
};
const AegisContext = createContext<Context | null>(null);

export function AegisProvider({
  active,
  children,
}: {
  active: boolean;
  children: ReactNode;
}) {
  const [state, setState] = useState<AegisState | null>(null);
  const [connectionError, setConnectionError] = useState(""),
    [error, setError] = useState(""),
    [notice, setNotice] = useState("");
  const [pending, setPending] = useState(0),
    [preview, setPreview] = useState<Preview | null>(null);
  const [messages, setMessages] = useState<Message[]>([]),
    [chatOpen, setChatOpen] = useState(false);
  const [selectedAsset, setSelectedAsset] = useState("WHSK"),
    [ownerAccount, setOwnerAccount] = useState("");
  const sequence = useRef(0),
    accepted = useRef(0),
    polling = useRef(false),
    chatPending = useRef(false);
  useEffect(() => {
    if (!active) return;
    const wallet = (
      window as unknown as {
        ethereum?: {
          request: (args: { method: string }) => Promise<unknown>;
          on?: (name: string, fn: (value: unknown) => void) => void;
          removeListener?: (name: string, fn: (value: unknown) => void) => void;
        };
      }
    ).ethereum;
    let alive = true;
    const changed = (value: unknown) => {
      if (!alive) return;
      setOwnerAccount(
        Array.isArray(value) &&
          typeof value[0] === "string" &&
          /^0x[0-9a-fA-F]{40}$/.test(value[0])
          ? value[0]
          : "",
      );
    };
    void wallet
      ?.request({ method: "eth_accounts" })
      .then(changed)
      .catch(() => undefined);
    wallet?.on?.("accountsChanged", changed);
    return () => {
      alive = false;
      wallet?.removeListener?.("accountsChanged", changed);
    };
  }, [active]);
  const load = useCallback(async () => {
    const id = ++sequence.current;
    try {
      const result = await api<AegisState>("/aegis/state");
      if (id >= accepted.current) {
        accepted.current = id;
        setState(result);
        setConnectionError("");
      }
    } catch (e) {
      if (id >= accepted.current) {
        accepted.current = id;
        setConnectionError(
          e instanceof Error ? e.message : "HSKSwap agent is unavailable",
        );
      }
    }
  }, []);
  useEffect(() => {
    if (!active) return;
    const poll = async () => {
      if (polling.current) return;
      polling.current = true;
      try {
        await load();
      } finally {
        polling.current = false;
      }
    };
    void poll();
    const id = setInterval(() => {
      if (document.visibilityState === "visible") void poll();
    }, 3000);
    const focus = () => void poll();
    window.addEventListener("focus", focus);
    return () => {
      clearInterval(id);
      window.removeEventListener("focus", focus);
    };
  }, [active, load]);
  const act = useCallback(
    async (work: () => Promise<unknown>, success?: string) => {
      setPending((n) => n + 1);
      setError("");
      setNotice("");
      try {
        await work();
        if (success) setNotice(success);
      } catch (e) {
        setError(e instanceof Error ? e.message : "Action failed");
      } finally {
        await load();
        setPending((n) => n - 1);
      }
    },
    [load],
  );
  const control = (action: string, acknowledgement?: string) =>
    api("/aegis/control", "POST", { action, acknowledgement });
  const send = async (text: string) => {
    const message = text.trim();
    if (!message || chatPending.current) return;
    chatPending.current = true;
    setMessages((rows) => [
      ...rows,
      { id: Date.now(), who: "you", text: message },
    ]);
    try {
      await act(async () => {
        try {
          const result = await api<{
            response: string;
            tool: string;
            engine?: string;
            data: Preview;
          }>("/aegis/chat", "POST", { message });
          setMessages((rows) => [
            ...rows,
            {
              id: Date.now() + 1,
              who: "aegis",
              text: result.response,
              tool: result.tool,
              engine: result.engine,
            },
          ]);
          if (result.data?.requires_confirmation) {
            setChatOpen(false);
            setPreview(result.data);
          }
        } catch (e) {
          setMessages((rows) => [
            ...rows,
            {
              id: Date.now() + 1,
              who: "aegis",
              text: e instanceof Error ? e.message : "Request refused",
              error: true,
            },
          ]);
          throw e;
        }
      });
    } finally {
      chatPending.current = false;
    }
  };
  return (
    <AegisContext.Provider
      value={{
        state:
          state && connectionError
            ? {
                ...state,
                valuation_fresh: false,
                data_status: "OFFLINE",
                pnl: null,
              }
            : state,
        connectionError,
        error,
        notice,
        busy: pending > 0,
        load,
        act,
        setNotice,
        clearError: () => {
          setError("");
          setNotice("");
        },
        control,
        preview,
        setPreview,
        messages,
        chatOpen,
        setChatOpen,
        send,
        selectedAsset,
        setSelectedAsset,
        ownerAccount,
        setOwnerAccount,
      }}
    >
      {children}
    </AegisContext.Provider>
  );
}

export function useAegis() {
  const value = useContext(AegisContext);
  if (!value)
    throw new Error("AEGIS views require the shared workspace provider");
  return value;
}
