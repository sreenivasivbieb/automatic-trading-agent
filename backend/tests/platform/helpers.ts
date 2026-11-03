import { randomUUID } from "node:crypto";
import type { Config } from "../../src/config.js";
import {
  specSchema,
  type Agent,
  type Deployment,
  type Principal,
} from "../../src/domain/schemas.js";
import type {
  RuntimeProvider,
  RuntimeStatus,
} from "../../src/runtime/runtime.interface.js";
export const alice: Principal = { userId: randomUUID(), username: "alice" },
  bob: Principal = { userId: randomUUID(), username: "bob" };
export const config: Config = {
  NODE_ENV: "test",
  KRONO_LLM_PROVIDER: "bedrock",
  GROQ_MODEL: "openai/gpt-oss-120b",
  GROQ_BASE_URL: "https://api.groq.com/openai/v1",
  AWS_REGION: "ap-south-1",
  KRONO_ENV: "development",
  KRONO_PORT: 8790,
  KRONO_HOST: "127.0.0.1",
  KRONO_PUBLIC_ORIGIN: "http://localhost:5173",
  COGNITO_USER_POOL_ID: "ap-south-1_fixture",
  COGNITO_CLIENT_ID: "fixtureclient",
  KRONO_CONTROL_TABLE: "control",
  KRONO_RUNTIME_TABLE: "runtime",
  KRONO_AGENT_CONTROL_TABLE: "agent-control",
  KRONO_ARTIFACT_BUCKET: "artifacts",
  KRONO_CLUSTER_ARN:
    "arn:aws:ecs:ap-south-1:111111111111:cluster/krono-development",
  KRONO_DEPLOYMENT_WORKFLOW_ARN:
    "arn:aws:states:ap-south-1:111111111111:stateMachine:krono-development-deployment",
  KRONO_PROVISIONER_ROLE_ARN: "arn:aws:iam::111111111111:role/provisioner",
  KRONO_TASK_EXECUTION_ROLE_ARN: "arn:aws:iam::111111111111:role/execution",
  KRONO_AGENT_BOUNDARY_ARN: "arn:aws:iam::111111111111:policy/boundary",
  KRONO_AGENT_IMAGE:
    "111111111111.dkr.ecr.ap-south-1.amazonaws.com/krono/agent@sha256:" +
    "a".repeat(64),
  KRONO_PRIVATE_SUBNETS: "subnet-one,subnet-two",
  KRONO_AGENT_SECURITY_GROUP: "sg-fixture",
  KRONO_RUNTIME_KMS_ARN: "arn:aws:kms:ap-south-1:111111111111:key/fixture",
  KRONO_AGENT_LOG_GROUP: "/krono/agents",
  KRONO_COORDINATION_QUEUE_URL:
    "https://sqs.ap-south-1.amazonaws.com/111111111111/coordination",
  BEDROCK_MODEL_ID: "minimax.minimax-m2.5",
  BEDROCK_MAX_OUTPUT_TOKENS: 2048,
  BEDROCK_TEMPERATURE: 0.2,
  BEDROCK_TIMEOUT_MS: 120000,
  BEDROCK_MAX_ATTEMPTS: 2,
  KRONO_MAX_AGENTS_PER_USER: 2,
  KRONO_MAX_AGENT_SPECS_PER_USER: 20,
  KRONO_DAILY_TOKEN_LIMIT: 100000,
  KRONO_DAILY_RUNTIME_SECONDS: 14400,
  KRONO_MESSAGE_RETENTION_DAYS: 30,
};
export function spec(extra: Record<string, unknown> = {}) {
  return specSchema.parse({
    name: "Momentum Operator",
    description: "Conservative simulated momentum",
    type: "trading",
    configuration: {
      assets: ["BTC"],
      strategies: ["momentum_v1", "trend_following_v1"],
      marketProvider: "fixture",
      newsProvider: "fixture",
    },
    riskPolicy: {},
    permissions: {
      readMarketData: true,
      readPortfolio: true,
      generateSignals: true,
      executeTrades: false,
      modifyRiskSettings: false,
    },
    execution: { template: "krono-python-v1" },
    ...extra,
  });
}
export class FixtureRuntime implements RuntimeProvider {
  policies = new Map<string, { emergency: boolean; version: number }>();
  async tenantPolicy(p: Principal) {
    return this.policies.get(p.userId) ?? { emergency: false, version: 0 };
  }
  async setEmergency(
    p: Principal,
    emergency: boolean,
    expectedVersion?: number,
  ) {
    const c = await this.tenantPolicy(p);
    if (expectedVersion !== undefined && expectedVersion !== c.version)
      throw Error("Conflict");
    const next = { emergency, version: c.version + 1 };
    this.policies.set(p.userId, next);
    return next;
  }
  calls: string[] = [];
  statuses = new Map<string, RuntimeStatus["status"]>();
  async prepare(p: Principal, a: Agent, _spec: unknown, d: Deployment) {
    if (a.ownerId !== p.userId) throw Error("Tenant mismatch");
    this.calls.push(`prepare:${d.id}`);
  }
  async deploy(_p: Principal, a: Agent, d: Deployment) {
    this.calls.push(`deploy:${d.id}`);
    this.statuses.set(a.id, "HEALTH_CHECK");
    return { workflowArn: `fixture:${d.id}` };
  }
  async status(_p: Principal, a: Agent): Promise<RuntimeStatus> {
    return {
      deploymentId: a.deployment!.id,
      status: this.statuses.get(a.id) ?? "PROVISIONING",
    };
  }
  async control(_p: Principal, a: Agent, command: string) {
    this.calls.push(command);
    this.statuses.set(
      a.id,
      command === "PAUSE"
        ? "PAUSED"
        : command === "STOP"
          ? "STOPPED"
          : "RUNNING",
    );
  }
  async events() {
    return { items: [] };
  }
  async logs() {
    return { items: [] };
  }
}
