/** Thin wrapper over fetch for the MLS API. Hand-written until the client is generated from OpenAPI (Sprint 4). */

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly requestId: string | null,
  ) {
    super(message);
  }
}

/** Status 0 means the request never reached the API. */
const UNREACHABLE = new ApiError(
  0,
  "unreachable",
  "The API is not reachable.",
  null,
);

export async function api<T>(
  path: string,
  init?: { method?: string; body?: unknown },
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api/v1${path}`, {
      method: init?.method ?? "GET",
      headers:
        init?.body === undefined
          ? undefined
          : { "Content-Type": "application/json" },
      body: init?.body === undefined ? undefined : JSON.stringify(init.body),
    });
  } catch {
    throw UNREACHABLE;
  }
  if (response.ok) {
    return (response.status === 204 ? undefined : await response.json()) as T;
  }
  // Errors use the API envelope; a proxy failure may not be JSON.
  const body = await response.json().catch(() => null);
  throw new ApiError(
    response.status,
    body?.error?.code ?? "error",
    body?.error?.message ?? `The API responded with status ${response.status}.`,
    response.headers.get("X-Request-ID"),
  );
}

export function describeError(error: unknown): string {
  if (error instanceof ApiError) {
    return error.requestId
      ? `${error.message} (request ${error.requestId})`
      : error.message;
  }
  return "Something went wrong.";
}

export type Membership = {
  organisation_id: string;
  organisation_name: string;
  organisation_kind: "mls" | "brokerage";
  role: "mls_admin" | "brokerage_admin" | "broker" | "agent" | "api_consumer";
};

export type Me = {
  user: {
    id: string;
    email: string;
    full_name: string;
    is_platform_admin: boolean;
  };
  memberships: Membership[];
};
