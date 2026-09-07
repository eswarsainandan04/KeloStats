"use client";

import React, { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { API_BASE_URL } from "@/lib/config";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    if (!email.trim() || !password) {
      setError("Please enter both email and password.");
      return;
    }

    setLoading(true);

    try {
      const res = await fetch(`${API_BASE_URL}/api/auth/login`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          email: email.trim(),
          password,
        }),
      });

      const data = await res.json();

      if (!res.ok) {
        throw new Error(data.detail || "Invalid email or password.");
      }

      // Store basic user session info in localStorage
      if (typeof window !== "undefined" && data.user) {
        localStorage.setItem("kelostats_user", JSON.stringify(data.user));
      }

      // Immediately redirect on success without message
      router.push("/dashboard");
    } catch (err: any) {
      setError(err.message || "An unexpected error occurred. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-white text-slate-900 flex flex-col font-sans selection:bg-orange-100 selection:text-orange-600 relative">
      {/* Floating Error Popup (Shows ONLY if login fails) */}
      {error && (
        <div className="fixed top-6 left-1/2 -translate-x-1/2 z-50 w-full max-w-md px-4 transition-all">
          <div className="bg-red-50 border border-red-200 text-red-800 rounded-xl p-4 shadow-xl flex items-center justify-between gap-3">
            <div className="flex items-center gap-2.5">
              <svg className="w-5 h-5 text-red-500 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              <span className="text-sm font-medium">{error}</span>
            </div>
            <button
              onClick={() => setError(null)}
              className="text-red-400 hover:text-red-700 font-bold text-lg leading-none p-1"
            >
              ✕
            </button>
          </div>
        </div>
      )}

      {/* Top Simple Nav */}
      <header className="border-b border-slate-100 py-4 px-6">
        <div className="max-w-6xl mx-auto flex items-center justify-between">
          <Link href="/" className="flex items-center gap-2">

            <span className="font-extrabold text-xl tracking-tight text-slate-900">
              <span className="text-[#FF5148]">KeloStats</span>
            </span>
          </Link>
          <Link
            href="/signup"
            className="text-sm font-semibold text-slate-600 hover:text-[#FF5148] transition-colors"
          >
            Sign Up
          </Link>
        </div>
      </header>

      {/* Main Container */}
      <main className="flex-1 flex items-center justify-center px-6 py-12">
        <div className="w-full max-w-md">
          {/* Card */}
          <div className="bg-white border border-slate-200 rounded-2xl p-8 shadow-sm">
            <div className="text-center mb-8">
              <h1 className="text-2xl sm:text-3xl font-extrabold text-slate-900">
                Welcome back
              </h1>
              <p className="text-sm text-slate-500 mt-2">
                Log in to your <span className="text-[#FF5148] font-semibold">KeloStats</span> account
              </p>
            </div>

            {/* Form */}
            <form onSubmit={handleSubmit} className="space-y-4">
              <div>
                <label className="block text-xs font-bold uppercase tracking-wider text-slate-700 mb-1.5">
                  Email Address
                </label>
                <input
                  type="email"
                  required
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="harper@company.com"
                  className="w-full px-4 py-2.5 rounded-lg border border-slate-200 focus:outline-none focus:ring-2 focus:ring-[#FF5148]/30 focus:border-[#FF5148] text-sm text-slate-900 placeholder:text-slate-400 transition-all"
                />
              </div>

              <div>
                <div className="flex items-center justify-between mb-1.5">
                  <label className="block text-xs font-bold uppercase tracking-wider text-slate-700">
                    Password
                  </label>
                  <a href="#" className="text-xs font-medium text-[#FF5148] hover:underline">
                    Forgot password?
                  </a>
                </div>
                <input
                  type="password"
                  required
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="••••••••"
                  className="w-full px-4 py-2.5 rounded-lg border border-slate-200 focus:outline-none focus:ring-2 focus:ring-[#FF5148]/30 focus:border-[#FF5148] text-sm text-slate-900 placeholder:text-slate-400 transition-all"
                />
              </div>

              <button
                type="submit"
                disabled={loading}
                className="w-full mt-2 py-3 px-4 rounded-lg bg-[#FF5148] hover:bg-[#e64037] text-white font-semibold text-sm shadow-md shadow-[#FF5148]/20 hover:shadow-lg transition-all disabled:opacity-60 disabled:cursor-not-allowed"
              >
                {loading ? "Signing In..." : "Log In"}
              </button>
            </form>

            <div className="mt-6 pt-6 border-t border-slate-100 text-center">
              <p className="text-sm text-slate-600">
                Don't have an account?{" "}
                <Link
                  href="/signup"
                  className="font-semibold text-[#FF5148] hover:underline"
                >
                  Sign Up
                </Link>
              </p>
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}
