"use client";

import React, { useState, useEffect, useRef } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import DatabasesPage from "./databases";
import DocumentsPage from "./documents";
import TemplatesPage from "./templates";
import NavBar from "./NavBar";
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
  display_name?: string;
}

interface TemplateItem {
  template_id: string;
  template_name: string;
  category?: string;
}

interface WorkspaceItem {
  project_id: string;
  project_name: string;
  user_id: string;
  database_id?: string;
  database_name?: string;
  database_display_name?: string;
  database_type?: string;
  template_id?: string;
  template_name?: string;
  template_category?: string;
  slide_count: number;
  has_pptx: boolean;
  s3_folder: string;
  created_at?: string;
  updated_at?: string;
}

export default function DashboardHome() {
  const router = useRouter();

  // Active navigation tab (default: 'home')
  const [activeTab, setActiveTab] = useState<"home" | "databases" | "documents" | "templates">("home");

  // User details from session
  const [user, setUser] = useState<{ full_name: string; email: string } | null>(null);

  // Workspaces state
  const [workspaces, setWorkspaces] = useState<WorkspaceItem[]>([]);
  const [loadingWorkspaces, setLoadingWorkspaces] = useState(true);
  const [workspaceSearch, setWorkspaceSearch] = useState("");

  // Create Project Modal States
  const [projectModalOpen, setProjectModalOpen] = useState(false);
  const [projectStep, setProjectStep] = useState<1 | 2 | 3>(1);

  // Step 1: Project Name
  const [projectName, setProjectName] = useState("");

  // Step 2: Databases
  const [availableDbs, setAvailableDbs] = useState<DatabaseItem[]>([]);
  const [loadingDbs, setLoadingDbs] = useState(false);
  const [selectedDbId, setSelectedDbId] = useState<string | null>(null);

  // Step 3: Templates
  const [availableTemplates, setAvailableTemplates] = useState<TemplateItem[]>([]);
  const [loadingTemplates, setLoadingTemplates] = useState(false);
  const [selectedTemplateId, setSelectedTemplateId] = useState<string | null>(null);

  // Submitting state & error
  const [submitting, setSubmitting] = useState(false);
  const [creationError, setCreationError] = useState<string | null>(null);

  // Delete Project Modal States
  const [projectToDelete, setProjectToDelete] = useState<WorkspaceItem | null>(null);
  const [isDeletingProject, setIsDeletingProject] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const getUserId = () => {
    if (typeof window !== "undefined") {
      try {
        const saved = localStorage.getItem("kelostats_user");
        if (saved) {
          const parsed = JSON.parse(saved);
          return parsed.user_id || "93756663-25b3-43c6-9866-be63337e61cc";
        }
      } catch {
        // Fallback
      }
    }
    return "93756663-25b3-43c6-9866-be63337e61cc";
  };

  // Fetch user workspaces from backend API (which loads from Supabase S3 bucket workspace/user_id/)
  const fetchWorkspaces = async () => {
    const userId = getUserId();
    if (!userId) return;
    setLoadingWorkspaces(true);
    try {
      const res = await fetch(`${API_BASE_URL}/api/workspace/list?user_id=${userId}`);
      if (res.ok) {
        const data = await res.json();
        setWorkspaces(data.workspaces || []);
      }
    } catch (err) {
      console.error("Error fetching workspaces:", err);
    } finally {
      setLoadingWorkspaces(false);
    }
  };

  // Delete workspace project from Supabase S3 and database table 'workspace'
  const handleConfirmDeleteProject = async () => {
    if (!projectToDelete) return;
    setIsDeletingProject(true);
    setDeleteError(null);
    try {
      const res = await fetch(`${API_BASE_URL}/api/workspace/delete`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          project_id: projectToDelete.project_id,
          user_id: projectToDelete.user_id || getUserId(),
        }),
      });

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || "Failed to delete workspace project.");
      }

      setProjectToDelete(null);
      await fetchWorkspaces();
    } catch (err: any) {
      console.error("Error deleting workspace project:", err);
      setDeleteError(err.message || "Failed to delete project");
    } finally {
      setIsDeletingProject(false);
    }
  };

  // Navigate to existing workspace in editor
  const handleEditWorkspace = (ws: WorkspaceItem) => {
    const userId = getUserId();
    const projName = encodeURIComponent(ws.project_name || "Presentation Project");
    router.push(
      `/dashboard/workspace?user_id=${userId}&userid_id=${userId}&project_id=${ws.project_id}&project_name=${projName}&database_id=${ws.database_id || ""}&template_id=${ws.template_id || ""}`
    );
  };

  const formatDate = (dateStr?: string) => {
    if (!dateStr) return "Recently";
    try {
      const d = new Date(dateStr);
      return d.toLocaleDateString("en-US", {
        month: "short",
        day: "numeric",
        year: "numeric",
      });
    } catch {
      return dateStr;
    }
  };

  useEffect(() => {
    try {
      const savedUser = localStorage.getItem("kelostats_user");
      if (savedUser) {
        setUser(JSON.parse(savedUser));
      } else {
        setUser({
          full_name: "Eswar Sai Nandan",
          email: "eswarsainandan04@gmail.com",
        });
      }
    } catch {
      setUser({
        full_name: "Eswar Sai Nandan",
        email: "eswarsainandan04@gmail.com",
      });
    }

    fetchWorkspaces();
  }, []);

  useEffect(() => {
    if (activeTab === "home" || activeTab === "documents") {
      fetchWorkspaces();
    }
  }, [activeTab]);

  const handleLogout = () => {
    if (typeof window !== "undefined") {
      localStorage.removeItem("kelostats_user");
    }
    router.push("/login");
  };

  const getInitials = (name?: string) => {
    if (!name) return "U";
    return name
      .split(" ")
      .map((n) => n[0])
      .join("")
      .substring(0, 2)
      .toUpperCase();
  };

  // Open Create Project Modal & Load Data
  const handleOpenCreateProject = async () => {
    setProjectStep(1);
    setProjectName("");
    setSelectedDbId(null);
    setSelectedTemplateId(null);
    setCreationError(null);
    setProjectModalOpen(true);

    // Fetch user's databases
    setLoadingDbs(true);
    const userId = getUserId();
    try {
      const res = await fetch(`${API_BASE_URL}/api/databases/database_info?user_id=${userId}`);
      if (res.ok) {
        const data = await res.json();
        const dbs = data.databases || [];
        setAvailableDbs(dbs);
        if (dbs.length > 0) {
          setSelectedDbId(dbs[0].db_id);
        }
      }
    } catch (err) {
      console.error("Error fetching databases:", err);
    } finally {
      setLoadingDbs(false);
    }

    // Fetch PPT templates from backend (templates/presentations.py -> api/get/templates)
    setLoadingTemplates(true);
    try {
      const res = await fetch(`${API_BASE_URL}/api/get/templates`);
      if (res.ok) {
        const data = await res.json();
        const tmpls = data.templates || [];
        setAvailableTemplates(tmpls);
        if (tmpls.length > 0) {
          setSelectedTemplateId(tmpls[0].template_id);
        }
      }
    } catch (err) {
      console.error("Error fetching templates:", err);
    } finally {
      setLoadingTemplates(false);
    }
  };

  // Handle "Let's Go" -> Call /api/workspace/create then navigate to workspace
  const handleLetsGo = async () => {
    if (!projectName.trim() || !selectedDbId || !selectedTemplateId) return;

    setSubmitting(true);
    setCreationError(null);

    const userId = getUserId();

    try {
      const res = await fetch(`${API_BASE_URL}/api/workspace/create`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          project_name: projectName.trim(),
          user_id: userId,
          database_id: selectedDbId,
          template_id: selectedTemplateId,
        }),
      });

      const data = await res.json();

      if (!res.ok) {
        throw new Error(data.detail || "Failed to create project workspace.");
      }

      // Close modal and navigate to workspace page with all parameters
      setProjectModalOpen(false);
      fetchWorkspaces();
      const projectId = data.project_id || "";
      const projName = encodeURIComponent(data.project_name || projectName.trim());

      router.push(
        `/dashboard/workspace?user_id=${userId}&userid_id=${userId}&database_id=${selectedDbId}&template_id=${selectedTemplateId}&project_id=${projectId}&project_name=${projName}`
      );
    } catch (err: any) {
      setCreationError(err.message || "An unexpected error occurred. Please try again.");
    } finally {
      setSubmitting(false);
    }
  };

  const filteredWorkspaces = workspaces.filter((w) => {
    if (!workspaceSearch.trim()) return true;
    const query = workspaceSearch.toLowerCase();
    return (
      (w.project_name && w.project_name.toLowerCase().includes(query)) ||
      (w.database_name && w.database_name.toLowerCase().includes(query)) ||
      (w.template_name && w.template_name.toLowerCase().includes(query)) ||
      (w.project_id && w.project_id.toLowerCase().includes(query))
    );
  });

  return (
    <div className="min-h-screen bg-white text-slate-900 flex flex-col md:flex-row font-sans selection:bg-orange-100 selection:text-orange-600">
      {/* ========================================================================= */}
      {/* CANVA-STYLE VERTICAL SLIDE BAR NAVIGATION */}
      {/* ========================================================================= */}
      <NavBar
        activeTab={activeTab}
        setActiveTab={setActiveTab}
        user={user}
        handleLogout={handleLogout}
        handleOpenCreateProject={handleOpenCreateProject}
        workspaces={workspaces}
        onSelectProject={handleEditWorkspace}
      />

      {/* ========================================================================= */}
      {/* MAIN BODY CONTENT WRAPPER */}
      {/* ========================================================================= */}
      <div className={`flex-1 flex flex-col min-w-0 min-h-screen ${activeTab === "templates" ? "bg-[#f4f6f9]" : "bg-white"}`}>
        {activeTab !== "templates" && (
          <main className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 md:px-8 py-6 md:py-8">
            {/* TAB 1: HOME */}
            {activeTab === "home" && (
          <div className="space-y-8 animate-in fade-in duration-200">
            {/* Action Banner */}
            <div className="flex flex-col md:flex-row md:items-center justify-between gap-6 p-8 rounded-2xl bg-gradient-to-r from-orange-50 via-white to-orange-50/40 border border-orange-200/60 shadow-sm">
              <div>
                <h1 className="text-2xl sm:text-3xl font-extrabold text-slate-900">
                  Welcome back, <span className="text-[#FF5148]">{user?.full_name?.split(" ")[0] || "User"}</span>!
                </h1>
                <p className="text-sm text-slate-600 mt-1.5 max-w-xl">
                  Connect your database telemetry and synthesize branded, executive-ready PowerPoint decks with multi-agent AI.
                </p>
              </div>
              <div className="flex items-center gap-3 shrink-0">
                <button
                  onClick={() => setActiveTab("databases")}
                  className="px-4 py-2.5 rounded-xl text-sm font-semibold text-slate-700 bg-white border border-slate-200 hover:bg-slate-50 transition-all cursor-pointer"
                >
                  Manage Databases
                </button>
                <button
                  onClick={handleOpenCreateProject}
                  className="px-5 py-2.5 rounded-xl text-sm font-bold text-white bg-[#FF5148] hover:bg-[#e64037] shadow-sm hover:shadow-md hover:scale-[1.02] active:scale-[0.98] transition-all flex items-center gap-2 cursor-pointer"
                >
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M12 4v16m8-8H4" />
                  </svg>
                  <span>Create Project</span>
                </button>
              </div>
            </div>

            {/* Workspaces & Projects Section */}
            <div className="space-y-5">
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-2 border-b border-slate-100">
                <div className="flex items-center gap-3">
                  <h2 className="text-xl font-bold text-slate-900 tracking-tight">Your Workspaces</h2>
                  <span className="px-2.5 py-0.5 rounded-full text-xs font-bold bg-orange-50 text-[#FF5148] border border-orange-200/80">
                    {filteredWorkspaces.length} {filteredWorkspaces.length === 1 ? "Project" : "Projects"}
                  </span>
                </div>

                <div className="flex items-center gap-3">
                  {/* Search input */}
                  <div className="relative">
                    <svg className="w-4 h-4 text-slate-400 absolute left-3 top-1/2 -translate-y-1/2 pointer-events-none" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
                    </svg>
                    <input
                      type="text"
                      value={workspaceSearch}
                      onChange={(e) => setWorkspaceSearch(e.target.value)}
                      placeholder="Search workspaces..."
                      className="pl-9 pr-7 py-2 text-xs rounded-xl border border-slate-200 bg-white text-slate-800 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-[#FF5148]/20 focus:border-[#FF5148] transition-all w-48 sm:w-64"
                    />
                    {workspaceSearch && (
                      <button
                        onClick={() => setWorkspaceSearch("")}
                        className="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600 text-sm font-bold"
                      >
                        ×
                      </button>
                    )}
                  </div>

                  {/* Refresh Button */}
                  <button
                    onClick={fetchWorkspaces}
                    disabled={loadingWorkspaces}
                    title="Refresh from Supabase S3 bucket"
                    className="p-2 rounded-xl border border-slate-200 bg-white hover:bg-slate-50 text-slate-600 hover:text-slate-900 transition-all cursor-pointer shadow-2xs"
                  >
                    <svg className={`w-4 h-4 ${loadingWorkspaces ? "animate-spin text-[#FF5148]" : ""}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                    </svg>
                  </button>

                  <button
                    onClick={handleOpenCreateProject}
                    className="px-3.5 py-2 rounded-xl text-xs font-bold text-white bg-[#FF5148] hover:bg-[#e64037] shadow-sm transition-all flex items-center gap-1.5 cursor-pointer"
                  >
                    <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M12 4v16m8-8H4" />
                    </svg>
                    <span>New Project</span>
                  </button>
                </div>
              </div>

              {/* Loading State */}
              {loadingWorkspaces && workspaces.length === 0 && (
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6 animate-pulse">
                  {[1, 2, 3].map((i) => (
                    <div key={i} className="h-56 rounded-2xl bg-slate-100 border border-slate-200 p-6 flex flex-col justify-between">
                      <div className="space-y-3">
                        <div className="w-10 h-10 rounded-xl bg-slate-200" />
                        <div className="w-3/4 h-5 rounded-lg bg-slate-200" />
                        <div className="w-1/2 h-3 rounded-lg bg-slate-200" />
                      </div>
                      <div className="w-full h-10 rounded-xl bg-slate-200" />
                    </div>
                  ))}
                </div>
              )}

              {/* Zero Workspaces in Total */}
              {!loadingWorkspaces && workspaces.length === 0 && (
                <div className="p-12 text-center rounded-2xl border-2 border-dashed border-slate-200 bg-slate-50/40 flex flex-col items-center justify-center">
                  <div className="w-16 h-16 rounded-2xl bg-orange-100/70 text-[#FF5148] flex items-center justify-center mb-4 shadow-sm">
                    <svg className="w-8 h-8" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
                    </svg>
                  </div>
                  <h2 className="text-xl font-bold text-slate-900">Start a new presentation project</h2>
                  <p className="text-sm text-slate-500 max-w-md mt-1 mb-6">
                    Choose a connected database and a PowerPoint template to initialize your project workspace.
                  </p>
                  <button
                    onClick={handleOpenCreateProject}
                    className="px-6 py-3 rounded-xl text-sm font-bold text-white bg-[#FF5148] hover:bg-[#e64037] shadow-sm hover:shadow-md transition-all flex items-center gap-2 cursor-pointer"
                  >
                    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M12 4v16m8-8H4" />
                    </svg>
                    <span>Create Project</span>
                  </button>
                </div>
              )}

              {/* Workspaces Exist but Search Found Nothing */}
              {workspaces.length > 0 && filteredWorkspaces.length === 0 && (
                <div className="p-12 text-center rounded-2xl border border-slate-200 bg-slate-50/50 flex flex-col items-center justify-center">
                  <p className="text-sm font-semibold text-slate-700">No workspaces match "{workspaceSearch}"</p>
                  <p className="text-xs text-slate-400 mt-1">Try clearing your search query or check spelling.</p>
                  <button
                    onClick={() => setWorkspaceSearch("")}
                    className="mt-4 px-4 py-2 rounded-xl text-xs font-bold text-[#FF5148] bg-orange-50 hover:bg-orange-100 border border-orange-200 transition-colors cursor-pointer"
                  >
                    Clear Filter
                  </button>
                </div>
              )}

              {/* Workspaces Cards Grid */}
              {filteredWorkspaces.length > 0 && (
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                  {filteredWorkspaces.map((ws) => (
                    <div
                      key={ws.project_id}
                      className="bg-white rounded-2xl border border-slate-200 shadow-sm hover:shadow-lg hover:border-orange-200 transition-all duration-200 p-6 flex flex-col justify-between group relative overflow-hidden"
                    >
                      {/* Top Accent Strip on hover */}
                      <div className="absolute top-0 left-0 right-0 h-1 bg-gradient-to-r from-[#FF5148] to-orange-400 opacity-0 group-hover:opacity-100 transition-opacity" />

                      <div>
                        {/* Header Row: Icon, Project Name & Slide Count */}
                        <div className="flex items-start justify-between gap-3">
                          <div className="w-11 h-11 rounded-xl bg-orange-100 text-[#FF5148] flex items-center justify-center shadow-xs shrink-0 group-hover:scale-105 transition-transform">
                            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 12l3-3 3 3 4-4M8 21l4-4 4 4M3 4h18M4 4h16v12a1 1 0 01-1 1H5a1 1 0 01-1-1V4z" />
                            </svg>
                          </div>

                          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-bold bg-orange-50 text-[#FF5148] border border-orange-200/70 shrink-0">
                            <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 17V7m0 10a2 2 0 01-2 2H5a2 2 0 01-2-2V7a2 2 0 012-2h2a2 2 0 012 2m0 10a2 2 0 002 2h2a2 2 0 002-2M9 7a2 2 0 012-2h2a2 2 0 012 2m0 10V7m0 10a2 2 0 002 2h2a2 2 0 002-2V7a2 2 0 00-2-2h-2a2 2 0 00-2 2" />
                            </svg>
                            <span>{ws.slide_count} {ws.slide_count === 1 ? "Slide" : "Slides"}</span>
                          </span>
                        </div>

                        {/* Project Title */}
                        <h3
                          onClick={() => handleEditWorkspace(ws)}
                          title={ws.project_name}
                          className="mt-4 text-lg font-bold text-slate-900 group-hover:text-[#FF5148] transition-colors truncate cursor-pointer"
                        >
                          {ws.project_name}
                        </h3>

                        <p className="text-xs text-slate-400 mt-1">
                          Last updated {formatDate(ws.updated_at || ws.created_at)}
                        </p>

                        {/* Badges / Metadata */}
                        <div className="mt-4 pt-3 border-t border-slate-100 space-y-2">
                          {/* Database */}
                          {(ws.database_display_name || ws.database_name) && (
                            <div className="flex items-center gap-2 text-xs text-slate-600">
                              <span className="w-5 h-5 rounded-md bg-slate-100 flex items-center justify-center shrink-0 text-slate-500">
                                <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4m0 5c0 2.21-3.582 4-8 4s-8-1.79-8-4" />
                                </svg>
                              </span>
                              <span className="truncate">
                                <span className="font-semibold text-slate-700">{ws.database_display_name || ws.database_name}</span>
                                <span className="text-slate-400 text-[11px] ml-1">({ws.database_type || "database"})</span>
                              </span>
                            </div>
                          )}

                          {/* Template */}
                          {ws.template_name && (
                            <div className="flex items-center gap-2 text-xs text-slate-600">
                              <span className="w-5 h-5 rounded-md bg-amber-50 text-amber-600 border border-amber-200/50 flex items-center justify-center shrink-0">
                                <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 5a1 1 0 011-1h14a1 1 0 011 1v2a1 1 0 01-1 1H5a1 1 0 01-1-1V5zM4 13a1 1 0 011-1h6a1 1 0 011 1v6a1 1 0 01-1 1H5a1 1 0 01-1-1v-6z" />
                                </svg>
                              </span>
                              <span className="truncate text-slate-500" title={ws.template_name}>
                                {ws.template_name}
                              </span>
                            </div>
                          )}
                        </div>
                      </div>

                      {/* Action Buttons: Edit Workspace Primary */}
                      <div className="mt-6 pt-4 border-t border-slate-100 flex items-center gap-2">
                        <button
                          onClick={() => handleEditWorkspace(ws)}
                          className="flex-1 py-2.5 px-4 rounded-xl text-xs font-bold text-white bg-[#FF5148] hover:bg-[#e64037] shadow-xs hover:shadow-md transition-all flex items-center justify-center gap-2 cursor-pointer group/btn"
                        >
                          <svg className="w-4 h-4 transition-transform group-hover/btn:scale-110" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
                          </svg>
                          <span>Edit Workspace</span>
                        </button>

                        <button
                          onClick={() => {
                            window.open(
                              `${API_BASE_URL}/api/workspace/editor/download?user_id=${ws.user_id}&project_id=${ws.project_id}`,
                              "_blank"
                            );
                          }}
                          title="Download PPTX"
                          className="p-2.5 rounded-xl border border-slate-200 text-slate-500 hover:text-slate-800 hover:bg-slate-50 transition-colors cursor-pointer shrink-0"
                        >
                          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
                          </svg>
                        </button>

                        {/* Delete Workspace Button */}
                        <button
                          onClick={() => {
                            setDeleteError(null);
                            setProjectToDelete(ws);
                          }}
                          title="Delete Project"
                          className="p-2.5 rounded-xl border border-slate-200 text-slate-400 hover:text-red-600 hover:border-red-200 hover:bg-red-50 transition-colors cursor-pointer shrink-0"
                        >
                          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path
                              strokeLinecap="round"
                              strokeLinejoin="round"
                              strokeWidth={2}
                              d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"
                            />
                          </svg>
                        </button>
                      </div>
                    </div>
                  ))}

                  {/* Add New Project Card */}
                  <button
                    onClick={handleOpenCreateProject}
                    className="min-h-[260px] rounded-2xl border-2 border-dashed border-slate-200 hover:border-[#FF5148]/60 hover:bg-orange-50/30 p-6 flex flex-col items-center justify-center text-center transition-all group cursor-pointer"
                  >
                    <div className="w-12 h-12 rounded-2xl bg-orange-100 text-[#FF5148] flex items-center justify-center mb-3 group-hover:scale-110 transition-transform shadow-2xs">
                      <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
                      </svg>
                    </div>
                    <span className="font-bold text-sm text-slate-800 group-hover:text-[#FF5148] transition-colors">Create Another Project</span>
                    <span className="text-xs text-slate-400 mt-1 max-w-[200px]">Connect database telemetry and synthesize a new presentation</span>
                  </button>
                </div>
              )}
            </div>
          </div>
        )}

        {/* TAB 2: DATABASES */}
        {activeTab === "databases" && <DatabasesPage />}

        {/* TAB 3: DOCUMENTS (RAG) */}
        {activeTab === "documents" && <DocumentsPage />}
      </main>
        )}

        {/* TAB 4: TEMPLATES (Full width and native background) */}
        {activeTab === "templates" && (
          <div className="flex-1 w-full min-h-screen flex flex-col">
            <TemplatesPage onNavigateTab={(tab) => setActiveTab(tab)} />
          </div>
        )}
      </div>

      {/* ========================================================================= */}
      {/* BIG POPUP MODAL: CREATE PROJECT (STEP 1: NAME -> STEP 2: DB -> STEP 3: TEMPLATE) */}
      {/* ========================================================================= */}
      {projectModalOpen && (
        <div
          className="fixed inset-0 z-50 bg-black/50 backdrop-blur-sm flex items-center justify-center p-4 animate-in fade-in duration-150"
          onClick={() => !submitting && setProjectModalOpen(false)}
        >
          <div
            className="bg-white border border-slate-200 rounded-2xl w-full max-w-2xl shadow-2xl overflow-hidden animate-in zoom-in-95 duration-200 flex flex-col max-h-[90vh]"
            onClick={(e) => e.stopPropagation()}
          >
            {/* Modal Header with Progress Steps */}
            <div className="px-6 py-5 border-b border-slate-100 flex items-center justify-between bg-slate-50/50">
              <div className="flex items-center gap-4">
                <div className="w-10 h-10 rounded-xl bg-orange-100 text-[#FF5148] flex items-center justify-center font-extrabold text-sm shrink-0">
                  {projectStep}
                </div>
                <div>
                  <h2 className="text-lg font-bold text-slate-900 leading-tight">
                    {projectStep === 1
                      ? "Step 1: Enter Project Name"
                      : projectStep === 2
                      ? "Step 2: Choose Your Database"
                      : "Step 3: Choose Your PPT Template"}
                  </h2>
                  <p className="text-xs text-slate-500 mt-0.5">
                    {projectStep === 1
                      ? "Give your presentation workspace a descriptive project name"
                      : projectStep === 2
                      ? "Select one available database to connect to your project"
                      : "Select a presentation template design for your report"}
                  </p>
                </div>
              </div>

              {!submitting && (
                <button
                  type="button"
                  onClick={() => setProjectModalOpen(false)}
                  className="w-8 h-8 rounded-lg hover:bg-slate-200/60 text-slate-400 hover:text-slate-700 flex items-center justify-center font-bold text-base transition-colors cursor-pointer"
                >
                  ✕
                </button>
              )}
            </div>

            {/* Error Message Box if Creation Fails */}
            {creationError && (
              <div className="px-6 py-3 bg-red-50 border-b border-red-100 text-xs text-red-700 font-medium flex items-center gap-2">
                <svg className="w-4 h-4 text-red-500 shrink-0" fill="currentColor" viewBox="0 0 20 20">
                  <path fillRule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7 4a1 1 0 11-2 0 1 1 0 012 0zm-1-9a1 1 0 00-1 1v4a1 1 0 102 0V6a1 1 0 00-1-1z" clipRule="evenodd" />
                </svg>
                <span>{creationError}</span>
              </div>
            )}

            {/* Modal Body */}
            <div className="p-6 overflow-y-auto flex-1">
              {/* STEP 1: ENTER PROJECT NAME */}
              {projectStep === 1 && (
                <div className="space-y-4 py-2">
                  <label className="block text-xs font-bold uppercase tracking-wider text-slate-700">
                    Project Name
                  </label>
                  <input
                    type="text"
                    required
                    autoFocus
                    value={projectName}
                    onChange={(e) => setProjectName(e.target.value)}
                    placeholder="e.g. Q4 Executive Telemetry Presentation"
                    className="w-full px-4 py-3 rounded-xl border border-slate-200 focus:outline-none focus:ring-2 focus:ring-[#FF5148]/30 focus:border-[#FF5148] text-base text-slate-900 shadow-sm"
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && projectName.trim()) {
                        setProjectStep(2);
                      }
                    }}
                  />
                  <p className="text-xs text-slate-500">
                    This project will hold your generated slides, query history, and Supabase cloud artifacts.
                  </p>
                </div>
              )}

              {/* STEP 2: CHOOSE YOUR DATABASE */}
              {projectStep === 2 && (
                <div className="space-y-4">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-bold uppercase tracking-wider text-slate-400">
                      Available Databases
                    </span>
                    <span className="text-xs text-slate-500 font-medium">
                      {availableDbs.length} connected
                    </span>
                  </div>

                  {loadingDbs ? (
                    <div className="py-12 text-center text-sm text-slate-400">
                      Loading databases...
                    </div>
                  ) : availableDbs.length === 0 ? (
                    <div className="p-8 text-center rounded-xl border border-dashed border-slate-200 bg-slate-50">
                      <p className="text-sm font-semibold text-slate-700">No connected databases found.</p>
                      <p className="text-xs text-slate-400 mt-1 mb-4">
                        Please connect a database first before creating a project.
                      </p>
                      <button
                        onClick={() => {
                          setProjectModalOpen(false);
                          setActiveTab("databases");
                        }}
                        className="px-4 py-2 text-xs font-semibold text-white bg-[#FF5148] hover:bg-[#e64037] rounded-lg transition-all cursor-pointer"
                      >
                        Go to Databases
                      </button>
                    </div>
                  ) : (
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3.5">
                      {availableDbs.map((db) => {
                        const isSelected = selectedDbId === db.db_id;
                        const displayName = db.display_name || db.database_name || db.service_name || "Database";
                        const rawDb = db.database_name || db.service_name;

                        return (
                          <div
                            key={db.db_id}
                            onClick={() => setSelectedDbId(db.db_id)}
                            className={`p-4 rounded-xl border-2 transition-all cursor-pointer flex items-center justify-between ${
                              isSelected
                                ? "border-[#FF5148] bg-orange-50/40 shadow-sm"
                                : "border-slate-200 hover:border-slate-300 hover:bg-slate-50/60"
                            }`}
                          >
                            <div className="flex items-center gap-3 overflow-hidden">
                              <div className="w-12 h-12 flex items-center justify-center shrink-0">
                                <img
                                  src="/database.png"
                                  alt={displayName}
                                  className="w-full h-full object-contain pointer-events-none"
                                />
                              </div>
                              <div className="overflow-hidden">
                                <h3 className="text-sm font-bold text-slate-900 truncate" title={displayName}>
                                  {displayName}
                                </h3>
                                <p className="text-xs text-slate-500 truncate mt-0.5">
                                  {rawDb && rawDb !== displayName ? `${rawDb} • ` : ""}{db.host}:{db.port}
                                </p>
                                <span className="inline-block text-[10px] font-semibold text-emerald-600 uppercase mt-1">
                                  {db.database_type}
                                </span>
                              </div>
                            </div>

                            <div className="shrink-0 ml-2">
                              <div
                                className={`w-5 h-5 rounded-full border flex items-center justify-center ${
                                  isSelected
                                    ? "border-[#FF5148] bg-[#FF5148]"
                                    : "border-slate-300 bg-white"
                                }`}
                              >
                                {isSelected && (
                                  <svg className="w-3 h-3 text-white" fill="currentColor" viewBox="0 0 20 20">
                                    <path
                                      fillRule="evenodd"
                                      d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z"
                                      clipRule="evenodd"
                                    />
                                  </svg>
                                )}
                              </div>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
              )}

              {/* STEP 3: CHOOSE YOUR PPT TEMPLATES */}
              {projectStep === 3 && (
                <div className="space-y-4">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-bold uppercase tracking-wider text-slate-400">
                      Available Templates
                    </span>
                    <span className="text-xs text-slate-500 font-medium">
                      {availableTemplates.length} templates
                    </span>
                  </div>

                  {loadingTemplates ? (
                    <div className="py-12 text-center text-sm text-slate-400">
                      Loading templates from database...
                    </div>
                  ) : availableTemplates.length === 0 ? (
                    <div className="p-8 text-center rounded-xl border border-dashed border-slate-200 bg-slate-50">
                      <p className="text-sm font-semibold text-slate-700">No templates found in public.templates.</p>
                      <p className="text-xs text-slate-400 mt-1">
                        Please insert rows into public.templates table.
                      </p>
                    </div>
                  ) : (
                    <div className="space-y-2.5">
                      {availableTemplates.map((tmpl) => {
                        const isSelected = selectedTemplateId === tmpl.template_id;

                        return (
                          <div
                            key={tmpl.template_id}
                            onClick={() => setSelectedTemplateId(tmpl.template_id)}
                            className={`p-4 rounded-xl border-2 transition-all cursor-pointer flex items-center justify-between ${
                              isSelected
                                ? "border-[#FF5148] bg-orange-50/40 shadow-sm"
                                : "border-slate-200 hover:border-slate-300 hover:bg-slate-50/60"
                            }`}
                          >
                            <div className="flex items-center gap-3.5">
                              <div
                                className={`w-9 h-9 rounded-lg flex items-center justify-center font-bold text-xs ${
                                  isSelected
                                    ? "bg-[#FF5148] text-white"
                                    : "bg-orange-100 text-[#FF5148]"
                                }`}
                              >
                                PPT
                              </div>
                              <div>
                                <span className="text-sm font-bold text-slate-900">
                                  {tmpl.template_name}
                                </span>
                              </div>
                            </div>

                            <div className="shrink-0 ml-2">
                              <div
                                className={`w-5 h-5 rounded-full border flex items-center justify-center ${
                                  isSelected
                                    ? "border-[#FF5148] bg-[#FF5148]"
                                    : "border-slate-300 bg-white"
                                }`}
                              >
                                {isSelected && (
                                  <svg className="w-3 h-3 text-white" fill="currentColor" viewBox="0 0 20 20">
                                    <path
                                      fillRule="evenodd"
                                      d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z"
                                      clipRule="evenodd"
                                    />
                                  </svg>
                                )}
                              </div>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
              )}
            </div>

            {/* Modal Footer Controls */}
            <div className="px-6 py-4 border-t border-slate-100 bg-slate-50/50 flex items-center justify-between">
              {projectStep === 1 ? (
                <>
                  <button
                    type="button"
                    onClick={() => setProjectModalOpen(false)}
                    className="px-4 py-2 text-sm font-semibold text-slate-600 hover:text-slate-800 hover:bg-slate-200/60 rounded-lg transition-colors cursor-pointer"
                  >
                    Cancel
                  </button>

                  <button
                    type="button"
                    disabled={!projectName.trim()}
                    onClick={() => setProjectStep(2)}
                    className="px-5 py-2 text-sm font-semibold text-white bg-[#FF5148] hover:bg-[#e64037] rounded-lg shadow-sm transition-all disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2 cursor-pointer"
                  >
                    <span>Next</span>
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                    </svg>
                  </button>
                </>
              ) : projectStep === 2 ? (
                <>
                  <button
                    type="button"
                    onClick={() => setProjectStep(1)}
                    className="px-4 py-2 text-sm font-semibold text-slate-600 hover:text-slate-800 hover:bg-slate-200/60 rounded-lg transition-colors flex items-center gap-1.5 cursor-pointer"
                  >
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
                    </svg>
                    <span>Back</span>
                  </button>

                  <button
                    type="button"
                    disabled={!selectedDbId || availableDbs.length === 0}
                    onClick={() => setProjectStep(3)}
                    className="px-5 py-2 text-sm font-semibold text-white bg-[#FF5148] hover:bg-[#e64037] rounded-lg shadow-sm transition-all disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2 cursor-pointer"
                  >
                    <span>Next</span>
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                    </svg>
                  </button>
                </>
              ) : (
                <>
                  <button
                    type="button"
                    disabled={submitting}
                    onClick={() => setProjectStep(2)}
                    className="px-4 py-2 text-sm font-semibold text-slate-600 hover:text-slate-800 hover:bg-slate-200/60 rounded-lg transition-colors flex items-center gap-1.5 cursor-pointer disabled:opacity-50"
                  >
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
                    </svg>
                    <span>Back</span>
                  </button>

                  <button
                    type="button"
                    disabled={!selectedTemplateId || availableTemplates.length === 0 || submitting}
                    onClick={handleLetsGo}
                    className="px-6 py-2 text-sm font-bold text-white bg-[#FF5148] hover:bg-[#e64037] rounded-lg shadow-sm hover:shadow-md transition-all disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2 cursor-pointer"
                  >
                    {submitting ? (
                      <>
                        <svg className="animate-spin -ml-1 mr-2 h-4 w-4 text-white" fill="none" viewBox="0 0 24 24">
                          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z" />
                        </svg>
                        <span>Creating Workspace...</span>
                      </>
                    ) : (
                      <>
                        <span>Let's Go</span>
                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14 5l7 7m0 0l-7 7m7-7H3" />
                        </svg>
                      </>
                    )}
                  </button>
                </>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Delete Project Confirmation Popup Modal */}
      {projectToDelete && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/60 backdrop-blur-xs animate-in fade-in duration-200">
          <div
            className="w-full max-w-md bg-white rounded-2xl shadow-2xl border border-slate-100 overflow-hidden transform transition-all animate-in zoom-in-95 duration-200"
            onClick={(e) => e.stopPropagation()}
          >
            {/* Header with warning icon */}
            <div className="p-6 pb-4">
              <div className="flex items-start gap-4">
                <div className="w-12 h-12 rounded-2xl bg-red-100 text-red-600 flex items-center justify-center shrink-0 shadow-2xs">
                  <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                      d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"
                    />
                  </svg>
                </div>
                <div className="flex-1">
                  <h3 className="text-lg font-bold text-slate-900">Delete Project?</h3>
                  <p className="text-sm text-slate-500 mt-1">
                    Are you sure you want to delete <span className="font-semibold text-slate-800">"{projectToDelete.project_name}"</span>?
                  </p>
                </div>
              </div>

              {/* Warning Callout Box */}
              <div className="mt-4 p-3.5 bg-red-50/70 border border-red-200/60 rounded-xl text-xs text-red-700 leading-relaxed">
                <div className="flex items-start gap-2">
                  <svg className="w-4 h-4 text-red-500 shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                  </svg>
                  <div>
                    <span className="font-semibold">This action cannot be undone.</span>
                    <p className="mt-0.5 text-red-600/90">
                      This will permanently remove the project from the <code className="bg-red-100 px-1 py-0.5 rounded font-mono text-[11px]">workspace</code> database table and delete all presentation files and slides from Supabase S3.
                    </p>
                  </div>
                </div>
              </div>

              {deleteError && (
                <div className="mt-3 p-3 bg-red-100/80 border border-red-300 rounded-xl text-xs text-red-800 font-medium">
                  {deleteError}
                </div>
              )}
            </div>

            {/* Modal Footer Actions */}
            <div className="p-4 bg-slate-50/80 border-t border-slate-100 flex items-center justify-end gap-2.5">
              <button
                type="button"
                disabled={isDeletingProject}
                onClick={() => {
                  setProjectToDelete(null);
                  setDeleteError(null);
                }}
                className="px-4 py-2.5 text-xs font-semibold text-slate-600 hover:text-slate-800 hover:bg-slate-200/60 rounded-xl transition-colors cursor-pointer disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                type="button"
                disabled={isDeletingProject}
                onClick={handleConfirmDeleteProject}
                className="px-5 py-2.5 text-xs font-bold text-white bg-red-600 hover:bg-red-700 active:bg-red-800 rounded-xl shadow-xs hover:shadow-md transition-all flex items-center gap-2 cursor-pointer disabled:opacity-50"
              >
                {isDeletingProject ? (
                  <>
                    <svg className="animate-spin w-3.5 h-3.5 text-white" fill="none" viewBox="0 0 24 24">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z" />
                    </svg>
                    <span>Deleting Project...</span>
                  </>
                ) : (
                  <>
                    <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        strokeWidth={2}
                        d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"
                      />
                    </svg>
                    <span>Yes, Delete Project</span>
                  </>
                )}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
