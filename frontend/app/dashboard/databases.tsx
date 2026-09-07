"use client";

import React, { useState, useEffect } from "react";
import { API_BASE_URL } from "@/lib/config";

interface DatabaseItem {
  db_id: string;
  database_type: string;
  database_name?: string;
  host: string;
  port: number;
  username: string;
  schema_name?: string;
  service_name?: string;
  ssl_mode?: string;
  created_at?: string;
  display_name?: string;
}

export default function DatabasesPage() {
  const [databases, setDatabases] = useState<DatabaseItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [modalOpen, setModalOpen] = useState(false);
  const [selectedDb, setSelectedDb] = useState<DatabaseItem | null>(null);
  const [connecting, setConnecting] = useState(false);
  const [popupError, setPopupError] = useState<string | null>(null);

  // Delete database states
  const [isDeletingDb, setIsDeletingDb] = useState(false);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [deleteDbError, setDeleteDbError] = useState<string | null>(null);

  // Tab switching: 'postgres' | 'mysql' | 'oracle_sql'
  const [activeDbType, setActiveDbType] = useState<"postgres" | "mysql" | "oracle_sql">("postgres");

  // Form fields
  const [displayName, setDisplayName] = useState("");
  const [host, setHost] = useState("localhost");
  const [port, setPort] = useState(5432);
  const [databaseName, setDatabaseName] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [schemaName, setSchemaName] = useState("public");
  const [serviceName, setServiceName] = useState("");
  const [sslMode, setSslMode] = useState("prefer");

  // Get current user ID
  const getUserId = () => {
    if (typeof window !== "undefined") {
      try {
        const stored = localStorage.getItem("kelostats_user");
        if (stored) {
          const parsed = JSON.parse(stored);
          return parsed.user_id || "00000000-0000-0000-0000-000000000000";
        }
      } catch {
        // Fallback
      }
    }
    return "00000000-0000-0000-0000-000000000000";
  };

  // Switch database tab and set smart defaults
  const handleTabSwitch = (type: "postgres" | "mysql" | "oracle_sql") => {
    setActiveDbType(type);
    setPopupError(null);

    if (type === "postgres") {
      setPort(5432);
      setSchemaName("public");
      setSslMode("prefer");
    } else if (type === "mysql") {
      setPort(3306);
      setSchemaName("");
      setSslMode("prefer");
    } else if (type === "oracle_sql") {
      setPort(1521);
      setServiceName("ORCLCDB");
      setSchemaName("");
      setSslMode("prefer");
    }
  };

  // Fetch connected databases
  const fetchDatabases = async () => {
    const userId = getUserId();
    try {
      const res = await fetch(`${API_BASE_URL}/api/databases/database_info?user_id=${userId}`);
      if (res.ok) {
        const data = await res.json();
        setDatabases(data.databases || []);
      }
    } catch (err) {
      console.error("Error fetching databases:", err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchDatabases();
  }, []);

  // Submit connect database form
  const handleConnectDatabase = async (e: React.FormEvent) => {
    e.preventDefault();
    setPopupError(null);
    setConnecting(true);

    const userId = getUserId();

    const payload: any = {
      user_id: userId,
      database_type: activeDbType,
      display_name: displayName.trim() || databaseName.trim() || serviceName.trim(),
      host: host.trim(),
      port: Number(port),
      username: username.trim(),
      password: password,
      ssl_mode: sslMode,
    };

    if (activeDbType === "postgres") {
      payload.database_name = databaseName.trim();
      payload.schema_name = schemaName.trim() || "public";
    } else if (activeDbType === "mysql") {
      payload.database_name = databaseName.trim();
    } else if (activeDbType === "oracle_sql") {
      payload.service_name = serviceName.trim();
      if (schemaName.trim()) {
        payload.schema_name = schemaName.trim();
      }
    }

    try {
      const res = await fetch(`${API_BASE_URL}/api/databases/connect`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(payload),
      });

      const data = await res.json();

      if (!res.ok) {
        throw new Error(data.detail || data.message || "Failed to connect to database.");
      }

      // Success: Close modal and refresh list
      setModalOpen(false);
      setDisplayName("");
      setPassword("");
      await fetchDatabases();
    } catch (err: any) {
      setPopupError(err.message || "Connection failed. Please check host, port, and credentials.");
    } finally {
      setConnecting(false);
    }
  };

  // Delete connected database
  const handleDeleteDatabase = async () => {
    if (!selectedDb) return;
    setIsDeletingDb(true);
    setDeleteDbError(null);
    const userId = getUserId();
    try {
      const res = await fetch(`${API_BASE_URL}/api/databases/delete`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          db_id: selectedDb.db_id,
          user_id: userId,
        }),
      });

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || errData.message || "Failed to delete database connection.");
      }

      // Success: Close modal, reset state, and refresh list
      setSelectedDb(null);
      setShowDeleteConfirm(false);
      await fetchDatabases();
    } catch (err: any) {
      console.error("Error deleting database:", err);
      setDeleteDbError(err.message || "Failed to delete database connection.");
    } finally {
      setIsDeletingDb(false);
    }
  };

  return (
    <div className="space-y-6 relative">
      {/* Floating Error Popup (Shows ONLY if connection fails) */}
      {popupError && (
        <div className="fixed top-6 left-1/2 -translate-x-1/2 z-50 w-full max-w-lg px-4 transition-all">
          <div className="bg-red-50 border border-red-200 text-red-800 rounded-xl p-4 shadow-2xl flex items-start justify-between gap-3">
            <div className="flex items-start gap-2.5">
              <svg className="w-5 h-5 text-red-500 shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              <div>
                <p className="text-sm font-bold text-red-900">Database Connection Failed</p>
                <p className="text-xs text-red-700 mt-0.5 leading-relaxed">{popupError}</p>
              </div>
            </div>
            <button
              onClick={() => setPopupError(null)}
              className="text-red-400 hover:text-red-700 font-bold text-lg leading-none p-1 shrink-0"
            >
              ✕
            </button>
          </div>
        </div>
      )}

      {/* Header Bar */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-extrabold text-slate-900">Connected Databases</h1>
          <p className="text-sm text-slate-500 mt-1">
            Connect your PostgreSQL, MySQL, or Oracle database to enable automated schema extraction and AI presentation synthesis.
          </p>
        </div>
        <button
          onClick={() => {
            setPopupError(null);
            setModalOpen(true);
          }}
          className="px-5 py-2.5 rounded-lg text-sm font-semibold text-white bg-[#FF5148] hover:bg-[#e64037] shadow-sm hover:shadow-md transition-all flex items-center justify-center gap-2 shrink-0"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
          </svg>
          <span>Add Database</span>
        </button>
      </div>

      {/* Database Cards List */}
      {loading ? (
        <div className="p-12 text-center text-slate-400 text-sm">
          Loading connected databases...
        </div>
      ) : databases.length === 0 ? (
        <div className="p-12 text-center rounded-2xl border-2 border-dashed border-slate-200 bg-slate-50/50">
          <div className="w-12 h-12 rounded-xl bg-orange-100 text-[#FF5148] flex items-center justify-center mx-auto mb-4">
            <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4" />
            </svg>
          </div>
          <h3 className="font-bold text-slate-800 text-base">No databases connected yet</h3>
          <p className="text-sm text-slate-500 max-w-md mx-auto mt-1 mb-6">
            Connect your first PostgreSQL, MySQL, or Oracle SQL database to start generating presentations from telemetry.
          </p>
          <button
            onClick={() => setModalOpen(true)}
            className="px-5 py-2.5 rounded-lg text-sm font-semibold text-white bg-[#FF5148] hover:bg-[#e64037] shadow-sm transition-all"
          >
            Connect Your First Database
          </button>
        </div>
      ) : (
        <div className="flex flex-wrap items-start gap-10 sm:gap-12 pt-4">
          {databases.map((db) => {
            const dbTitle = db.display_name || db.database_name || db.service_name || "Database";
            const subTitle = db.database_name || db.service_name;
            return (
              <div key={db.db_id} className="flex flex-col items-center">
                <button
                  type="button"
                  onClick={() => {
                    setSelectedDb(db);
                    setShowDeleteConfirm(false);
                    setDeleteDbError(null);
                  }}
                  className="w-32 h-32 sm:w-36 sm:h-36 p-1 hover:scale-105 active:scale-95 transition-transform duration-200 flex items-center justify-center cursor-pointer focus:outline-none"
                  title={`Click to view ${dbTitle} info`}
                >
                  <img
                    src="/database.png"
                    alt={dbTitle}
                    className="w-full h-full object-contain pointer-events-none"
                  />
                </button>
                <span
                  className="mt-3 text-base font-bold text-slate-800 max-w-[160px] text-center truncate"
                  title={dbTitle}
                >
                  {dbTitle}
                </span>
                {subTitle && subTitle !== dbTitle && (
                  <span
                    className="text-[11px] text-slate-400 max-w-[160px] text-center truncate mt-0.5"
                    title={subTitle}
                  >
                    {subTitle}
                  </span>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* ========================================================================= */}
      {/* DATABASE DETAILS POPUP MODAL */}
      {/* ========================================================================= */}
      {selectedDb && (
        <div
          className="fixed inset-0 z-50 bg-black/40 backdrop-blur-sm flex items-center justify-center p-4 animate-in fade-in duration-150"
          onClick={() => setSelectedDb(null)}
        >
          <div
            className="bg-white border border-slate-200 rounded-2xl w-full max-w-md shadow-2xl overflow-hidden animate-in zoom-in-95 duration-200"
            onClick={(e) => e.stopPropagation()}
          >
            {/* Modal Header */}
            <div className="px-6 py-4 border-b border-slate-100 flex items-center justify-between">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 flex items-center justify-center shrink-0">
                  <img src="/database.png" alt="Database" className="w-full h-full object-contain" />
                </div>
                <div>
                  <h2 className="text-base font-bold text-slate-900 leading-tight">
                    {selectedDb.display_name || selectedDb.database_name || selectedDb.service_name || "Database Info"}
                  </h2>
                  <span className="inline-block mt-0.5 text-[11px] font-semibold text-emerald-600 bg-emerald-50 px-2 py-0.5 rounded-full border border-emerald-200">
                    Active
                  </span>
                </div>
              </div>
              <button
                type="button"
                onClick={() => setSelectedDb(null)}
                className="w-8 h-8 rounded-lg hover:bg-slate-100 text-slate-400 hover:text-slate-700 flex items-center justify-center font-bold text-base transition-colors"
              >
                ✕
              </button>
            </div>

            {/* Details List */}
            <div className="p-6 space-y-3 text-sm">
              <div className="flex items-center justify-between py-1.5 border-b border-slate-100">
                <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">Type</span>
                <span className="font-semibold text-slate-800 capitalize">{selectedDb.database_type}</span>
              </div>

              {selectedDb.display_name && (
                <div className="flex items-center justify-between py-1.5 border-b border-slate-100">
                  <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">Display Name</span>
                  <span className="font-semibold text-slate-800">{selectedDb.display_name}</span>
                </div>
              )}

              {selectedDb.database_name && (
                <div className="flex items-center justify-between py-1.5 border-b border-slate-100">
                  <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">Database Name</span>
                  <span className="font-mono font-medium text-slate-800">{selectedDb.database_name}</span>
                </div>
              )}

              {selectedDb.service_name && (
                <div className="flex items-center justify-between py-1.5 border-b border-slate-100">
                  <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">Service Name</span>
                  <span className="font-mono font-medium text-slate-800">{selectedDb.service_name}</span>
                </div>
              )}

              <div className="flex items-center justify-between py-1.5 border-b border-slate-100">
                <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">Host</span>
                <span className="font-mono font-medium text-slate-800">{selectedDb.host}</span>
              </div>

              <div className="flex items-center justify-between py-1.5 border-b border-slate-100">
                <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">Port</span>
                <span className="font-mono font-medium text-slate-800">{selectedDb.port}</span>
              </div>

              <div className="flex items-center justify-between py-1.5 border-b border-slate-100">
                <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">Username</span>
                <span className="font-mono font-medium text-slate-800">{selectedDb.username}</span>
              </div>

              {selectedDb.schema_name && (
                <div className="flex items-center justify-between py-1.5 border-b border-slate-100">
                  <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">Schema</span>
                  <span className="font-mono font-medium text-slate-800">{selectedDb.schema_name}</span>
                </div>
              )}

              <div className="flex items-center justify-between py-1.5 border-b border-slate-100">
                <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">SSL Mode</span>
                <span className="font-mono font-medium text-slate-800">{selectedDb.ssl_mode || "prefer"}</span>
              </div>
            </div>

            {/* Official Confirmation Step (if user clicked delete) */}
            {showDeleteConfirm && (
              <div className="mx-6 mb-4 p-4 bg-red-50/80 border border-red-200 rounded-xl space-y-3 animate-in fade-in duration-150">
                <div className="flex items-start gap-3">
                  <div className="w-8 h-8 rounded-lg bg-red-100 text-red-600 flex items-center justify-center shrink-0">
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                    </svg>
                  </div>
                  <div>
                    <h4 className="text-xs font-bold text-red-900 uppercase tracking-wider">Confirm Deletion</h4>
                    <p className="text-xs text-red-700 mt-1 leading-relaxed">
                      Are you sure you want to permanently delete this database connection? Cached schemas and saved credentials will be removed.
                    </p>
                  </div>
                </div>

                {deleteDbError && (
                  <div className="p-2 bg-red-100 border border-red-300 rounded-lg text-xs text-red-800 font-medium">
                    {deleteDbError}
                  </div>
                )}
              </div>
            )}

            {/* Footer */}
            <div className="px-6 py-3.5 bg-slate-50 border-t border-slate-100 flex items-center justify-between">
              {showDeleteConfirm ? (
                <>
                  <button
                    type="button"
                    disabled={isDeletingDb}
                    onClick={() => {
                      setShowDeleteConfirm(false);
                      setDeleteDbError(null);
                    }}
                    className="px-3.5 py-2 text-xs font-semibold text-slate-600 hover:text-slate-800 hover:bg-slate-200/60 rounded-lg transition-colors cursor-pointer disabled:opacity-50"
                  >
                    Cancel
                  </button>

                  <button
                    type="button"
                    disabled={isDeletingDb}
                    onClick={handleDeleteDatabase}
                    className="px-4 py-2 text-xs font-bold text-white bg-red-600 hover:bg-red-700 active:bg-red-800 rounded-lg shadow-xs hover:shadow-md transition-all flex items-center gap-2 cursor-pointer disabled:opacity-50"
                  >
                    {isDeletingDb ? (
                      <>
                        <svg className="animate-spin w-3.5 h-3.5 text-white" fill="none" viewBox="0 0 24 24">
                          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z" />
                        </svg>
                        <span>Deleting...</span>
                      </>
                    ) : (
                      <>
                        <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                        </svg>
                        <span>Confirm Delete</span>
                      </>
                    )}
                  </button>
                </>
              ) : (
                <>
                  <button
                    type="button"
                    onClick={() => {
                      setDeleteDbError(null);
                      setShowDeleteConfirm(true);
                    }}
                    className="px-3 py-1.5 text-xs font-semibold text-red-600 hover:text-red-700 hover:bg-red-50 border border-red-200 hover:border-red-300 rounded-lg transition-colors flex items-center gap-1.5 cursor-pointer"
                  >
                    <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                    </svg>
                    <span>Delete Database</span>
                  </button>

                  <button
                    type="button"
                    onClick={() => {
                      setSelectedDb(null);
                      setShowDeleteConfirm(false);
                    }}
                    className="px-4 py-2 text-xs font-semibold text-slate-700 bg-white border border-slate-200 hover:bg-slate-100 rounded-lg transition-colors cursor-pointer"
                  >
                    Close
                  </button>
                </>
              )}
            </div>
          </div>
        </div>
      )}

      {/* ========================================================================= */}
      {/* ADD DATABASE POPUP MODAL */}
      {/* ========================================================================= */}
      {modalOpen && (
        <div className="fixed inset-0 z-50 bg-black/40 backdrop-blur-sm flex items-center justify-center p-4 animate-in fade-in duration-150">
          <div className="bg-white border border-slate-200 rounded-2xl w-full max-w-xl shadow-2xl overflow-hidden animate-in zoom-in-95 duration-200">
            {/* Modal Header */}
            <div className="px-6 py-4 border-b border-slate-100 flex items-center justify-between">
              <div>
                <h2 className="text-lg font-bold text-slate-900">Connect Database</h2>
                <p className="text-xs text-slate-500">
                  Select your database engine and enter credentials to verify connection.
                </p>
              </div>
              <button
                onClick={() => setModalOpen(false)}
                className="w-8 h-8 rounded-lg hover:bg-slate-100 text-slate-400 hover:text-slate-700 flex items-center justify-center font-bold text-base transition-colors"
              >
                ✕
              </button>
            </div>

            {/* TAB SWITCHING: MySQL | PostgreSQL | Oracle SQL */}
            <div className="px-6 pt-5">
              <div className="grid grid-cols-3 p-1 rounded-xl bg-slate-100 border border-slate-200 text-xs font-semibold">
                <button
                  type="button"
                  onClick={() => handleTabSwitch("postgres")}
                  className={`py-2 rounded-lg transition-all flex items-center justify-center gap-1.5 ${
                    activeDbType === "postgres"
                      ? "bg-white text-[#FF5148] shadow-sm font-bold"
                      : "text-slate-600 hover:text-slate-900"
                  }`}
                >
                  <span className="w-2 h-2 rounded-full bg-blue-500" />
                  <span>PostgreSQL</span>
                </button>

                <button
                  type="button"
                  onClick={() => handleTabSwitch("mysql")}
                  className={`py-2 rounded-lg transition-all flex items-center justify-center gap-1.5 ${
                    activeDbType === "mysql"
                      ? "bg-white text-[#FF5148] shadow-sm font-bold"
                      : "text-slate-600 hover:text-slate-900"
                  }`}
                >
                  <span className="w-2 h-2 rounded-full bg-amber-500" />
                  <span>MySQL</span>
                </button>

                <button
                  type="button"
                  onClick={() => handleTabSwitch("oracle_sql")}
                  className={`py-2 rounded-lg transition-all flex items-center justify-center gap-1.5 ${
                    activeDbType === "oracle_sql"
                      ? "bg-white text-[#FF5148] shadow-sm font-bold"
                      : "text-slate-600 hover:text-slate-900"
                  }`}
                >
                  <span className="w-2 h-2 rounded-full bg-red-500" />
                  <span>Oracle SQL</span>
                </button>
              </div>
            </div>

            {/* Form Input Fields */}
            <form onSubmit={handleConnectDatabase} className="p-6 space-y-4">
              {/* Display Name */}
              <div>
                <label className="block text-xs font-bold uppercase tracking-wider text-slate-700 mb-1">
                  Display Name
                </label>
                <input
                  type="text"
                  required
                  value={displayName}
                  onChange={(e) => setDisplayName(e.target.value)}
                  placeholder={
                    activeDbType === "postgres"
                      ? "e.g. Production Analytics DB"
                      : activeDbType === "mysql"
                      ? "e.g. E-Commerce Store DB"
                      : "e.g. Enterprise Warehouse DB"
                  }
                  className="w-full px-3.5 py-2 rounded-lg border border-slate-200 focus:outline-none focus:ring-2 focus:ring-[#FF5148]/30 focus:border-[#FF5148] text-sm text-slate-900"
                />
              </div>

              {/* Host & Port */}
              <div className="grid grid-cols-3 gap-3">
                <div className="col-span-2">
                  <label className="block text-xs font-bold uppercase tracking-wider text-slate-700 mb-1">
                    Host / Server Address
                  </label>
                  <input
                    type="text"
                    required
                    value={host}
                    onChange={(e) => setHost(e.target.value)}
                    placeholder="localhost or db.example.com"
                    className="w-full px-3.5 py-2 rounded-lg border border-slate-200 focus:outline-none focus:ring-2 focus:ring-[#FF5148]/30 focus:border-[#FF5148] text-sm text-slate-900"
                  />
                </div>
                <div>
                  <label className="block text-xs font-bold uppercase tracking-wider text-slate-700 mb-1">
                    Port
                  </label>
                  <input
                    type="number"
                    required
                    value={port}
                    onChange={(e) => setPort(Number(e.target.value))}
                    className="w-full px-3.5 py-2 rounded-lg border border-slate-200 focus:outline-none focus:ring-2 focus:ring-[#FF5148]/30 focus:border-[#FF5148] text-sm text-slate-900"
                  />
                </div>
              </div>

              {/* Database Name or Service Name */}
              {activeDbType !== "oracle_sql" ? (
                <div>
                  <label className="block text-xs font-bold uppercase tracking-wider text-slate-700 mb-1">
                    Database Name
                  </label>
                  <input
                    type="text"
                    required
                    value={databaseName}
                    onChange={(e) => setDatabaseName(e.target.value)}
                    placeholder={activeDbType === "postgres" ? "kelostats" : "mydb"}
                    className="w-full px-3.5 py-2 rounded-lg border border-slate-200 focus:outline-none focus:ring-2 focus:ring-[#FF5148]/30 focus:border-[#FF5148] text-sm text-slate-900"
                  />
                </div>
              ) : (
                <div>
                  <label className="block text-xs font-bold uppercase tracking-wider text-slate-700 mb-1">
                    Oracle Service Name (SID / Service)
                  </label>
                  <input
                    type="text"
                    required
                    value={serviceName}
                    onChange={(e) => setServiceName(e.target.value)}
                    placeholder="ORCLCDB or XE"
                    className="w-full px-3.5 py-2 rounded-lg border border-slate-200 focus:outline-none focus:ring-2 focus:ring-[#FF5148]/30 focus:border-[#FF5148] text-sm text-slate-900"
                  />
                </div>
              )}

              {/* Username & Password */}
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-bold uppercase tracking-wider text-slate-700 mb-1">
                    Username
                  </label>
                  <input
                    type="text"
                    required
                    value={username}
                    onChange={(e) => setUsername(e.target.value)}
                    placeholder={activeDbType === "postgres" ? "postgres" : activeDbType === "mysql" ? "root" : "system"}
                    className="w-full px-3.5 py-2 rounded-lg border border-slate-200 focus:outline-none focus:ring-2 focus:ring-[#FF5148]/30 focus:border-[#FF5148] text-sm text-slate-900"
                  />
                </div>
                <div>
                  <label className="block text-xs font-bold uppercase tracking-wider text-slate-700 mb-1">
                    Password
                  </label>
                  <input
                    type="password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    placeholder="••••••••"
                    className="w-full px-3.5 py-2 rounded-lg border border-slate-200 focus:outline-none focus:ring-2 focus:ring-[#FF5148]/30 focus:border-[#FF5148] text-sm text-slate-900"
                  />
                </div>
              </div>

              {/* Schema Name & SSL Mode */}
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-bold uppercase tracking-wider text-slate-700 mb-1">
                    Schema Name (Optional)
                  </label>
                  <input
                    type="text"
                    value={schemaName}
                    onChange={(e) => setSchemaName(e.target.value)}
                    placeholder="public"
                    className="w-full px-3.5 py-2 rounded-lg border border-slate-200 focus:outline-none focus:ring-2 focus:ring-[#FF5148]/30 focus:border-[#FF5148] text-sm text-slate-900"
                  />
                </div>
                <div>
                  <label className="block text-xs font-bold uppercase tracking-wider text-slate-700 mb-1">
                    SSL Mode
                  </label>
                  <select
                    value={sslMode}
                    onChange={(e) => setSslMode(e.target.value)}
                    className="w-full px-3.5 py-2 rounded-lg border border-slate-200 focus:outline-none focus:ring-2 focus:ring-[#FF5148]/30 focus:border-[#FF5148] text-sm text-slate-900 bg-white"
                  >
                    <option value="prefer">prefer</option>
                    <option value="require">require</option>
                    <option value="disable">disable</option>
                  </select>
                </div>
              </div>

              {/* Action Buttons */}
              <div className="mt-6 pt-4 border-t border-slate-100 flex items-center justify-end gap-3">
                <button
                  type="button"
                  onClick={() => setModalOpen(false)}
                  className="px-4 py-2 text-sm font-semibold text-slate-600 hover:text-slate-800 hover:bg-slate-100 rounded-lg transition-colors"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={connecting}
                  className="px-5 py-2 text-sm font-semibold text-white bg-[#FF5148] hover:bg-[#e64037] rounded-lg shadow-sm hover:shadow-md transition-all disabled:opacity-60 disabled:cursor-not-allowed flex items-center gap-2"
                >
                  {connecting ? (
                    <>
                      <svg className="animate-spin -ml-1 mr-2 h-4 w-4 text-white" fill="none" viewBox="0 0 24 24">
                        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z" />
                      </svg>
                      <span>Verifying & Connecting...</span>
                    </>
                  ) : (
                    <span>Connect Database</span>
                  )}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
