import { spawn } from "node:child_process";
import { existsSync } from "node:fs";

const python = ".venv/bin/python";
if (!existsSync(python)) throw new Error("Run uv sync --python 3.12 first.");
if (!process.env.TERMINAL_TEST_RUN && existsSync(".env"))
  process.loadEnvFile(".env");
const args = process.argv.slice(2);
const testnet = args.includes("--testnet");
if (
  testnet &&
  (!args.includes("--i-understand-testnet") ||
    process.env.TERMINAL_TEST_RUN === "1")
)
  throw new Error(
    "Use the explicit local testnet command outside the fixture application.",
  );
if (!testnet && args.length)
  throw new Error("Unknown development launcher arguments.");
const backendArgs = testnet
  ? [
      "-m",
      "scripts.testnet_server",
      ...args.filter((arg) => arg !== "--testnet"),
    ]
  : [
      "-m",
      "uvicorn",
      process.env.TERMINAL_TEST_RUN === "1"
        ? "e2e.aegis_server:app"
        : "backend.api:app",
      "--host",
      "127.0.0.1",
      "--port",
      process.env.TERMINAL_PORT ?? "8787",
    ];
const backend = spawn(python, backendArgs, {
  stdio: "inherit",
  env: process.env,
});
const frontend = spawn(
  "node_modules/.bin/vite",
  ["--config", "frontend/vite.config.ts", "--host", "127.0.0.1"],
  { stdio: "inherit", env: process.env },
);
let stopping = false;
function stop(code = 0) {
  if (stopping) return;
  stopping = true;
  backend.kill("SIGTERM");
  frontend.kill("SIGTERM");
  setTimeout(() => process.exit(code), 500).unref();
}
process.on("SIGINT", () => stop());
process.on("SIGTERM", () => stop());
backend.on("exit", (code) => stop(code ?? 1));
frontend.on("exit", (code) => stop(code ?? 1));
