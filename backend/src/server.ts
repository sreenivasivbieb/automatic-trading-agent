import Fastify from "fastify";
import cookie from "@fastify/cookie";
import { z, ZodError } from "zod";
import { DynamoDBClient } from "@aws-sdk/client-dynamodb";
import { DynamoDBDocumentClient } from "@aws-sdk/lib-dynamodb";
import { pathToFileURL } from "node:url";
import { randomUUID } from "node:crypto";
import { loadConfig, type Config } from "./config.js";
import { CognitoAuth, type Authenticator } from "./auth/cognito.js";
import { DynamoTenantStore, type TenantStore } from "./storage/tenant-store.js";
import { ProfileService } from "./profiles/profile.service.js";
import { AgentService } from "./agents/agent.service.js";
import { AwsRuntime } from "./runtime/aws-runtime.js";
import type { RuntimeProvider } from "./runtime/runtime.interface.js";
import { createBedrockClient } from "./integrations/llm/bedrock.client.js";
import { MiniMaxProvider } from "./integrations/llm/minimax.provider.js";
import { GroqProvider } from "./integrations/llm/groq.provider.js";
import { TokenUsageService } from "./integrations/llm/token-usage.service.js";
import { ConversationService } from "./integrations/llm/conversation.service.js";
import { ToolRegistry } from "./integrations/llm/tool-registry.js";
import { PromptManager } from "./integrations/llm/prompt-manager.js";
import type { LLMProvider } from "./integrations/llm/llm.interface.js";
import {
  idSchema,
  messageSchema,
  type Principal,
  type Agent,
} from "./domain/schemas.js";
import { PlatformError, missing, denied } from "./domain/errors.js";
import { AgentAnalysisService } from "./integrations/llm/agent-analysis.service.js";
import { consumeAnalysis } from "./integrations/llm/analysis-consumer.js";

