import { supabase } from "./supabase";
import { API_BASE_URL } from "./config";

/**
 * Fetch wrapper that automatically appends the Supabase Bearer token
 * to the Authorization header for protected backend API calls.
 */
export async function fetchWithAuth(url: string, options: RequestInit = {}): Promise<Response> {
  let token: string | undefined;

  try {
    const { data } = await supabase.auth.getSession();
    token = data.session?.access_token;
  } catch (err) {
    console.warn("[fetchWithAuth] Unable to retrieve Supabase session token:", err);
  }

  const resolvedUrl = url.startsWith("http://") || url.startsWith("https://")
    ? url
    : `${API_BASE_URL}${url.startsWith("/") ? "" : "/"}${url}`;

  const existingHeaders = (options.headers as Record<string, string>) || {};

  const headers: Record<string, string> = {
    ...existingHeaders,
  };

  // Set default JSON Content-Type if not sending FormData
  if (!(options.body instanceof FormData) && !headers["Content-Type"]) {
    headers["Content-Type"] = "application/json";
  }

  let savedUserId: string | undefined;
  if (typeof window !== "undefined") {
    try {
      const saved = localStorage.getItem("kelostats_user");
      if (saved) {
        savedUserId = JSON.parse(saved).user_id;
      }
    } catch {}
  }

  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }
  if (savedUserId && !headers["x-user-id"]) {
    headers["x-user-id"] = savedUserId;
  }

  const response = await fetch(resolvedUrl, {
    ...options,
    headers,
  });

  // Only redirect if there is no user session stored at all
  if (response.status === 401 && typeof window !== "undefined") {
    const saved = localStorage.getItem("kelostats_user");
    if (!saved && !window.location.pathname.startsWith("/login") && !window.location.pathname.startsWith("/signup")) {
      console.warn("[fetchWithAuth] 401 Unauthorized - No active session. Redirecting to /login.");
      window.location.href = "/login";
    }
  }

  return response;
}
