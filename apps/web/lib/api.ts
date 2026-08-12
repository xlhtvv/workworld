export const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export async function apiFetch(path: string, token?: string, init?: RequestInit) {
  const headers = new Headers(init?.headers);
  headers.set("content-type", "application/json");
  if (token) headers.set("authorization", `Bearer ${token}`);
  return fetch(`${apiUrl}${path}`, {...init, headers});
}