declare module "fastify" {
  interface FastifyRequest {
    principal: Principal;
  }
}
export function createPlatform(
  c: Config,
  overrides?: {
    store?: TenantStore;
    runtime?: RuntimeProvider;
    auth?: Authenticator;
    llm?: LLMProvider;
  },
) {
  if (overrides && c.NODE_ENV !== "test")
    throw Error("Dependency overrides are restricted to tests");
  const db = DynamoDBDocumentClient.from(
    new DynamoDBClient({ region: c.AWS_REGION, maxAttempts: 3 }),
    { marshallOptions: { removeUndefinedValues: true } },
  );
  const store =
      overrides?.store ?? new DynamoTenantStore(db, c.KRONO_CONTROL_TABLE),
    profiles = new ProfileService(store);
  const runtime = overrides?.runtime ?? new AwsRuntime(c, db),
    agents = new AgentService(store, runtime, c, profiles);
  const llm =
    overrides?.llm ??
    (c.KRONO_LLM_PROVIDER === "groq"
      ? new GroqProvider(c, new TokenUsageService(store, c))
      : new MiniMaxProvider(
          createBedrockClient(c),
          c,
          new TokenUsageService(store, c),
        ));
  const tools = new ToolRegistry(agents, profiles),
    conversations = new ConversationService(
      store,
      llm,
      new PromptManager(store),
      tools,
      c.KRONO_MESSAGE_RETENTION_DAYS,
    );
  const auth = overrides?.auth ?? new CognitoAuth(c);
  const app = Fastify({
    genReqId: () => randomUUID(),
    logger: {
      level: c.NODE_ENV === "test" ? "silent" : "info",
      redact: [
        "req.headers.authorization",
        "req.headers.cookie",
        "req.body",
        "res.headers.set-cookie",
      ],
    },
    bodyLimit: 64 * 1024,
    requestTimeout: 180000,
    trustProxy: "uniquelocal",
  });
  app.register(cookie);
  if (c.KRONO_ANALYSIS_QUEUE_URL && !overrides) {
    let close: (() => Promise<void>) | undefined;
    app.addHook("onReady", async () => {
      close = consumeAnalysis(
        c.AWS_REGION,
        c.KRONO_ANALYSIS_QUEUE_URL!,
        new AgentAnalysisService(c, store, db, llm),
      );
    });
    app.addHook("onClose", async () => {
      await close?.();
    });
  }
  app.decorateRequest("principal");
  const windows = new Map<string, { count: number; until: number }>();
  app.addHook("onRequest", async (req, reply) => {
    reply
      .header("x-content-type-options", "nosniff")
      .header("x-frame-options", "DENY")
      .header("referrer-policy", "no-referrer")
      .header("cache-control", "no-store")
      .header("x-request-id", req.id);
    const origin = req.headers.origin;
    if (origin && origin !== c.KRONO_PUBLIC_ORIGIN)
      throw denied("Origin is not permitted");
    if (req.headers["sec-fetch-site"] === "cross-site")
      throw denied("Cross-site request blocked");
    const now = Date.now(),
      key = req.ip;
    let bucket = windows.get(key);
    if (!bucket || bucket.until < now) {
      bucket = { count: 0, until: now + 60000 };
      windows.set(key, bucket);
    }
    if (++bucket.count > 120)
      throw new PlatformError("RATE_LIMIT", "Request limit reached", 429);
    if (windows.size > 10000)
      for (const [k, v] of windows) if (v.until < now) windows.delete(k);
  });
  app.addHook("preHandler", async (req) => {
    const path = req.url.split("?")[0];
    if (path === "/platform/health" || path.startsWith("/platform/auth/"))
      return;
    req.principal = await auth.authenticate(req);
  });
  app.setErrorHandler((err, req, reply) => {
    const authErrors: Record<string, [number, string]> = {
      NotAuthorizedException: [
        401,
        "Sign-in failed. Check your email and password.",
      ],
      UserNotConfirmedException: [403, "Verify your email before signing in."],
      CodeMismatchException: [422, "The verification code is incorrect."],
      ExpiredCodeException: [
        422,
        "The verification code expired. Request another code.",
      ],
      InvalidPasswordException: [
        422,
        "Use at least 12 characters with uppercase, lowercase, a number and a symbol.",
      ],
      TooManyRequestsException: [
        429,
        "Authentication request limit reached. Try again later.",
      ],
      LimitExceededException: [
        429,
        "Authentication limit reached. Try again later.",
      ],
      UsernameExistsException: [
        409,
        "Registration could not be completed. Try signing in or resetting your password.",
      ],
      AliasExistsException: [
        409,
        "This email cannot be associated with the account.",
      ],
      UserNotFoundException: [
        400,
        "Unable to complete this authentication request.",
      ],
      InvalidParameterException: [
        422,
        "Check the authentication fields and try again.",
      ],
      ForbiddenException: [
        403,
        "Authentication was blocked by the account security policy.",
      ],
    };
    const authError = req.url.startsWith("/platform/auth/")
      ? authErrors[(err as Error).name]
      : undefined;
    if (authError)
      return reply.status(authError[0]).send({
        error: {
          code: "AUTHENTICATION",
          message: authError[1],
          requestId: req.id,
        },
      });
    if (err instanceof ZodError)
      return reply.status(422).send({
        error: {
          code: "VALIDATION",
          message: "Invalid request",
          fields: err.issues.map((i) => ({
            path: i.path.join("."),
            message: i.message,
          })),
          requestId: req.id,
        },
      });
    const transportError = err as { code?: string; statusCode?: number };
    if (
      transportError.code?.startsWith("FST_") &&
      transportError.statusCode &&
      transportError.statusCode >= 400 &&
      transportError.statusCode < 500
    )
      return reply.status(transportError.statusCode).send({
        error: {
          code: "INVALID_HTTP_REQUEST",
          message:
            transportError.statusCode === 413
              ? "Request body exceeds the allowed size"
              : transportError.statusCode === 415
                ? "Use the supported JSON content type"
                : "Malformed request; check the JSON body and headers",
          requestId: req.id,
        },
      });
    const known = err instanceof PlatformError;
    if (!known)
      req.log.warn({
        event: "request.failed",
        errorType: (err as Error).name,
        requestId: req.id,
      });
    return reply.status(known ? err.status : 503).send({
      error: {
        code: known ? err.code : "SERVICE_UNAVAILABLE",
        message: known
          ? err.message
          : "The service is unavailable. Verify AWS configuration and provider access.",
        requestId: req.id,
      },
    });
  });
  app.setNotFoundHandler((req, reply) =>
    reply.status(404).send({
      error: {
        code: "NOT_FOUND",
        message: "Endpoint not found",
        requestId: req.id,
      },
    }),
  );
  if (auth instanceof CognitoAuth)
    auth.routes(app, (p, identity) => profiles.syncIdentity(p, identity));
  app.get("/platform/health", async () => ({
    service: "KRONO control plane",
    configured: true,
    environment: c.KRONO_ENV,
    model: c.BEDROCK_MODEL_ID,
    region: c.AWS_REGION,
    liveEnabled: false,
    validationMode: c.NODE_ENV === "test" ? "FIXTURE" : null,
  }));
  app.get("/platform/ready", async (req) => {
    await profiles.get(req.principal);
    return { ready: true };
  });
  app.get(
    "/platform/emergency",
    (req) =>
      runtime.tenantPolicy?.(req.principal) ?? {
        emergency: false,
        available: false,
      },
  );
  app.post("/platform/emergency-stop", (req) =>
    agents.emergencyStop(req.principal),
  );
  app.post("/platform/emergency-clear", async (req) => {
    const v = z
      .object({
        expectedVersion: z.number().int().nonnegative(),
        acknowledgement: z.literal("CLEAR_EMERGENCY_KEEP_PAUSED"),
      })
      .strict()
      .parse(req.body);
    if (!runtime.setEmergency)
      throw new PlatformError(
        "UNAVAILABLE",
        "Execution barrier is unavailable",
        503,
      );
    const active = (
      await store.list<Agent>(req.principal, "AGENT", 100)
    ).items.filter((r) => r.data.deployment && r.data.state !== "TERMINATED");
    for (const a of active)
      await runtime.control(req.principal, a.data, "PAUSE");
    const policy = await runtime.setEmergency(
        req.principal,
        false,
        v.expectedVersion,
      ),
      prior = await store.get(req.principal, "CONFIG", "emergency");
    await store.commit(
      req.principal,
      [
        {
          kind: "CONFIG",
          id: "emergency",
          expectedVersion: prior?.version ?? 0,
          data: policy,
        },
      ],
      "emergency.cleared",
      { entriesRemainPaused: true },
    );
    return { ...policy, entriesRemainPaused: true };
  });
  app.get("/platform/profile", (req) => profiles.get(req.principal));
  // All profile changes use a review action. Important risk changes can never be hidden in a PATCH.
  app.post("/platform/profile/preview", async (req) => {
    const input = z
      .object({
        profile: z.unknown(),
        expectedVersion: z.number().int().positive(),
      })
      .strict()
      .parse(req.body);
    const prior = await profiles.get(req.principal);
    if (prior.version !== input.expectedVersion)
      throw new PlatformError("CONFLICT", "Profile changed; reload it", 409);
    const { profileSchema } = await import("./domain/schemas.js");
    return tools.pending(req.principal, "PROFILE_UPDATE", {
      profile: profileSchema.parse(input.profile),
      expectedVersion: input.expectedVersion,
    });
  });
  app.get("/platform/agents", (req) => {
    const q = pagination(req.query);
    return store.list<unknown>(req.principal, "AGENT", q.limit, q.cursor);
  });
  app.get("/platform/portfolio", (req) => agents.portfolio(req.principal));
  app.post("/platform/agents", (req) => agents.create(req.principal, req.body));
  app.get("/platform/agent-templates", (req) =>
    agents.templates(req.principal),
  );
  app.post("/platform/agent-templates/:id/instantiate", (req) => {
    const v = z
      .object({ id: z.string().regex(/^[a-z0-9-]{2,60}$/) })
      .parse(req.params);
    return agents.fromTemplate(req.principal, v.id);
  });
  const resource = (params: unknown) =>
    z.object({ id: idSchema }).parse(params).id;
  app.get("/platform/agents/:id", (req) =>
    agents.status(req.principal, resource(req.params)),
  );
  app.get("/platform/agents/:id/preview", (req) =>
    agents.preview(req.principal, resource(req.params)),
  );
  app.post("/platform/agents/:id/deploy", (req) =>
    agents.deploy(req.principal, resource(req.params), req.body),
  );
  app.post("/platform/agents/:id/configuration/preview", async (req) => {
    const input = z
        .object({
          specification: z.unknown(),
          expectedVersion: z.number().int().positive(),
        })
        .strict()
        .parse(req.body),
      id = resource(req.params),
      row = await agents.get(req.principal, id);
    if (row.version !== input.expectedVersion)
      throw new PlatformError("CONFLICT", "Agent changed; reload it", 409);
    const specification = await agents.validate(
      req.principal,
      input.specification,
    );
    return tools.pending(req.principal, "AGENT_UPDATE", {
      ...input,
      specification,
      agentId: id,
    });
  });
  app.post("/platform/agents/:id/rollback/preview", async (req) => {
    const input = z
        .object({
          configurationVersion: z.number().int().positive(),
          expectedVersion: z.number().int().positive(),
        })
        .strict()
        .parse(req.body),
      id = resource(req.params);
    await agents.get(req.principal, id);
    const prior = await store.get(
      req.principal,
      `AGENT_SPEC_${id}`,
      String(input.configurationVersion),
    );
    if (!prior) throw missing();
    return tools.pending(req.principal, "AGENT_UPDATE", {
      agentId: id,
      specification: await agents.validate(req.principal, prior.data),
      expectedVersion: input.expectedVersion,
    });
  });
  app.post("/platform/agents/:id/control", async (req) => {
    const input = z
      .object({
        command: z.enum(["PAUSE", "RESUME", "STOP", "RESTART", "TERMINATE"]),
        expectedVersion: z.number().int().positive(),
        acknowledgement: z.string().max(100).optional(),
      })
      .strict()
      .parse(req.body);
    return agents.control(
      req.principal,
      resource(req.params),
      input.command,
      input.expectedVersion,
      input.acknowledgement,
    );
  });
  const pagination = (query: unknown) =>
    z
      .object({
        limit: z.coerce.number().int().min(1).max(100).default(50),
        cursor: z.string().max(4096).optional(),
      })
      .parse(query);
  app.get("/platform/agents/:id/events", async (req) => {
    const row = await agents.get(req.principal, resource(req.params)),
      q = pagination(req.query);
    return runtime.events(req.principal, row.data, q.limit, q.cursor);
  });
  app.get("/platform/agents/:id/logs", async (req) => {
    const row = await agents.get(req.principal, resource(req.params)),
      q = pagination(req.query);
    return runtime.logs(req.principal, row.data, q.limit, q.cursor);
  });
  app.get("/platform/agents/:id/metrics", async (req) => {
    const row = await agents.get(req.principal, resource(req.params));
    if (!row.data.deployment || !runtime.metrics)
      return { available: false, cpuPercent: null, memoryPercent: null };
    return {
      available: true,
      ...((await runtime.metrics(req.principal, row.data)) as object),
    };
  });
  app.get("/platform/agents/:id/versions", async (req) => {
    const id = resource(req.params);
    await agents.get(req.principal, id);
    const q = pagination(req.query);
    return store.list(req.principal, `AGENT_SPEC_${id}`, q.limit, q.cursor);
  });
  app.post("/platform/conversations", (req) =>
    conversations.create(req.principal),
  );
  app.get("/platform/conversations", (req) => {
    const q = pagination(req.query);
    return store.list(req.principal, "CONVERSATION", q.limit, q.cursor);
  });
  app.get("/platform/conversations/:id/messages", async (req) => {
    const id = resource(req.params);
    if (!(await store.get(req.principal, "CONVERSATION", id))) throw missing();
    const q = pagination(req.query);
    return store.list(req.principal, `MESSAGE_${id}`, q.limit, q.cursor);
  });
  app.post("/platform/conversations/:id/messages", (req) => {
    const input = messageSchema.parse(req.body);
    return conversations.send(
      req.principal,
      resource(req.params),
      input.message,
      input.requestId,
    );
  });
  app.get("/platform/conversations/:id/requests/:requestId", async (req) => {
    const v = z.object({ id: idSchema, requestId: idSchema }).parse(req.params);
    const row = await store.get(
      req.principal,
      "CHAT_REQUEST",
      `${v.id}:${v.requestId}`,
    );
    if (!row) throw missing();
    return row;
  });
  app.post("/platform/actions/:id/approve", (req) => {
    const input = z
      .object({
        digest: z.string().regex(/^[a-f0-9]{64}$/),
        acknowledgement: z.literal("APPROVE_CHANGE"),
      })
      .strict()
      .parse(req.body);
    return tools.approve(req.principal, resource(req.params), input.digest);
  });
  app.get("/platform/history/:kind", (req) => {
    const kind = z
        .object({
          kind: z.enum([
            "AUDIT",
            "USAGE",
            "LLM_REQUEST",
            "DEPLOYMENT",
            "ACTION",
          ]),
        })
        .parse(req.params).kind,
      q = pagination(req.query);
    return store.list(req.principal, kind, q.limit, q.cursor);
  });
  app.get("/platform/strategies", async () => ({
    items: [
      { id: "momentum_v1", name: "Momentum Trading" },
      { id: "mean_reversion_v1", name: "Mean Reversion" },
      { id: "trend_following_v1", name: "Trend Following" },
      { id: "breakout_v1", name: "Breakout Trading" },
      {
        id: "spread_research_v1",
        name: "Arbitrage Detection",
        limitation:
          "Ineligible until verified compatible quotes and positive net costs are available",
      },
    ],
  }));
  return { app, agents, profiles, store, conversations, tools };
}
if (
  process.argv[1] &&
  import.meta.url === pathToFileURL(process.argv[1]).href
) {
  try {
    const c = loadConfig();
    await createPlatform(c).app.listen({
      host: c.KRONO_HOST,
      port: c.KRONO_PORT,
    });
  } catch (e) {
    console.error(
      JSON.stringify({
        event: "platform.startup.failed",
        message: (e as Error).message,
      }),
    );
    process.exitCode = 1;
  }
}
