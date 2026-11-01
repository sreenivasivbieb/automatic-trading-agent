import type { Page } from "../types";
import type { AegisView } from "./types";

export type Workspace = "aegis" | "research" | "platform";
export type Route = { workspace: Workspace; page: Page };
export const AEGIS_VIEWS: AegisView[] = [
  "overview",
  "desk",
  "markets",
  "strategies",
  "positions",
  "executions",
  "observatory",
  "risk",
  "wallet",
  "settings",
];
const RESEARCH_VIEWS: Page[] = [
  "overview",
  "desk",
  "markets",
  "news",
  "strategies",
  "positions",
  "executions",
  "observatory",
  "risk",
  "wallet",
  "settings",
];

export function readRoute(): Route {
  if (import.meta.env.VITE_KRONO_PLATFORM === "true")
    return { workspace: "platform", page: "platform" };
  const path = window.location.hash.replace(/^#\/?/, "").split("?")[0];
  if (path === "platform") return { workspace: "platform", page: "platform" };
  if (path === "aegis") return { workspace: "aegis", page: "overview" };
  if (path.startsWith("aegis/")) {
    const view = path.slice(6) as AegisView;
    return {
      workspace: "aegis",
      page: AEGIS_VIEWS.includes(view) ? view : "overview",
    };
  }
  return {
    workspace: "research",
    page: RESEARCH_VIEWS.includes(path as Page) ? (path as Page) : "overview",
  };
}

export function routeHash(
  workspace: Workspace,
  page: Page = "overview",
): string {
  return workspace === "platform"
    ? "/platform"
    : workspace === "aegis"
      ? page === "overview"
        ? "/aegis"
        : `/aegis/${page}`
      : `/${page}`;
}
