let csrf = "";
let initializing: Promise<void> | null = null;

async function session() {
  if (!initializing)
    initializing = fetch("/api/session", {
      method: "POST",
      credentials: "same-origin",
    })
      .then(async (response) => {
        if (!response.ok)
          throw new Error("Could not establish a local terminal session.");
        csrf = (await response.json()).csrf_token;
      })
      .catch((error) => {
        initializing = null;
        throw error;
      });
  await initializing;
}

export async function api<T>(
  path: string,
  method = "GET",
  body?: unknown,
): Promise<T> {
  await session();
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), 65000);
  try {
    const requestCsrf = csrf;
    const options = {
      method,
      credentials: "same-origin" as RequestCredentials,
      headers: { "Content-Type": "application/json", "X-Terminal-CSRF": csrf },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: controller.signal,
    };
    let response = await fetch(`/api${path}`, options);
    if (response.status === 401) {
      if (csrf === requestCsrf) {
        initializing = null;
        csrf = "";
      }
      await session();
      if (method !== "GET")
        throw new Error(
          "Session refreshed. Review the preview and retry this action; it was not resubmitted automatically.",
        );
      response = await fetch(`/api${path}`, {
        ...options,
        headers: { ...options.headers, "X-Terminal-CSRF": csrf },
      });
    }
    let data;
    try {
      data = await response.json();
    } catch {
      throw new Error(
        `Backend returned an unreadable response (${response.status}). Check that make demo is running and restart it after backend changes.`,
      );
    }
    if (!response.ok) {
      const details = Array.isArray(data.error?.details)
        ? data.error.details
            .slice(0, 3)
            .map(
              (item: { location?: string[]; message?: string }) =>
                `${
                  item.location
                    ?.filter((p) => p !== "body")
                    .join(".")
                    .replaceAll("_", " ") || "Request"
                }: ${item.message || "invalid value"}`,
            )
            .join("; ")
        : "";
      throw new Error(
        (data.error?.message ?? `Request failed (${response.status})`) +
          (details ? ". " + details : ""),
      );
    }
    return data as T;
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError")
      throw new Error(
        "The request timed out. It may still have been recorded; inspect the latest state before retrying a change.",
      );
    if (error instanceof TypeError)
      throw new Error(
        "Could not reach the backend. Start make demo, wait for the API to be ready, and retry.",
      );
    throw error;
  } finally {
    window.clearTimeout(timeout);
  }
}
