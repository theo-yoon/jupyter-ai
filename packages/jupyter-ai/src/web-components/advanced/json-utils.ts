export function decodeHtmlEntities(value: string): string {
  if (!value.includes('&')) {
    return value;
  }

  if (typeof window === 'undefined' || typeof DOMParser === 'undefined') {
    // Fallback to a minimal manual decode for non-browser environments.
    return value
      .replace(/&quot;/g, '"')
      .replace(/&apos;/g, "'")
      .replace(/&lt;/g, '<')
      .replace(/&gt;/g, '>')
      .replace(/&amp;/g, '&');
  }

  const parser = new DOMParser();
  const decoded = parser.parseFromString(value, 'text/html');
  return decoded.documentElement.textContent ?? value;
}

export function parseJsonContent<T = unknown>(
  value: string | null | undefined
): T | null {
  if (!value) {
    return null;
  }

  const decoded = decodeHtmlEntities(value);
  try {
    return JSON.parse(decoded) as T;
  } catch (error) {
    console.error('Failed to parse JSON content:', error);
    return null;
  }
}
