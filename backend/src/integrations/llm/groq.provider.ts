import type { Config } from "../../config.js";
import { PlatformError } from "../../domain/errors.js";
import type {
  LLMProvider,
  LLMRequest,
  LLMResponse,
  ModelMessage,
} from "./llm.interface.js";
import { TokenUsageService } from "./token-usage.service.js";

type Fetch = typeof fetch;
type OpenAIMessage =
  | { role: "system" | "user"; content: string }
  | {
      role: "assistant";
      content: string | null;
      tool_calls?: Array<{
        id: string;
        type: "function";
        function: { name: string; arguments: string };
      }>;
    }
  | { role: "tool"; tool_call_id: string; content: string };

/** Converts the platform's Converse-shaped messages to OpenAI Chat Completions messages. */
export function toOpenAIMessages(
  system: string,
  messages: ModelMessage[],
): OpenAIMessage[] {
  const out: OpenAIMessage[] = [{ role: "system", content: system }];
  for (const message of messages) {
    const text = message.content
      .flatMap((b) => ("text" in b ? [b.text] : []))
      .join("\n");
    if (message.role === "assistant") {
      const calls = message.content.flatMap((b) =>
        "toolUse" in b
          ? [
              {
                id: b.toolUse.toolUseId,
                type: "function" as const,
                function: {
                  name: b.toolUse.name,
                  arguments: JSON.stringify(b.toolUse.input ?? {}),
                },
              },
            ]
          : [],
      );
      out.push({
        role: "assistant",
        content: text || null,
        ...(calls.length ? { tool_calls: calls } : {}),
      });
      continue;
    }
    for (const b of message.content)
      if ("toolResult" in b)
        out.push({
          role: "tool",
          tool_call_id: b.toolResult.toolUseId,
          content: b.toolResult.content.map((c) => c.text).join("\n"),
        });
    if (text) out.push({ role: "user", content: text });
  }
  return out;
}

/** Groq through its OpenAI-compatible endpoint, with the same usage accounting as Bedrock. */
export class GroqProvider implements LLMProvider {
  constructor(
    private config: Config,
    private usage: TokenUsageService,
    private fetcher: Fetch = fetch,
  ) {
    if (!config.GROQ_API_KEY)
      throw new PlatformError(
        "MODEL_UNAVAILABLE",
        "KRONO_LLM_PROVIDER=groq requires GROQ_API_KEY",
        503,
      );
  }
  async converse(request: LLMRequest): Promise<LLMResponse> {
    for (
      let attempt = 0;
      attempt < this.config.BEDROCK_MAX_ATTEMPTS;
      attempt++
    ) {
      try {
        return await this.invoke(request);
      } catch (e) {
        if (
          !(e instanceof PlatformError) ||
          e.code !== "MODEL_THROTTLED" ||
          attempt + 1 >= this.config.BEDROCK_MAX_ATTEMPTS
        )
          throw e;
        await new Promise((resolve) => setTimeout(resolve, 500 * 2 ** attempt));
      }
    }
    throw new PlatformError(
      "MODEL_UNAVAILABLE",
      "Groq retry limit reached",
      503,
    );
  }
  private async invoke(request: LLMRequest): Promise<LLMResponse> {
    const bytes = Buffer.byteLength(
      JSON.stringify({
        system: request.system,
        messages: request.messages,
        tools: request.tools,
        outputSchema: request.outputSchema,
      }),
    );
    if (bytes > 80_000)
      throw new PlatformError(
        "CONTEXT_LIMIT",
        "Conversation context is too large",
        413,
      );
    const reservation = await this.usage.reserve(
        request.context,
        bytes + 2048 + this.config.BEDROCK_MAX_OUTPUT_TOKENS,
      ),
      started = Date.now();
    let recorded = false;
    try {
      const response = await this.fetcher(
        this.config.GROQ_BASE_URL.replace(/\/$/, "") + "/chat/completions",
        {
          method: "POST",
          headers: {
            authorization: `Bearer ${this.config.GROQ_API_KEY}`,
            "content-type": "application/json",
          },
          signal: AbortSignal.timeout(this.config.BEDROCK_TIMEOUT_MS),
          body: JSON.stringify({
            model: this.config.GROQ_MODEL,
            messages: toOpenAIMessages(request.system, request.messages),
            max_completion_tokens: this.config.BEDROCK_MAX_OUTPUT_TOKENS,
            temperature: this.config.BEDROCK_TEMPERATURE,
            ...(request.tools?.length
              ? {
                  tools: request.tools.map((t) => ({
                    type: "function",
                    function: {
                      name: t.name,
                      description: t.description,
                      parameters: t.inputSchema,
                    },
                  })),
                  parallel_tool_calls: false,
                }
              : {}),
            ...(request.outputSchema
              ? {
                  response_format: {
                    type: "json_schema",
                    json_schema: {
                      name: request.outputSchema.name,
                      schema: request.outputSchema.schema,
                    },
                  },
                }
              : {}),
          }),
        },
      );
      if (response.status === 429 || response.status === 503)
        throw new PlatformError(
          "MODEL_THROTTLED",
          "Groq is rate limited or busy",
          503,
        );
      if (!response.ok)
        throw new PlatformError(
          "MODEL_UNAVAILABLE",
          `Groq request failed (${response.status}); verify the key and model`,
          503,
        );
      const body = (await response.json()) as {
        choices?: Array<{
          finish_reason?: string;
          message?: {
            content?: string | null;
            tool_calls?: Array<{
              id: string;
              type: string;
              function: { name: string; arguments: string };
            }>;
          };
        }>;
        usage?: { prompt_tokens?: number; completion_tokens?: number };
      };
      const choice = body.choices?.[0],
        content: ModelMessage["content"] = [];
      if (choice?.message?.content)
        content.push({ text: choice.message.content });
      for (const call of choice?.message?.tool_calls ?? []) {
        if (call.type !== "function") continue;
        let input: unknown;
        try {
          input = JSON.parse(call.function.arguments || "{}");
        } catch {
          throw new PlatformError(
            "MODEL_UNAVAILABLE",
            "Groq returned malformed tool input",
            502,
          );
        }
        content.push({
          toolUse: { toolUseId: call.id, name: call.function.name, input },
        });
      }
      const durationMs = Date.now() - started,
        inputTokens = body.usage?.prompt_tokens,
        outputTokens = body.usage?.completion_tokens;
      await this.usage.finish(reservation, {
        inputTokens,
        outputTokens,
        durationMs,
        status: "SUCCEEDED",
      });
      recorded = true;
      if (!content.length)
        throw new PlatformError(
          "EMPTY_MODEL_OUTPUT",
          "The model returned no public result",
          502,
        );
      return {
        message: { role: "assistant", content },
        // Bedrock-compatible stop reasons keep the conversation loop provider-neutral.
        stopReason:
          choice?.finish_reason === "tool_calls"
            ? "tool_use"
            : (choice?.finish_reason ?? "unknown"),
        usage: {
          inputTokens: inputTokens ?? null,
          outputTokens: outputTokens ?? null,
        },
        modelId: this.config.GROQ_MODEL,
        durationMs,
      };
    } catch (e) {
      if (!recorded)
        await this.usage.finish(reservation, {
          durationMs: Date.now() - started,
          status: "UNKNOWN",
        });
      if (e instanceof PlatformError) throw e;
      throw new PlatformError(
        "MODEL_UNAVAILABLE",
        "Groq request failed; verify network access, key and model",
        503,
      );
    }
  }
}
