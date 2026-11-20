/** Typed JSON-RPC client with request ids and CSRF from the shell meta tags. */

export class RpcError extends Error {
  constructor(
    message: string,
    readonly code: number = -32000,
  ) {
    super(message);
    this.name = "RpcError";
  }
}

let nextId = 1;

function meta(name: string): string {
  return document.querySelector<HTMLMetaElement>(`meta[name="${name}"]`)?.content ?? "";
}

function csrfToken(): string {
  return meta("kberp-csrf");
}

export async function rpc<T>(method: string, params: Record<string, unknown> = {}): Promise<T> {
  const id = nextId++;
  let response: Response;
  try {
    response = await fetch("/web/rpc", {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": csrfToken(),
      },
      body: JSON.stringify({ jsonrpc: "2.0", id, method, params }),
    });
  } catch {
    throw new RpcError("The server is unreachable. Check your connection and try again.");
  }

  const text = await response.text();
  let payload: {
    id?: number;
    result?: T;
    error?: { code?: number; message?: string };
  };
  try {
    payload = JSON.parse(text) as typeof payload;
  } catch {
    throw new RpcError("Your session expired. Reload the page and sign in again.");
  }
  if (payload.error) {
    throw new RpcError(payload.error.message ?? "The request failed.", payload.error.code);
  }
  if (payload.result === undefined) {
    throw new RpcError("The server returned an empty response.");
  }
  return payload.result;
}
