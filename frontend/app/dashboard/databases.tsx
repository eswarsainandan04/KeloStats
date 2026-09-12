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

  // Popups state
  const [schemaModalDb, setSchemaModalDb] = useState<DatabaseItem | null>(null);
  const [selectedTable, setSelectedTable] = useState<any | null>(null);
  const [tableTab, setTableTab] = useState<"schema_info" | "sample_data">("schema_info");
  const [schemaData, setSchemaData] = useState<any>(null);
  const [loadingSchema, setLoadingSchema] = useState(false);
  const [schemaError, setSchemaError] = useState<string | null>(null);

  // Helper to get normalized database engine info and small icon
  const getEngineInfo = (type: string) => {
    const norm = (type || "").toLowerCase().trim();
    if (norm === "mysql") {
      return { name: "MySQL", icon: "/mysql.png" };
    }
    if (norm === "oracle_sql" || norm === "oracle") {
      return { name: "Oracle SQL", icon: "/oracle.png" };
    }
    return { name: "PostgreSQL", icon: "/postgres.png" };
  };

  // Fetch database schema from /api/database/schema
  const fetchDatabaseSchema = async (dbId: string) => {
    setLoadingSchema(true);
    setSchemaError(null);
    try {
      const res = await fetch(`${API_BASE_URL}/api/database/schema?database_id=${dbId}`);
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || "Failed to load database schema.");
      }
      const data = await res.json();
      setSchemaData(data);
    } catch (err: any) {
      console.error("Error fetching schema:", err);
      setSchemaError(err.message || "Failed to load database schema.");
    } finally {
      setLoadingSchema(false);
    }
  };

  // Open fresh schema popup when clicking Schema button
  const handleOpenSchema = (db: DatabaseItem) => {
    setSelectedDb(null);
    setSchemaModalDb(db);
    setSelectedTable(null);
    setSchemaData(null);
    fetchDatabaseSchema(db.db_id);
  };

  // Modal Step: 'select' (initial engine picker) | 'form' (credential entry)
  const [modalStep, setModalStep] = useState<"select" | "form">("select");

  // Selected database type: 'postgres' | 'mysql' | 'oracle_sql'
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

  // Open Add Database modal reset to initial selection
  const openAddModal = () => {
    setPopupError(null);
    setModalStep("select");
    setDisplayName("");
    setPassword("");
    setModalOpen(true);
  };

  // Handle engine selection from initial step
  const handleSelectEngine = (type: "postgres" | "mysql" | "oracle_sql") => {
    handleTabSwitch(type);
    setModalStep("form");
  };

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
      setModalStep("select");
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
          onClick={openAddModal}
          className="px-5 py-2.5 rounded-lg text-sm font-semibold text-white bg-[#FF5148] hover:bg-[#e64037] shadow-sm hover:shadow-md transition-all flex items-center justify-center gap-2 shrink-0 cursor-pointer"
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
            onClick={openAddModal}
            className="px-5 py-2.5 rounded-lg text-sm font-semibold text-white bg-[#FF5148] hover:bg-[#e64037] shadow-sm transition-all cursor-pointer"
          >
            Connect Your First Database
          </button>
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-6 pt-4">
          {databases.map((db) => {
            const dbTitle = db.display_name || db.database_name || db.service_name || "Database";
            const subTitle = db.database_name || db.service_name;
            const engine = getEngineInfo(db.database_type);

            return (
              <div
                key={db.db_id}
                onClick={() => {
                  setSelectedDb(db);
                  setShowDeleteConfirm(false);
                  setDeleteDbError(null);
                }}
                className="group relative bg-white border border-slate-200 hover:border-[#FF5148] rounded-2xl p-5 shadow-xs hover:shadow-xl hover:-translate-y-1 transition-all duration-200 cursor-pointer flex flex-col justify-between items-center text-center aspect-square"
              >
                {/* Top: Database Type with small icon & Active dot */}
                <div className="w-full flex items-center justify-between">
                  <div className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-slate-50 border border-slate-200/80 text-[11px] font-semibold text-slate-700">
                    <img src={engine.icon} alt={engine.name} className="w-3.5 h-3.5 object-contain" />
                    <span>{engine.name}</span>
                  </div>
                  <span className="w-2 h-2 rounded-full bg-emerald-500 shadow-xs" title="Active" />
                </div>

                {/* Center: Database 3D Icon */}
                <div className="w-20 h-20 sm:w-24 sm:h-24 p-1 my-auto flex items-center justify-center group-hover:scale-110 transition-transform duration-200">
                  <img
                    src="/database.png"
                    alt={dbTitle}
                    className="w-full h-full object-contain pointer-events-none drop-shadow-sm"
                  />
                </div>

                {/* Bottom: Database Title & Hover action */}
                <div className="w-full">
                  <h3
                    className="text-sm font-bold text-slate-800 group-hover:text-[#FF5148] transition-colors truncate"
                    title={dbTitle}
                  >
                    {dbTitle}
                  </h3>
                  {subTitle && subTitle !== dbTitle && (
                    <p className="text-[11px] text-slate-400 truncate mt-0.5" title={subTitle}>
                      {subTitle}
                    </p>
                  )}
                  <span className="inline-flex items-center gap-1 text-[11px] font-semibold text-[#FF5148] opacity-0 group-hover:opacity-100 transition-opacity mt-1">
                    View Details &rarr;
                  </span>
                </div>
              </div>
            );
          })}
        </div>
      )}
      {/* ========================================================================= */}
      {/* 1. OVERVIEW POPUP MODAL (Clean, Connection details only, no tabs/types) */}
      {/* ========================================================================= */}
      {selectedDb && !schemaModalDb && !selectedTable && (
        <div
          className="fixed inset-0 z-50 bg-black/40 backdrop-blur-sm flex items-center justify-center p-4 animate-in fade-in duration-150"
          onClick={() => {
            setSelectedDb(null);
            setShowDeleteConfirm(false);
          }}
        >
          <div
            className="bg-white border border-slate-200 rounded-2xl w-full max-w-xl h-[460px] shadow-2xl overflow-hidden animate-in zoom-in-95 duration-200 flex flex-col"
            onClick={(e) => e.stopPropagation()}
          >
            {/* Modal Header */}
            <div className="px-6 py-4 border-b border-slate-100 flex items-center justify-between shrink-0">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 flex items-center justify-center shrink-0">
                  <img src="/database.png" alt="Database" className="w-full h-full object-contain" />
                </div>
                <div>
                  <div className="flex items-center gap-2">
                    <h2 className="text-base font-bold text-slate-900 leading-tight">
                      {selectedDb.display_name || selectedDb.database_name || selectedDb.service_name || "Database Info"}
                    </h2>
                    <span className="inline-block text-[11px] font-semibold text-emerald-600 bg-emerald-50 px-2 py-0.5 rounded-full border border-emerald-200">
                      Active
                    </span>
                  </div>
                  {/* Database type with small icon */}
                  <div className="inline-flex items-center gap-1.5 mt-1 px-2 py-0.5 rounded-full bg-slate-100 border border-slate-200 text-[11px] font-medium text-slate-700">
                    <img
                      src={getEngineInfo(selectedDb.database_type).icon}
                      alt={getEngineInfo(selectedDb.database_type).name}
                      className="w-3.5 h-3.5 object-contain"
                    />
                    <span>{getEngineInfo(selectedDb.database_type).name}</span>
                  </div>
                </div>
              </div>
              <button
                type="button"
                onClick={() => {
                  setSelectedDb(null);
                  setShowDeleteConfirm(false);
                }}
                className="w-8 h-8 rounded-lg hover:bg-slate-100 text-slate-400 hover:text-slate-700 flex items-center justify-center font-bold text-base transition-colors cursor-pointer"
              >
                ✕
              </button>
            </div>

            {/* Connection Details: NO Type, NO Display Name, NO Tabs */}
            <div className="p-6 space-y-3 text-sm flex-1 overflow-y-auto">
              {selectedDb.database_name && (
                <div className="flex items-center justify-between py-2 border-b border-slate-100">
                  <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">Database Name</span>
                  <span className="font-mono font-medium text-slate-800">{selectedDb.database_name}</span>
                </div>
              )}

              {selectedDb.service_name && (
                <div className="flex items-center justify-between py-2 border-b border-slate-100">
                  <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">Service Name</span>
                  <span className="font-mono font-medium text-slate-800">{selectedDb.service_name}</span>
                </div>
              )}

              <div className="flex items-center justify-between py-2 border-b border-slate-100">
                <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">Host</span>
                <span className="font-mono font-medium text-slate-800">{selectedDb.host}</span>
              </div>

              <div className="flex items-center justify-between py-2 border-b border-slate-100">
                <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">Port</span>
                <span className="font-mono font-medium text-slate-800">{selectedDb.port}</span>
              </div>

              <div className="flex items-center justify-between py-2 border-b border-slate-100">
                <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">Username</span>
                <span className="font-mono font-medium text-slate-800">{selectedDb.username}</span>
              </div>

              {selectedDb.schema_name && (
                <div className="flex items-center justify-between py-2 border-b border-slate-100">
                  <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">Schema</span>
                  <span className="font-mono font-medium text-slate-800">{selectedDb.schema_name}</span>
                </div>
              )}

              <div className="flex items-center justify-between py-2 border-b border-slate-100">
                <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">SSL Mode</span>
                <span className="font-mono font-medium text-slate-800">{selectedDb.ssl_mode || "prefer"}</span>
              </div>
            </div>

            {/* Confirmation Step if user clicked delete */}
            {showDeleteConfirm && (
              <div className="mx-6 mb-4 p-4 bg-red-50/80 border border-red-200 rounded-xl space-y-3 shrink-0 animate-in fade-in duration-150">
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

            {/* Footer with Delete, Schema, and Close */}
            <div className="px-6 py-3.5 bg-slate-50 border-t border-slate-100 flex items-center justify-between shrink-0">
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
                    {isDeletingDb ? "Deleting..." : "Confirm Delete"}
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

                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      onClick={() => handleOpenSchema(selectedDb)}
                      className="px-4 py-2 text-xs font-semibold text-white bg-slate-900 hover:bg-black rounded-lg shadow-sm transition-all flex items-center gap-1.5 cursor-pointer"
                    >
                      <svg className="w-3.5 h-3.5 text-orange-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 10h16M4 14h16M4 18h16" />
                      </svg>
                      <span>Schema</span>
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
                  </div>
                </>
              )}
            </div>
          </div>
        </div>
      )}

      {/* ========================================================================= */}
      {/* 2. FRESH SCHEMA POPUP: Tables in Database */}
      {/* ========================================================================= */}
      {schemaModalDb && !selectedTable && (
        <div
          className="fixed inset-0 z-50 bg-black/40 backdrop-blur-sm flex items-center justify-center p-4 animate-in fade-in duration-150"
          onClick={() => setSchemaModalDb(null)}
        >
          <div
            className="bg-white border border-slate-200 rounded-2xl w-full max-w-xl h-[460px] shadow-2xl overflow-hidden animate-in zoom-in-95 duration-200 flex flex-col"
            onClick={(e) => e.stopPropagation()}
          >
            {/* Modal Header */}
            <div className="px-6 py-4 border-b border-slate-100 flex items-center justify-between shrink-0">
              <div className="flex items-center gap-3">
                <div className="w-9 h-9 flex items-center justify-center shrink-0">
                  <img src="/database.png" alt="Database" className="w-full h-full object-contain" />
                </div>
                <div>
                  <h2 className="text-base font-bold text-slate-900 leading-tight">
                    {schemaModalDb.display_name || schemaModalDb.database_name || "Database"} - Tables
                  </h2>
                  <p className="text-xs text-slate-400 mt-0.5">Database Schema</p>
                </div>
              </div>
              <button
                type="button"
                onClick={() => setSchemaModalDb(null)}
                className="w-8 h-8 rounded-lg hover:bg-slate-100 text-slate-400 hover:text-slate-700 flex items-center justify-center font-bold text-base transition-colors cursor-pointer"
              >
                ✕
              </button>
            </div>

            {/* Modal Body: Tables List */}
            <div className="p-6 overflow-y-auto flex-1">
              {loadingSchema ? (
                <div className="h-full flex flex-col items-center justify-center text-center text-slate-500">
                  <div className="w-8 h-8 border-3 border-orange-200 border-t-[#FF5148] rounded-full animate-spin mb-3" />
                  <p className="text-sm font-semibold text-slate-700">Loading Tables...</p>
                </div>
              ) : schemaError ? (
                <div className="p-4 rounded-xl bg-red-50 border border-red-200 text-red-700 text-xs">
                  <p className="font-bold text-red-900 mb-1">Failed to load schema</p>
                  <p>{schemaError}</p>
                  <button
                    type="button"
                    onClick={() => fetchDatabaseSchema(schemaModalDb.db_id)}
                    className="mt-3 px-3 py-1.5 rounded-lg bg-red-600 text-white font-semibold text-xs hover:bg-red-700 transition-colors cursor-pointer"
                  >
                    Retry Loading
                  </button>
                </div>
              ) : !schemaData || !schemaData.tables || schemaData.tables.length === 0 ? (
                <div className="h-full flex items-center justify-center text-slate-500 text-sm">
                  No tables found in this database.
                </div>
              ) : (
                <div className="grid grid-cols-2 sm:grid-cols-3 gap-3.5">
                  {schemaData.tables.map((table: any, idx: number) => (
                    <div
                      key={idx}
                      className="p-4 rounded-xl border border-slate-200 bg-white hover:border-slate-300 hover:shadow-xs flex flex-col items-center justify-center text-center gap-2.5 transition-all"
                    >
                      {/* small size table_name */}
                      <span className="text-xs font-mono font-bold text-slate-800 break-all leading-tight">
                        {table.table_name}
                      </span>

                      {/* table.png button below table name that's it - the img itself is a button */}
                      <button
                        type="button"
                        onClick={() => {
                          setSelectedTable(table);
                          setTableTab("schema_info");
                        }}
                        className="p-1.5 rounded-xl hover:bg-slate-100 active:scale-95 transition-all cursor-pointer"
                        title={`Open ${table.table_name}`}
                      >
                        <img
                          src="/table.png"
                          alt="Table"
                          className="w-12 h-12 object-contain hover:scale-105 transition-transform"
                        />
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Footer */}
            <div className="px-6 py-3.5 bg-slate-50 border-t border-slate-100 flex items-center justify-between shrink-0">
              <button
                type="button"
                onClick={() => {
                  setSelectedDb(schemaModalDb);
                  setSchemaModalDb(null);
                }}
                className="px-3.5 py-1.5 text-xs font-semibold text-slate-600 hover:text-slate-800 hover:bg-slate-200/60 rounded-lg transition-colors cursor-pointer"
              >
                &larr; Back to Overview
              </button>
              <button
                type="button"
                onClick={() => setSchemaModalDb(null)}
                className="px-4 py-1.5 text-xs font-semibold text-slate-700 bg-white border border-slate-200 hover:bg-slate-100 rounded-lg transition-colors cursor-pointer"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ========================================================================= */}
      {/* 3. TABLE DETAILS POPUP: Schema Info & Sample Data Tab Switching */}
      {/* ========================================================================= */}
      {selectedTable && (
        <div
          className="fixed inset-0 z-50 bg-black/40 backdrop-blur-sm flex items-center justify-center p-4 animate-in fade-in duration-150"
          onClick={() => setSelectedTable(null)}
        >
          <div
            className="bg-white border border-slate-200 rounded-2xl w-full max-w-xl h-[460px] shadow-2xl overflow-hidden animate-in zoom-in-95 duration-200 flex flex-col"
            onClick={(e) => e.stopPropagation()}
          >
            {/* Modal Header */}
            <div className="px-6 py-4 border-b border-slate-100 flex items-center justify-between shrink-0">
              <div className="flex items-center gap-3">
                <div className="w-8 h-8 rounded-lg bg-slate-100 p-1.5 flex items-center justify-center shrink-0 border border-slate-200">
                  <img src="/table.png" alt="Table" className="w-full h-full object-contain" />
                </div>
                <div>
                  <h2 className="text-base font-bold text-slate-900 font-mono leading-tight">
                    {selectedTable.table_name}
                  </h2>
                  <p className="text-xs text-slate-400">Table Information</p>
                </div>
              </div>
              <button
                type="button"
                onClick={() => setSelectedTable(null)}
                className="w-8 h-8 rounded-lg hover:bg-slate-100 text-slate-400 hover:text-slate-700 flex items-center justify-center font-bold text-base transition-colors cursor-pointer"
              >
                ✕
              </button>
            </div>

            {/* Tab Switching: Middle / Center aligned */}
            <div className="px-6 border-b border-slate-100 flex items-center justify-center gap-8 bg-slate-50/70 shrink-0">
              <button
                type="button"
                onClick={() => setTableTab("schema_info")}
                className={`px-5 py-3 text-xs font-bold border-b-2 transition-all cursor-pointer ${
                  tableTab === "schema_info"
                    ? "border-[#FF5148] text-[#FF5148]"
                    : "border-transparent text-slate-500 hover:text-slate-800"
                }`}
              >
                Schema Info
              </button>
              <button
                type="button"
                onClick={() => setTableTab("sample_data")}
                className={`px-5 py-3 text-xs font-bold border-b-2 transition-all cursor-pointer ${
                  tableTab === "sample_data"
                    ? "border-[#FF5148] text-[#FF5148]"
                    : "border-transparent text-slate-500 hover:text-slate-800"
                }`}
              >
                Sample Data
              </button>
            </div>

            {/* Modal Body */}
            <div className="p-6 overflow-hidden flex-1 flex flex-col">
              {/* TAB 1: SCHEMA INFO */}
              {tableTab === "schema_info" && (
                <div className="flex flex-col h-full">
                  {/* no of rows, no of columns */}
                  <div className="flex items-center gap-8 mb-4 p-3 bg-slate-50 rounded-xl border border-slate-200/80 text-xs shrink-0">
                    <div>
                      <span className="text-slate-500">No. of Rows:</span>
                      <strong className="text-slate-900 font-bold ml-1.5">
                        {Number(selectedTable.number_of_rows || 0).toLocaleString()}
                      </strong>
                    </div>
                    <div>
                      <span className="text-slate-500">No. of Columns:</span>
                      <strong className="text-slate-900 font-bold ml-1.5">
                        {selectedTable.number_of_columns || selectedTable.column_wise_summary?.length || 0}
                      </strong>
                    </div>
                  </div>

                  {/* 2 column table with column name & data type, with vertical scrollbar */}
                  <div className="border border-slate-200 rounded-xl overflow-y-auto overflow-x-auto flex-1 shadow-2xs">
                    <table className="w-full text-xs text-left">
                      <thead className="bg-slate-50 border-b border-slate-200 sticky top-0 z-10">
                        <tr>
                          <th className="py-2.5 px-4 font-bold text-slate-700 bg-slate-50 border-r border-slate-200">
                            Column Name
                          </th>
                          <th className="py-2.5 px-4 font-bold text-slate-700 bg-slate-50">
                            Data Type
                          </th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-100">
                        {selectedTable.column_wise_summary?.map((col: any, idx: number) => (
                          <tr key={idx} className="hover:bg-slate-50/60 transition-colors">
                            <td className="py-2 px-4 font-mono font-medium text-slate-900 whitespace-nowrap border-r border-slate-100">
                              {col.column_name}
                            </td>
                            <td className="py-2 px-4 font-mono text-slate-600 whitespace-nowrap">
                              {col.data_type}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}

              {/* TAB 2: SAMPLE DATA (Real col 1 | col 2 | col 3 table with horizontal & vertical scrollbars) */}
              {tableTab === "sample_data" && (() => {
                const columns: any[] = selectedTable.column_wise_summary || [];
                const maxRows = Math.max(
                  0,
                  ...columns.map((c: any) => (c.sample_values?.length || c.categories?.length || 0))
                );

                if (columns.length === 0 || maxRows === 0) {
                  return (
                    <div className="h-full flex items-center justify-center text-slate-400 text-xs">
                      No sample data available for this table.
                    </div>
                  );
                }

                return (
                  <div className="flex flex-col h-full">
                    {/* Real Table with col1 | col2 | col3 as headers and val | val | val as rows */}
                    <div className="border border-slate-200 rounded-xl overflow-auto flex-1 shadow-2xs">
                      <table className="w-full text-xs text-left border-collapse min-w-full">
                        <thead className="bg-slate-50 border-b border-slate-200 sticky top-0 z-10 shadow-2xs">
                          <tr>
                            {columns.map((col: any, cIdx: number) => (
                              <th
                                key={cIdx}
                                className="py-2.5 px-4 font-mono font-bold text-slate-800 whitespace-nowrap bg-slate-50 border-r border-slate-200 last:border-r-0"
                              >
                                {col.column_name}
                              </th>
                            ))}
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-slate-100">
                          {Array.from({ length: maxRows }).map((_, rIdx) => (
                            <tr key={rIdx} className="hover:bg-slate-50/70 transition-colors">
                              {columns.map((col: any, cIdx: number) => {
                                const vals = col.sample_values || col.categories || [];
                                const cellVal = vals[rIdx];
                                return (
                                  <td
                                    key={cIdx}
                                    className="py-2.5 px-4 font-mono text-slate-700 whitespace-nowrap border-r border-slate-100 last:border-r-0"
                                  >
                                    {cellVal !== undefined && cellVal !== null ? String(cellVal) : "-"}
                                  </td>
                                );
                              })}
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                );
              })()}
            </div>

            {/* Footer */}
            <div className="px-6 py-3.5 bg-slate-50 border-t border-slate-100 flex items-center justify-between shrink-0">
              <button
                type="button"
                onClick={() => setSelectedTable(null)}
                className="px-3.5 py-1.5 text-xs font-semibold text-slate-600 hover:text-slate-800 hover:bg-slate-200/60 rounded-lg transition-colors cursor-pointer"
              >
                &larr; Back to Tables
              </button>
              <button
                type="button"
                onClick={() => {
                  setSelectedTable(null);
                  setSchemaModalDb(null);
                }}
                className="px-4 py-1.5 text-xs font-semibold text-slate-700 bg-white border border-slate-200 hover:bg-slate-100 rounded-lg transition-colors cursor-pointer"
              >
                Close
              </button>
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
              <div className="flex items-center gap-3">
                {modalStep === "form" && (
                  <button
                    type="button"
                    onClick={() => setModalStep("select")}
                    className="w-8 h-8 -ml-1 rounded-lg hover:bg-slate-100 text-slate-500 hover:text-slate-800 flex items-center justify-center transition-colors cursor-pointer"
                    title="Back to database selection"
                  >
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
                    </svg>
                  </button>
                )}
                <div>
                  <h2 className="text-lg font-bold text-slate-900">
                    {modalStep === "select"
                      ? "Connect Database"
                      : `Connect to ${activeDbType === "postgres" ? "PostgreSQL" : activeDbType === "mysql" ? "MySQL" : "Oracle SQL"}`}
                  </h2>
                  <p className="text-xs text-slate-500">
                    {modalStep === "select"
                      ? "Select your database engine to get started."
                      : "Enter your database credentials to verify and save connection."}
                  </p>
                </div>
              </div>
              <button
                onClick={() => setModalOpen(false)}
                className="w-8 h-8 rounded-lg hover:bg-slate-100 text-slate-400 hover:text-slate-700 flex items-center justify-center font-bold text-base transition-colors cursor-pointer"
              >
                ✕
              </button>
            </div>

            {/* STEP 1: INITIAL ENGINE SELECTION */}
            {modalStep === "select" ? (
              <div className="p-6">
                <p className="text-xs font-bold uppercase tracking-wider text-slate-400 mb-4">
                  Select Database Engine
                </p>

                <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                  {/* PostgreSQL */}
                  <button
                    type="button"
                    onClick={() => handleSelectEngine("postgres")}
                    className="group flex flex-col items-center justify-between p-5 rounded-xl border-2 border-slate-200 bg-white hover:border-[#FF5148] hover:bg-orange-50/10 hover:shadow-md hover:-translate-y-0.5 transition-all duration-200 cursor-pointer text-center"
                  >
                    <div className="w-16 h-16 rounded-xl bg-slate-50 border border-slate-100 p-2 flex items-center justify-center mb-3 group-hover:bg-white group-hover:border-orange-200 group-hover:scale-105 transition-all">
                      <img src="/postgres.png" alt="PostgreSQL" className="w-full h-full object-contain" />
                    </div>
                    <div>
                      <span className="block font-bold text-slate-800 text-sm group-hover:text-[#FF5148] transition-colors">
                        PostgreSQL
                      </span>
                      <span className="block text-[11px] text-slate-400 mt-0.5">Port 5432</span>
                    </div>
                    <span className="mt-3 text-[11px] font-semibold text-[#FF5148] opacity-0 group-hover:opacity-100 transition-opacity">
                      Configure &rarr;
                    </span>
                  </button>

                  {/* MySQL */}
                  <button
                    type="button"
                    onClick={() => handleSelectEngine("mysql")}
                    className="group flex flex-col items-center justify-between p-5 rounded-xl border-2 border-slate-200 bg-white hover:border-[#FF5148] hover:bg-orange-50/10 hover:shadow-md hover:-translate-y-0.5 transition-all duration-200 cursor-pointer text-center"
                  >
                    <div className="w-16 h-16 rounded-xl bg-slate-50 border border-slate-100 p-2 flex items-center justify-center mb-3 group-hover:bg-white group-hover:border-orange-200 group-hover:scale-105 transition-all">
                      <img src="/mysql.png" alt="MySQL" className="w-full h-full object-contain" />
                    </div>
                    <div>
                      <span className="block font-bold text-slate-800 text-sm group-hover:text-[#FF5148] transition-colors">
                        MySQL
                      </span>
                      <span className="block text-[11px] text-slate-400 mt-0.5">Port 3306</span>
                    </div>
                    <span className="mt-3 text-[11px] font-semibold text-[#FF5148] opacity-0 group-hover:opacity-100 transition-opacity">
                      Configure &rarr;
                    </span>
                  </button>

                  {/* Oracle SQL */}
                  <button
                    type="button"
                    onClick={() => handleSelectEngine("oracle_sql")}
                    className="group flex flex-col items-center justify-between p-5 rounded-xl border-2 border-slate-200 bg-white hover:border-[#FF5148] hover:bg-orange-50/10 hover:shadow-md hover:-translate-y-0.5 transition-all duration-200 cursor-pointer text-center"
                  >
                    <div className="w-16 h-16 rounded-xl bg-slate-50 border border-slate-100 p-2 flex items-center justify-center mb-3 group-hover:bg-white group-hover:border-orange-200 group-hover:scale-105 transition-all">
                      <img src="/oracle.png" alt="Oracle SQL" className="w-full h-full object-contain" />
                    </div>
                    <div>
                      <span className="block font-bold text-slate-800 text-sm group-hover:text-[#FF5148] transition-colors">
                        Oracle SQL
                      </span>
                      <span className="block text-[11px] text-slate-400 mt-0.5">Port 1521</span>
                    </div>
                    <span className="mt-3 text-[11px] font-semibold text-[#FF5148] opacity-0 group-hover:opacity-100 transition-opacity">
                      Configure &rarr;
                    </span>
                  </button>
                </div>

                <div className="mt-6 pt-4 border-t border-slate-100 flex items-center justify-end">
                  <button
                    type="button"
                    onClick={() => setModalOpen(false)}
                    className="px-4 py-2 text-sm font-semibold text-slate-600 hover:text-slate-800 hover:bg-slate-100 rounded-lg transition-colors cursor-pointer"
                  >
                    Cancel
                  </button>
                </div>
              </div>
            ) : (
              /* STEP 2: CREDENTIALS ENTRY FORM */
              <form onSubmit={handleConnectDatabase} className="p-6 space-y-4">
                {/* Active Selected Database Engine Badge */}
                <div className="p-3 bg-slate-50 border border-slate-200 rounded-xl flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <div className="w-9 h-9 rounded-lg bg-white border border-slate-200 p-1 flex items-center justify-center shadow-xs">
                      <img
                        src={
                          activeDbType === "postgres"
                            ? "/postgres.png"
                            : activeDbType === "mysql"
                            ? "/mysql.png"
                            : "/oracle.png"
                        }
                        alt={activeDbType}
                        className="w-full h-full object-contain"
                      />
                    </div>
                    <div>
                      <span className="text-[11px] text-slate-400 font-medium block">Selected Engine</span>
                      <span className="text-sm font-bold text-slate-800">
                        {activeDbType === "postgres"
                          ? "PostgreSQL"
                          : activeDbType === "mysql"
                          ? "MySQL"
                          : "Oracle SQL"}
                      </span>
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={() => setModalStep("select")}
                    className="text-xs font-semibold text-[#FF5148] hover:text-[#e64037] hover:underline px-2.5 py-1.5 rounded-lg hover:bg-orange-50 transition-colors cursor-pointer"
                  >
                    Change Engine &larr;
                  </button>
                </div>

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
                <div className="mt-6 pt-4 border-t border-slate-100 flex items-center justify-between">
                  <button
                    type="button"
                    onClick={() => setModalStep("select")}
                    className="px-4 py-2 text-sm font-semibold text-slate-600 hover:text-slate-800 hover:bg-slate-100 rounded-lg transition-colors cursor-pointer flex items-center gap-1.5"
                  >
                    &larr; Back
                  </button>
                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      onClick={() => setModalOpen(false)}
                      className="px-4 py-2 text-sm font-semibold text-slate-600 hover:text-slate-800 hover:bg-slate-100 rounded-lg transition-colors cursor-pointer"
                    >
                      Cancel
                    </button>
                    <button
                      type="submit"
                      disabled={connecting}
                      className="px-5 py-2 text-sm font-semibold text-white bg-[#FF5148] hover:bg-[#e64037] rounded-lg shadow-sm hover:shadow-md transition-all disabled:opacity-60 disabled:cursor-not-allowed flex items-center gap-2 cursor-pointer"
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
                </div>
              </form>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
