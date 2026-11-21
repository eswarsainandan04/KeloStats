import { API_BASE_URL } from "./config";

// Singleton promise to ensure concurrent 401 requests trigger only a single refresh call
let refreshPromise: Promise<string | null> | null = null;

async function refreshAccessToken(): Promise<string | null> {
  if (typeof window === "undefined") return null;

  const refreshToken = localStorage.getItem("kelostats_refresh_token");
  if (!refreshToken) {
    return null;
  }

  if (refreshPromise) {
    return refreshPromise;
  }

  refreshPromise = (async () => {
    try {
      const res = await fetch(`${API_BASE_URL}/api/auth/refresh`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: refreshToken }),
      });

      if (!res.ok) {
        throw new Error(`Refresh endpoint returned status ${res.status}`);
      }

      const data = await res.json();
      if (data?.access_token) {
        localStorage.setItem("kelostats_token", data.access_token);
        return data.access_token as string;
      }
      return null;
    } catch (err) {
      console.warn("[fetchWithAuth] Token refresh failed:", err);
      localStorage.removeItem("kelostats_token");
      localStorage.removeItem("kelostats_refresh_token");
      localStorage.removeItem("kelostats_user");

      if (
        !window.location.pathname.startsWith("/login") &&
        !window.location.pathname.startsWith("/signup")
      ) {
        window.location.href = "/login";
      }
      return null;
    } finally {
      refreshPromise = null;
    }
  })();

  return refreshPromise;
}

/**
 * Fetch wrapper that automatically appends the native Kelostats JWT Bearer token
 * to the Authorization header for protected backend API calls.
 * Automatically intercepts 401 errors, uses the refresh token to get a new
 * access token, and seamlessly retries the original request.
 */
export async function fetchWithAuth(url: string, options: RequestInit = {}): Promise<Response> {
  let token: string | null = null;
  let savedUserId: string | undefined;

  if (typeof window !== "undefined") {
    try {
      token = localStorage.getItem("kelostats_token");
      savedUserId = getStoredUserId() || undefined;
    } catch (err) {
      console.warn("[fetchWithAuth] Unable to read localStorage credentials:", err);
    }
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

  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }
  if (savedUserId && !headers["x-user-id"]) {
    headers["x-user-id"] = savedUserId;
  }

  let response = await fetch(resolvedUrl, {
    ...options,
    headers,
  });

  // Intercept 401 Unauthorized and auto-refresh using the stored refresh token
  if (response.status === 401 && typeof window !== "undefined") {
    const isAuthRoute = resolvedUrl.includes("/api/auth/");
    if (!isAuthRoute) {
      const newToken = await refreshAccessToken();
      if (newToken) {
        // Retry original request with newly issued access token
        headers["Authorization"] = `Bearer ${newToken}`;
        response = await fetch(resolvedUrl, {
          ...options,
          headers,
        });
      } else {
        // If refresh failed and user session is invalid, redirect to login
        if (
          !window.location.pathname.startsWith("/login") &&
          !window.location.pathname.startsWith("/signup")
        ) {
          console.warn("[fetchWithAuth] 401 Unauthorized - Refresh failed. Redirecting to /login.");
          window.location.href = "/login";
        }
      }
    }
  }

  return response;
}

export interface StoredUser {
  user_id: string;
  full_name?: string;
  email?: string;
}

/**
 * Single source of truth for reading the stored user session from localStorage.
 */
export function getStoredUser(): StoredUser | null {
  if (typeof window === "undefined") return null;
  try {
    const saved = localStorage.getItem("kelostats_user");
    if (!saved) return null;
    const parsed = JSON.parse(saved);
    if (!parsed) return null;
    const userId = parsed.user_id || parsed.id;
    if (!userId) return null;
    return {
      user_id: String(userId),
      full_name: parsed.full_name,
      email: parsed.email,
    };
  } catch {
    return null;
  }
}

/**
 * Returns the authenticated user_id from the stored session.
 */
export function getStoredUserId(): string | null {
  return getStoredUser()?.user_id || null;
}
