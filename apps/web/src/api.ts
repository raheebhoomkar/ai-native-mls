/** Thin wrapper over fetch for the MLS API. Hand-written until the client is generated from OpenAPI (Sprint 4). */

import { useCallback, useEffect, useState } from "react";

type FieldError = { field: string; message: string };

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly requestId: string | null,
    readonly details: FieldError[] = [],
  ) {
    super(message);
  }
}

// Sent as X-Organisation-ID on every request; the API ignores it where it does not apply.
let activeOrganisationId: string | null = null;

export function setActiveOrganisation(id: string | null) {
  activeOrganisationId = id;
}

export async function api<T>(
  path: string,
  init?: { method?: string; body?: unknown },
): Promise<T> {
  const headers: Record<string, string> = {};
  if (init?.body !== undefined) headers["Content-Type"] = "application/json";
  if (activeOrganisationId) headers["X-Organisation-ID"] = activeOrganisationId;

  let response: Response;
  try {
    response = await fetch(`/api/v1${path}`, {
      method: init?.method ?? "GET",
      headers,
      body: init?.body === undefined ? undefined : JSON.stringify(init.body),
    });
  } catch {
    // Status 0 means the request never reached the API.
    throw unreachable();
  }
  if (response.ok) {
    return (response.status === 204 ? undefined : await response.json()) as T;
  }
  // Errors use the API envelope; a proxy failure may not be JSON.
  const body = await response.json().catch(() => null);
  throw toApiError(response.status, body, response.headers.get("X-Request-ID"));
}

/** Status 0: the request never reached the API. */
function unreachable() {
  const message = navigator.onLine
    ? "The server cannot be reached. Try again in a moment."
    : "You are offline. Try again when the connection is back.";
  return new ApiError(0, "unreachable", message, null);
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function toApiError(status: number, body: any, requestId: string | null) {
  return new ApiError(
    status,
    body?.error?.code ?? "error",
    body?.error?.message ?? `The API responded with status ${status}.`,
    requestId,
    body?.error?.details ?? [],
  );
}

/** POST a file as the raw request body, reporting progress (0 to 1). fetch cannot report upload progress. */
export function uploadFile<T>(
  path: string,
  file: File,
  onProgress: (fraction: number) => void,
): Promise<T> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `/api/v1${path}`);
    xhr.setRequestHeader("Content-Type", file.type);
    if (activeOrganisationId)
      xhr.setRequestHeader("X-Organisation-ID", activeOrganisationId);
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress(event.loaded / event.total);
    };
    xhr.onerror = () => reject(unreachable());
    xhr.onload = () => {
      let body = null;
      try {
        body = JSON.parse(xhr.responseText);
      } catch {
        // not JSON: a proxy error page
      }
      if (xhr.status >= 200 && xhr.status < 300) resolve(body as T);
      else
        reject(
          toApiError(xhr.status, body, xhr.getResponseHeader("X-Request-ID")),
        );
    };
    xhr.send(file);
  });
}

export function describeError(error: unknown): string {
  if (!(error instanceof ApiError)) return "Something went wrong.";
  // Name the field: "Input should be greater than 0" alone does not say which input.
  const fields = error.details
    .map((d) => {
      const name = d.field.replace(/^(body|query)\./, "").replace(/[._]/g, " ");
      return /^(current|new) password$|^password$/.test(name)
        ? d.message
        : `${name}: ${d.message}`;
    })
    .join(" ");
  const text = fields ? `${error.message} ${fields}` : error.message;
  // Validation and permission answers are self-explanatory; other failures get the ID for support.
  return error.requestId && (error.status >= 500 || error.status === 401)
    ? `${text} (request ${error.requestId})`
    : text;
}

/** Run a form submission or button action with busy and error state. */
export function useAction() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const run = useCallback(async (action: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (caught) {
      setError(describeError(caught));
    } finally {
      setBusy(false);
    }
  }, []);
  return { run, busy, error };
}

type Page<T> = { items: T[]; next_cursor: string | null };

/** Load a paginated collection. `reloadKey` changes (for example the organisation) restart it. */
export function useList<T>(path: string, reloadKey: unknown) {
  const [state, setState] = useState<{
    items: T[];
    next: string | null;
    loading: boolean;
    error: string | null;
  }>({ items: [], next: null, loading: true, error: null });
  const [version, setVersion] = useState(0);

  useEffect(() => {
    let cancelled = false;
    api<Page<T>>(path)
      .then((page) => {
        if (!cancelled)
          setState({
            items: page.items,
            next: page.next_cursor,
            loading: false,
            error: null,
          });
      })
      .catch((error) => {
        if (!cancelled)
          setState({
            items: [],
            next: null,
            loading: false,
            error: describeError(error),
          });
      });
    return () => {
      cancelled = true;
    };
  }, [path, reloadKey, version]);

  const loadMore = useCallback(async () => {
    if (!state.next) return;
    try {
      const separator = path.includes("?") ? "&" : "?";
      const page = await api<Page<T>>(
        `${path}${separator}cursor=${encodeURIComponent(state.next)}`,
      );
      setState((s) => ({
        ...s,
        items: [...s.items, ...page.items],
        next: page.next_cursor,
      }));
    } catch (error) {
      setState((s) => ({ ...s, error: describeError(error) }));
    }
  }, [path, state.next]);

  const reload = useCallback(() => setVersion((v) => v + 1), []);
  return { ...state, loadMore, reload };
}

export type Role =
  "mls_admin" | "brokerage_admin" | "broker" | "agent" | "api_consumer";

export const ROLE_LABELS: Record<Role, string> = {
  mls_admin: "MLS administrator",
  brokerage_admin: "Brokerage administrator",
  broker: "Broker",
  agent: "Agent",
  api_consumer: "API consumer",
};

export type Membership = {
  organisation_id: string;
  organisation_name: string;
  organisation_kind: "mls" | "brokerage";
  role: Role;
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

export type Organisation = {
  id: string;
  name: string;
  kind: "mls" | "brokerage";
};

export type CurrentOrganisation = Organisation & {
  my_role: Role | null;
  my_permissions: string[];
  assignable_roles: Role[];
};

/** A one-time link built from a token the API returned once. The token stays in the URL fragment. */
export function tokenLink(route: string, token: string): string {
  return `${window.location.origin}${window.location.pathname}#/${route}?token=${encodeURIComponent(token)}`;
}
