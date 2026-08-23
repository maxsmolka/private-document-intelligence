const VALIDATION_ORIGIN = "https://pdi.invalid";
const CONTROL_CHARACTER = /[\u0000-\u001f\u007f]/;

function normalizeInternalPath(candidate: string | null | undefined): string | null {
  if (
    !candidate
    || candidate !== candidate.trim()
    || CONTROL_CHARACTER.test(candidate)
    || !candidate.startsWith("/")
    || candidate.startsWith("//")
  ) {
    return null;
  }

  try {
    const target = new URL(candidate, VALIDATION_ORIGIN);
    if (target.origin !== VALIDATION_ORIGIN) return null;
    return `${target.pathname}${target.search}${target.hash}`;
  } catch {
    return null;
  }
}

export function resolveSafeInternalRedirect(
  candidate: string | null | undefined,
  fallback = "/",
): string {
  return normalizeInternalPath(candidate) ?? normalizeInternalPath(fallback) ?? "/";
}
