"use client";

import React, { useState, useRef, useEffect } from "react";
import Link from "next/link";

export interface WorkspaceItem {
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

export interface NavBarProps {
  activeTab: "home" | "databases" | "documents" | "templates";
  setActiveTab: (tab: "home" | "databases" | "documents" | "templates") => void;
  user: { full_name: string; email: string } | null;
  handleLogout: () => void;
  handleOpenCreateProject: () => void;
  workspaces?: WorkspaceItem[];
  onSelectProject?: (workspace: WorkspaceItem) => void;
}

type SlidePanelType = "none" | "projects" | "templates";

export default function NavBar({
  activeTab,
  setActiveTab,
  user,
  handleLogout,
  handleOpenCreateProject,
  workspaces = [],
  onSelectProject,
}: NavBarProps) {
  // Slide drawer state
  const [slidePanel, setSlidePanel] = useState<SlidePanelType>("none");
  const [isMobileOpen, setIsMobileOpen] = useState(false);

  // Profile menu popup state
  const [profileOpen, setProfileOpen] = useState(false);
  const profileRef = useRef<HTMLDivElement>(null);
  const slideDrawerRef = useRef<HTMLDivElement>(null);

  // Panel search
  const [panelSearch, setPanelSearch] = useState("");

  // Get user initials
  const getInitials = (name?: string) => {
    if (!name) return "U";
    return name
      .split(" ")
      .map((n) => n[0])
      .join("")
      .substring(0, 2)
      .toUpperCase();
  };

  // Close dropdowns on outside click
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (profileRef.current && !profileRef.current.contains(event.target as Node)) {
        setProfileOpen(false);
      }
      if (
        slidePanel !== "none" &&
        slideDrawerRef.current &&
        !slideDrawerRef.current.contains(event.target as Node)
      ) {
        const targetEl = event.target as HTMLElement;
        if (!targetEl.closest("[data-nav-rail='true']")) {
          setSlidePanel("none");
        }
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [slidePanel]);

  // Handle panel toggle
  const togglePanel = (panel: SlidePanelType) => {
    setSlidePanel((prev) => (prev === panel ? "none" : panel));
  };

  const templatesList = [
    {
      id: "tmpl-executive-board",
      title: "Executive Boardroom Deck",
      category: "Executive",
      badge: "Popular",
      color: "from-[#FF5148] to-orange-500",
      desc: "High-impact KPI telemetry with executive boardroom aesthetics.",
    },
    {
      id: "tmpl-financial-qbr",
      title: "Quarterly Business Review",
      category: "Finance",
      badge: "Finance",
      color: "from-amber-500 to-orange-600",
      desc: "Revenue waterfalls, churn decomposition, and ARR milestones.",
    },
    {
      id: "tmpl-saas-metrics",
      title: "SaaS Product Metrics",
      category: "Analytics",
      badge: "Product",
      color: "from-rose-500 to-[#FF5148]",
      desc: "User retention, funnel attribution, and cohort heatmaps.",
    },
    {
      id: "tmpl-tech-infra",
      title: "Tech Infrastructure & Cost",
      category: "Engineering",
      badge: "Engineering",
      color: "from-orange-500 to-amber-600",
      desc: "Cloud spend breakdown, cluster utilization, and SLAs.",
    },
  ];

  const filteredWorkspaces = workspaces.filter((w) => {
    if (!panelSearch.trim()) return true;
    const q = panelSearch.toLowerCase();
    return (
      (w.project_name && w.project_name.toLowerCase().includes(q)) ||
      (w.database_name && w.database_name.toLowerCase().includes(q))
    );
  });

  return (
    <>
      {/* ========================================================================= */}
      {/* MOBILE TOP BAR (Visible only on small screens) */}
      {/* ========================================================================= */}
      <div className="md:hidden sticky top-0 z-30 flex items-center justify-between px-4 h-14 bg-white border-b border-slate-200">
        <button
          onClick={() => setIsMobileOpen(!isMobileOpen)}
          className="p-2 rounded-lg text-slate-600 hover:bg-slate-100 transition-colors"
          aria-label="Toggle navigation"
        >
          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
          </svg>
        </button>

        <Link href="/dashboard" className="flex items-center gap-2">
          <div className="w-7 h-7 rounded-lg bg-[#FF5148] flex items-center justify-center text-white font-extrabold text-sm shadow-xs">
            K
          </div>
          <span className="font-extrabold text-base tracking-tight text-slate-900">
            Kelo<span className="text-[#FF5148]">Stats</span>
          </span>
        </Link>

        <button
          onClick={handleOpenCreateProject}
          className="w-8 h-8 rounded-full bg-[#FF5148] hover:bg-[#e64037] text-white flex items-center justify-center shadow-sm"
          title="Create Project"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M12 4v16m8-8H4" />
          </svg>
        </button>
      </div>

      {/* Mobile backdrop overlay */}
      {isMobileOpen && (
        <div
          onClick={() => setIsMobileOpen(false)}
          className="md:hidden fixed inset-0 bg-slate-900/40 backdrop-blur-xs z-40 animate-in fade-in duration-200"
        />
      )}

      {/* ========================================================================= */}
      {/* CANVA-STYLE VERTICAL ICON SLIDE BAR (ORANGE THEME) */}
      {/* ========================================================================= */}
      <aside
        data-nav-rail="true"
        className={`fixed md:sticky top-0 left-0 bottom-0 h-screen z-40 flex select-none transition-transform duration-300 ease-in-out ${
          isMobileOpen ? "translate-x-0" : "-translate-x-full md:translate-x-0"
        }`}
      >
        {/* Main Icon Rail */}
        <div className="w-[74px] h-full bg-white border-r border-slate-200/90 flex flex-col justify-between items-center py-3.5 shadow-xs z-50 shrink-0">
          {/* Top Section: Toggle button + Create Button + Nav Items */}
          <div className="flex flex-col items-center w-full gap-2.5">
            {/* 1. Sidebar Toggle Button [ | ] */}
            <button
              type="button"
              onClick={() => togglePanel(slidePanel === "none" ? "projects" : "none")}
              title={slidePanel === "none" ? "Expand sidebar panel" : "Collapse panel"}
              className={`w-10 h-10 rounded-xl flex items-center justify-center text-slate-600 hover:text-slate-900 hover:bg-slate-100 active:scale-95 transition-all cursor-pointer ${
                slidePanel !== "none" ? "bg-orange-50 text-[#FF5148]" : ""
              }`}
            >
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <rect x="3" y="3" width="18" height="18" rx="3" strokeWidth={1.8} />
                <path strokeLinecap="round" strokeWidth={1.8} d="M9 3v18" />
              </svg>
            </button>

            {/* 2. Circular Orange "+ Create" Action Button */}
            <div className="flex flex-col items-center group mt-1 mb-1">
              <button
                type="button"
                onClick={() => {
                  handleOpenCreateProject();
                  if (isMobileOpen) setIsMobileOpen(false);
                }}
                title="Create Presentation Workspace"
                className="w-11 h-11 rounded-full bg-gradient-to-tr from-[#FF5148] via-[#ff6145] to-[#ff7d52] text-white flex items-center justify-center shadow-md shadow-orange-500/30 hover:shadow-lg hover:shadow-orange-500/40 hover:scale-105 active:scale-95 transition-all duration-200 cursor-pointer"
              >
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.8} d="M12 4v16m8-8H4" />
                </svg>
              </button>
              <span className="text-[10.5px] font-semibold text-[#FF5148] tracking-tight mt-1 group-hover:text-[#e64037] transition-colors">
                Create
              </span>
            </div>

            {/* 3. Navigation Items Stack */}
            <div className="flex flex-col items-center w-full gap-1">
              {/* Item: Home */}
              <button
                type="button"
                onClick={() => {
                  setActiveTab("home");
                  setSlidePanel("none");
                  if (isMobileOpen) setIsMobileOpen(false);
                }}
                className={`w-full py-1.5 flex flex-col items-center justify-center group cursor-pointer transition-colors ${
                  activeTab === "home" ? "text-[#FF5148]" : "text-slate-600 hover:text-slate-900"
                }`}
              >
                <div
                  className={`w-10 h-8 rounded-full flex items-center justify-center transition-all ${
                    activeTab === "home"
                      ? "bg-orange-50 text-[#FF5148] shadow-2xs font-semibold"
                      : "group-hover:bg-slate-100"
                  }`}
                >
                  <svg className="w-5 h-5" fill={activeTab === "home" ? "currentColor" : "none"} stroke="currentColor" viewBox="0 0 24 24">
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={activeTab === "home" ? 1.5 : 1.8}
                      d="M3 10.5L12 3l9 7.5V20a1 1 0 01-1 1h-5a1 1 0 01-1-1v-5a1 1 0 00-1-1h-2a1 1 0 00-1 1v5a1 1 0 01-1 1H4a1 1 0 01-1-1v-9.5z"
                    />
                  </svg>
                </div>
                <span
                  className={`text-[10.5px] tracking-tight mt-0.5 leading-none ${
                    activeTab === "home" ? "font-bold text-slate-900" : "font-medium text-slate-600"
                  }`}
                >
                  Home
                </span>
              </button>

              {/* Item: Projects */}
              <button
                type="button"
                onClick={() => {
                  setActiveTab("home");
                  togglePanel("projects");
                }}
                className={`w-full py-1.5 flex flex-col items-center justify-center group cursor-pointer transition-colors ${
                  slidePanel === "projects" ? "text-[#FF5148]" : "text-slate-600 hover:text-slate-900"
                }`}
              >
                <div
                  className={`w-10 h-8 rounded-full flex items-center justify-center transition-all ${
                    slidePanel === "projects" ? "bg-orange-50 text-[#FF5148]" : "group-hover:bg-slate-100"
                  }`}
                >
                  <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={1.8}
                      d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z"
                    />
                  </svg>
                </div>
                <span
                  className={`text-[10.5px] tracking-tight mt-0.5 leading-none ${
                    slidePanel === "projects" ? "font-bold text-[#FF5148]" : "font-medium text-slate-600"
                  }`}
                >
                  Projects
                </span>
              </button>

              {/* Item: Templates */}
              <button
                type="button"
                onClick={() => {
                  setActiveTab("templates");
                  setSlidePanel("none");
                  if (isMobileOpen) setIsMobileOpen(false);
                }}
                className={`w-full py-1.5 flex flex-col items-center justify-center group cursor-pointer transition-colors ${
                  activeTab === "templates" ? "text-[#FF5148]" : "text-slate-600 hover:text-slate-900"
                }`}
              >
                <div
                  className={`w-10 h-8 rounded-full flex items-center justify-center transition-all ${
                    activeTab === "templates" ? "bg-orange-50 text-[#FF5148] shadow-2xs font-semibold" : "group-hover:bg-slate-100"
                  }`}
                >
                  <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <rect x="3" y="3" width="7" height="18" rx="1.5" strokeWidth={1.8} />
                    <rect x="14" y="3" width="7" height="8" rx="1.5" strokeWidth={1.8} />
                    <rect x="14" y="13" width="7" height="8" rx="1.5" strokeWidth={1.8} />
                  </svg>
                </div>
                <span
                  className={`text-[10.5px] tracking-tight mt-0.5 leading-none ${
                    activeTab === "templates" ? "font-bold text-slate-900" : "font-medium text-slate-600"
                  }`}
                >
                  Templates
                </span>
              </button>

              {/* Item: Databases (Crown removed) */}
              <button
                type="button"
                onClick={() => {
                  setActiveTab("databases");
                  setSlidePanel("none");
                  if (isMobileOpen) setIsMobileOpen(false);
                }}
                className={`w-full py-1.5 flex flex-col items-center justify-center group cursor-pointer transition-colors ${
                  activeTab === "databases" ? "text-[#FF5148]" : "text-slate-600 hover:text-slate-900"
                }`}
              >
                <div
                  className={`w-10 h-8 rounded-full flex items-center justify-center transition-all ${
                    activeTab === "databases"
                      ? "bg-orange-50 text-[#FF5148] shadow-2xs font-semibold"
                      : "group-hover:bg-slate-100"
                  }`}
                >
                  <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={1.8}
                      d="M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4m0 5c0 2.21-3.582 4-8 4s-8-1.79-8-4"
                    />
                  </svg>
                </div>
                <span
                  className={`text-[10.5px] tracking-tight mt-0.5 leading-none ${
                    activeTab === "databases" ? "font-bold text-slate-900" : "font-medium text-slate-600"
                  }`}
                >
                  Databases
                </span>
              </button>

              {/* Item: Documents */}
              <button
                type="button"
                onClick={() => {
                  setActiveTab("documents");
                  setSlidePanel("none");
                  if (isMobileOpen) setIsMobileOpen(false);
                }}
                className={`w-full py-1.5 flex flex-col items-center justify-center group cursor-pointer transition-colors ${
                  activeTab === "documents" ? "text-[#FF5148]" : "text-slate-600 hover:text-slate-900"
                }`}
              >
                <div
                  className={`w-10 h-8 rounded-full flex items-center justify-center transition-all ${
                    activeTab === "documents"
                      ? "bg-orange-50 text-[#FF5148] shadow-2xs font-semibold"
                      : "group-hover:bg-slate-100"
                  }`}
                >
                  <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={1.8}
                      d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
                    />
                  </svg>
                </div>
                <span
                  className={`text-[10.5px] tracking-tight mt-0.5 leading-none ${
                    activeTab === "documents" ? "font-bold text-slate-900" : "font-medium text-slate-600"
                  }`}
                >
                  Documents
                </span>
              </button>
            </div>
          </div>

          {/* Bottom Section: User Profile Avatar (Notification bell removed & Green dot removed) */}
          <div className="flex flex-col items-center w-full pt-2 border-t border-slate-100">
            {/* Profile Avatar Button */}
            <div className="relative" ref={profileRef}>
              <button
                type="button"
                onClick={() => setProfileOpen(!profileOpen)}
                title={user?.full_name || "Account Profile"}
                className="w-10 h-10 rounded-full bg-gradient-to-tr from-[#FF5148] to-[#ff7d52] text-white font-bold text-sm flex items-center justify-center shadow-sm hover:scale-105 active:scale-95 transition-all cursor-pointer"
              >
                {getInitials(user?.full_name)}
              </button>

              {/* Profile Dropdown Popover */}
              {profileOpen && (
                <div className="absolute left-14 bottom-0 w-64 bg-white rounded-2xl shadow-2xl border border-slate-200 py-2 z-50 animate-in fade-in slide-in-from-left-2 duration-150">
                  <div className="px-4 py-3 border-b border-slate-100">
                    <p className="text-sm font-bold text-slate-800 leading-tight">
                      {user?.full_name || "User"}
                    </p>
                    <p className="text-xs text-slate-500 truncate mt-0.5">
                      {user?.email || "user@company.com"}
                    </p>
                    <div className="mt-2 inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-emerald-50 border border-emerald-200 text-[10px] font-semibold text-emerald-700">
                      <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
                      <span>Active Account</span>
                    </div>
                  </div>

                  <div className="py-1">
                    <button
                      type="button"
                      onClick={() => {
                        setActiveTab("home");
                        setProfileOpen(false);
                      }}
                      className="w-full px-4 py-2 text-left text-sm text-slate-700 hover:bg-slate-50 flex items-center gap-2.5 transition-colors cursor-pointer"
                    >
                      <svg className="w-4 h-4 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
                      </svg>
                      <span>My Profile</span>
                    </button>

                    <button
                      type="button"
                      onClick={() => {
                        setActiveTab("databases");
                        setProfileOpen(false);
                      }}
                      className="w-full px-4 py-2 text-left text-sm text-slate-700 hover:bg-slate-50 flex items-center gap-2.5 transition-colors cursor-pointer"
                    >
                      <svg className="w-4 h-4 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4m0 5c0 2.21-3.582 4-8 4s-8-1.79-8-4" />
                      </svg>
                      <span>Database Settings</span>
                    </button>
                  </div>

                  <div className="border-t border-slate-100 pt-1">
                    <button
                      type="button"
                      onClick={() => {
                        setProfileOpen(false);
                        handleLogout();
                      }}
                      className="w-full px-4 py-2 text-left text-sm text-rose-600 hover:bg-rose-50 font-semibold flex items-center gap-2.5 transition-colors cursor-pointer"
                    >
                      <svg className="w-4 h-4 text-rose-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" />
                      </svg>
                      <span>Log Out</span>
                    </button>
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>

        {/* ======================================================================= */}
        {/* SLIDE-OUT DRAWER PANEL (ORANGE THEME) */}
        {/* ======================================================================= */}
        {slidePanel !== "none" && (
          <div
            ref={slideDrawerRef}
            className="w-72 sm:w-80 h-full bg-white border-r border-slate-200 shadow-xl flex flex-col animate-in slide-in-from-left duration-200 z-40 shrink-0"
          >
            {/* Drawer Header */}
            <div className="p-4 border-b border-slate-100 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className="font-bold text-slate-800 text-sm capitalize">
                  {slidePanel}
                </span>
                {slidePanel === "projects" && (
                  <span className="px-2 py-0.5 text-[10px] font-bold rounded-full bg-orange-50 text-[#FF5148]">
                    {workspaces.length}
                  </span>
                )}
              </div>
              <button
                type="button"
                onClick={() => setSlidePanel("none")}
                className="w-7 h-7 rounded-lg text-slate-400 hover:text-slate-700 hover:bg-slate-100 flex items-center justify-center transition-colors cursor-pointer text-base"
              >
                ✕
              </button>
            </div>

            {/* PANEL CONTENT: PROJECTS */}
            {slidePanel === "projects" && (
              <div className="flex-1 flex flex-col overflow-hidden p-3 space-y-3">
                <div className="relative">
                  <input
                    type="text"
                    value={panelSearch}
                    onChange={(e) => setPanelSearch(e.target.value)}
                    placeholder="Filter projects..."
                    className="w-full pl-8 pr-3 py-1.5 text-xs rounded-lg border border-slate-200 bg-slate-50 focus:bg-white focus:outline-none focus:ring-2 focus:ring-[#FF5148]/30"
                  />
                  <svg className="w-3.5 h-3.5 text-slate-400 absolute left-2.5 top-1/2 -translate-y-1/2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
                  </svg>
                </div>

                <div className="flex-1 overflow-y-auto space-y-2 pr-1">
                  {filteredWorkspaces.length === 0 ? (
                    <div className="text-center py-8 text-xs text-slate-400">
                      No matching projects found
                    </div>
                  ) : (
                    filteredWorkspaces.map((ws) => (
                      <div
                        key={ws.project_id}
                        onClick={() => {
                          if (onSelectProject) onSelectProject(ws);
                          setSlidePanel("none");
                        }}
                        className="p-2.5 rounded-xl border border-slate-200/80 hover:border-orange-300 bg-white hover:bg-orange-50/40 transition-all cursor-pointer group shadow-2xs"
                      >
                        <div className="flex items-center justify-between">
                          <span className="font-semibold text-xs text-slate-800 group-hover:text-[#FF5148] truncate">
                            {ws.project_name || "Untitled Project"}
                          </span>
                          <span className="text-[10px] text-slate-400">
                            {ws.slide_count || 0} slides
                          </span>
                        </div>
                        <p className="text-[11px] text-slate-500 mt-1 truncate">
                          DB: {ws.database_display_name || ws.database_name || "Telemetry Source"}
                        </p>
                      </div>
                    ))
                  )}
                </div>

                <button
                  type="button"
                  onClick={() => {
                    handleOpenCreateProject();
                    setSlidePanel("none");
                  }}
                  className="w-full py-2 rounded-xl text-xs font-bold text-white bg-[#FF5148] hover:bg-[#e64037] transition-all flex items-center justify-center gap-1.5 shadow-sm"
                >
                  <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M12 4v16m8-8H4" />
                  </svg>
                  <span>New Project</span>
                </button>
              </div>
            )}

            {/* PANEL CONTENT: TEMPLATES */}
            {slidePanel === "templates" && (
              <div className="flex-1 flex flex-col overflow-hidden p-3 space-y-3">
                <p className="text-xs text-slate-500">
                  Boardroom-ready deck templates tuned for executive storytelling.
                </p>

                <div className="flex-1 overflow-y-auto space-y-2.5 pr-1">
                  {templatesList.map((tmpl) => (
                    <div
                      key={tmpl.id}
                      onClick={() => {
                        handleOpenCreateProject();
                        setSlidePanel("none");
                      }}
                      className="p-3 rounded-xl border border-slate-200/80 hover:border-orange-300 bg-white hover:bg-orange-50/40 transition-all cursor-pointer group shadow-2xs"
                    >
                      <div className="flex items-center justify-between mb-1.5">
                        <span className={`px-2 py-0.5 rounded-md text-[9px] font-bold text-white bg-gradient-to-r ${tmpl.color}`}>
                          {tmpl.badge}
                        </span>
                        <span className="text-[10px] font-medium text-[#FF5148] opacity-0 group-hover:opacity-100 transition-opacity">
                          Use →
                        </span>
                      </div>
                      <h4 className="font-bold text-xs text-slate-800 group-hover:text-[#FF5148] transition-colors">
                        {tmpl.title}
                      </h4>
                      <p className="text-[11px] text-slate-500 mt-1 leading-snug">
                        {tmpl.desc}
                      </p>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </aside>
    </>
  );
}
