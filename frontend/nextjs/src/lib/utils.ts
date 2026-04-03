export function normalizeBaseUrl(value: string): string {
  return value.trim().replace(/\/+$/, "");
}

export function prettyJson(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

export function safeToString(value: unknown): string {
  if (value === null || value === undefined) {
    return "";
  }
  if (typeof value === "string") {
    return value;
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  return prettyJson(value);
}

export function coerceDescription(value: unknown): string {
  if (value === null || value === undefined) {
    return "";
  }

  if (typeof value === "string") {
    return value;
  }

  if (typeof value === "object") {
    const parts: string[] = [];

    const walk = (node: unknown) => {
      if (!node) {
        return;
      }

      if (Array.isArray(node)) {
        for (const item of node) {
          walk(item);
        }
        return;
      }

      if (typeof node === "object") {
        const maybeText = (node as { text?: unknown }).text;
        if (typeof maybeText === "string" && maybeText.trim()) {
          parts.push(maybeText.trim());
        }

        for (const child of Object.values(node as Record<string, unknown>)) {
          walk(child);
        }
      }
    };

    walk(value);

    if (parts.length > 0) {
      return parts.join("\n");
    }

    return prettyJson(value);
  }

  return String(value);
}