// Centralized API configuration reading from environment variables
const rawBaseUrl =
  process.env.NEXT_PUBLIC_BASE_URL ||
  process.env.NEXT_BASE_URL ||
  "localhost:8000";

// Ensure the protocol is included and strip any trailing slashes
export const API_BASE_URL =
  rawBaseUrl.startsWith("http://") || rawBaseUrl.startsWith("https://")
    ? rawBaseUrl.replace(/\/+$/, "")
    : `http://${rawBaseUrl.replace(/\/+$/, "")}`;
