"use client";

import React, { useState, useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import { API_BASE_URL } from "@/lib/config";

export interface TemplateItem {
  template_id: string;
  template_name: string;
  category: string;
  preview_url: string;
}

export interface SlideItem {
  slide_number: number;
  filename: string;
  name: string;
  s3_key?: string;
  raw_html?: string;
  rendered_html: string;
}

export interface DatabaseItem {
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

interface TemplatesPageProps {
  onNavigateTab?: (tab: "home" | "databases" | "documents") => void;
}

export default function TemplatesPage({ onNavigateTab }: TemplatesPageProps) {
  const router = useRouter();

  // Template listing state
  const [templates, setTemplates] = useState<TemplateItem[]>([]);
  const [loadingTemplates, setLoadingTemplates] = useState(true);
  const [templateError, setTemplateError] = useState<string | null>(null);

  // Active view: null = catalog grid; TemplateItem = slide detail preview
  const [selectedTemplate, setSelectedTemplate] = useState<TemplateItem | null>(null);

  // Slide preview state
  const [slides, setSlides] = useState<SlideItem[]>([]);
  const [loadingSlides, setLoadingSlides] = useState(false);
  const [slideError, setSlideError] = useState<string | null>(null);

  // Search and categories
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedCategory, setSelectedCategory] = useState("all");

  // Favorites tracking (stored in localStorage)
  const [favorites, setFavorites] = useState<Record<string, boolean>>({});

  // "+ Create Project" Modal state
  const [createModalOpen, setCreateModalOpen] = useState(false);
  const [targetTemplateForModal, setTargetTemplateForModal] = useState<TemplateItem | null>(null);
  const [projectName, setProjectName] = useState("");
  const [availableDbs, setAvailableDbs] = useState<DatabaseItem[]>([]);
  const [loadingDbs, setLoadingDbs] = useState(false);
  const [selectedDbId, setSelectedDbId] = useState<string | null>(null);
  const [isCreatingProject, setIsCreatingProject] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);

  // Load user info from localStorage
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

  // Load favorites from localStorage
  useEffect(() => {
    if (typeof window !== "undefined") {
      try {
        const saved = localStorage.getItem("kelostats_favorite_templates");
        if (saved) {
          setFavorites(JSON.parse(saved));
        }
      } catch {
        // ignore
      }
    }
  }, []);

  const toggleFavorite = (templateId: string, e?: React.MouseEvent) => {
    if (e) e.stopPropagation();
    setFavorites((prev) => {
      const updated = { ...prev, [templateId]: !prev[templateId] };
      try {
        localStorage.setItem("kelostats_favorite_templates", JSON.stringify(updated));
      } catch {
        // ignore
      }
      return updated;
    });
  };

  // Fetch templates catalog
  const fetchTemplates = async () => {
    setLoadingTemplates(true);
    setTemplateError(null);
    try {
      const res = await fetch(`${API_BASE_URL}/api/get/templates`);
      if (!res.ok) {
        throw new Error(`Failed to load templates (${res.status})`);
      }
      const data = await res.json();
      setTemplates(data.templates || []);
    } catch (err: any) {
      console.error("Error loading templates:", err);
      setTemplateError(err.message || "Failed to load templates");
    } finally {
      setLoadingTemplates(false);
    }
  };

  useEffect(() => {
    fetchTemplates();
  }, []);

  // Fetch slides when a template is selected for preview
  useEffect(() => {
    if (!selectedTemplate) {
      setSlides([]);
      return;
    }

    const fetchSlides = async () => {
      setLoadingSlides(true);
      setSlideError(null);
      try {
        const res = await fetch(`${API_BASE_URL}/api/templates/${selectedTemplate.template_id}/slides`);
        if (!res.ok) {
          throw new Error(`Failed to fetch slides for template (${res.status})`);
        }
        const data = await res.json();
        setSlides(data.slides || []);
      } catch (err: any) {
        console.error("Error loading template slides:", err);
        setSlideError(err.message || "Could not load slide codes from S3");
      } finally {
        setLoadingSlides(false);
      }
    };

    fetchSlides();
  }, [selectedTemplate]);

  // Open Create Project Modal
  const openCreateModal = async (tmpl: TemplateItem, e?: React.MouseEvent) => {
    if (e) e.stopPropagation();
    setTargetTemplateForModal(tmpl);
    setProjectName(`${tmpl.template_name.split(" ").slice(0, 4).join(" ")} Project`);
    setCreateError(null);
    setCreateModalOpen(true);

    // Fetch user databases
    setLoadingDbs(true);
    const userId = getUserId();
    try {
      const res = await fetch(`${API_BASE_URL}/api/databases/database_info?user_id=${userId}`);
      if (res.ok) {
        const data = await res.json();
        const dbs: DatabaseItem[] = data.databases || [];
        setAvailableDbs(dbs);
        if (dbs.length > 0 && !selectedDbId) {
          setSelectedDbId(dbs[0].db_id);
        }
      }
    } catch (err) {
      console.error("Error loading databases for template project:", err);
    } finally {
      setLoadingDbs(false);
    }
  };

  // Submit Create Project
  const handleCreateProjectSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!projectName.trim()) {
      setCreateError("Please enter a project name.");
      return;
    }
    if (!selectedDbId) {
      setCreateError("Please select a database for this project.");
      return;
    }
    if (!targetTemplateForModal) {
      setCreateError("No template selected.");
      return;
    }

    setIsCreatingProject(true);
    setCreateError(null);

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
          template_id: targetTemplateForModal.template_id,
        }),
      });

      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail || "Failed to create project from template.");
      }

      setCreateModalOpen(false);
      const projectId = data.project_id || "";
      const projName = encodeURIComponent(data.project_name || projectName.trim());

      // Redirect directly to workspace
      router.push(
        `/dashboard/workspace?user_id=${userId}&userid_id=${userId}&database_id=${selectedDbId}&template_id=${targetTemplateForModal.template_id}&project_id=${projectId}&project_name=${projName}`
      );
    } catch (err: any) {
      console.error("Project creation error:", err);
      setCreateError(err.message || "An unexpected error occurred. Please try again.");
    } finally {
      setIsCreatingProject(false);
    }
  };

  // Extract unique categories
  const categories = ["all", ...Array.from(new Set(templates.map((t) => t.category).filter(Boolean)))];

  // Filter templates
  const filteredTemplates = templates.filter((t) => {
    const matchesSearch =
      !searchQuery.trim() ||
      t.template_name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      t.category.toLowerCase().includes(searchQuery.toLowerCase());
    const matchesCategory = selectedCategory === "all" || t.category.toLowerCase() === selectedCategory.toLowerCase();
    return matchesSearch && matchesCategory;
  });

  // ============================================================================
  // VIEW 2: SLIDE DETAIL PREVIEW (When user clicked a template card)
  // ============================================================================
  if (selectedTemplate) {
    const isFav = !!favorites[selectedTemplate.template_id];
    return (
      <div className="fixed inset-0 z-50 bg-[#f4f6f9] flex flex-col overflow-y-auto animate-in fade-in duration-150">
        {/* ===================================================================== */}
        {/* TOP PERSISTENT PREVIEW NAVIGATION BAR */}
        {/* Matches Image 2: < Back | [P] Template_Name.pptx   [♡] [+ Create Project] */}
        {/* ===================================================================== */}
        <header className="sticky top-0 z-30 bg-white border-b border-slate-200/90 px-6 sm:px-10 h-16 flex items-center justify-between shadow-xs shrink-0">
          {/* Left: Back button & Title */}
          <div className="flex items-center gap-3 sm:gap-4 min-w-0">
            <button
              onClick={() => setSelectedTemplate(null)}
              className="px-3 py-1.5 rounded-lg text-sm font-semibold text-slate-600 hover:text-slate-900 hover:bg-slate-100 flex items-center gap-1.5 transition-all cursor-pointer shrink-0"
              title="Return to templates catalog"
            >
              <svg className="w-4 h-4 text-slate-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.2} d="M15 19l-7-7 7-7" />
              </svg>
              <span>Back</span>
            </button>

            <div className="h-5 w-px bg-slate-200 shrink-0" />

            {/* PowerPoint Icon + File Title */}
            <div className="flex items-center gap-2.5 min-w-0">
              <div className="w-7 h-7 rounded-md bg-gradient-to-br from-[#FF5148] to-orange-600 text-white flex items-center justify-center font-black text-xs shadow-xs shrink-0">
                P
              </div>
              <h1 className="text-sm sm:text-base font-bold text-slate-900 truncate max-w-xs sm:max-w-md lg:max-w-xl">
                {selectedTemplate.template_name}.pptx
              </h1>
            </div>
          </div>

          {/* Right: Actions */}
          <div className="flex items-center gap-3 shrink-0">
            {/* Heart Favorite Button */}
            <button
              onClick={(e) => toggleFavorite(selectedTemplate.template_id, e)}
              className={`w-9 h-9 rounded-xl border flex items-center justify-center transition-all cursor-pointer ${
                isFav
                  ? "border-rose-200 bg-rose-50 text-rose-500"
                  : "border-slate-200 text-slate-400 hover:text-rose-500 hover:border-rose-200 hover:bg-slate-50"
              }`}
              title={isFav ? "Favorited" : "Add to favorites"}
            >
              <svg className="w-4 h-4" fill={isFav ? "currentColor" : "none"} stroke="currentColor" viewBox="0 0 24 24">
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M4.318 6.318a4.5 4.5 0 000 6.364L12 20.364l7.682-7.682a4.5 4.5 0 00-6.364-6.364L12 7.636l-1.318-1.318a4.5 4.5 0 00-6.364 0z"
                />
              </svg>
            </button>

            {/* Primary Action: + Create Project (Replacing Download per instructions) */}
            <button
              onClick={(e) => openCreateModal(selectedTemplate, e)}
              className="px-5 py-2.5 rounded-xl bg-[#FF5148] hover:bg-[#e64037] text-white font-bold text-sm shadow-md hover:shadow-lg hover:scale-[1.02] active:scale-[0.98] transition-all flex items-center gap-2 cursor-pointer"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M12 4v16m8-8H4" />
              </svg>
              <span>Create Project</span>
            </button>
          </div>
        </header>

        {/* ===================================================================== */}
        {/* MAIN SLIDES PREVIEW CANVAS: VERTICALLY STACKED 16:9 SLIDES */}
        {/* Matches Image 2 layout */}
        {/* ===================================================================== */}
        <main className="flex-1 py-10 px-4 sm:px-8 max-w-[1280px] w-full mx-auto">
          {loadingSlides ? (
            <div className="flex flex-col items-center justify-center py-24 space-y-4">
              <div className="w-10 h-10 border-3 border-orange-200 border-t-[#FF5148] rounded-full animate-spin" />
              <p className="text-sm font-medium text-slate-500">Loading slide presentation codes from S3...</p>
            </div>
          ) : slideError ? (
            <div className="p-8 bg-white border border-rose-200 rounded-2xl text-center max-w-md mx-auto shadow-sm">
              <div className="w-12 h-12 rounded-full bg-rose-50 text-rose-500 flex items-center justify-center mx-auto mb-3">
                <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
              </div>
              <h3 className="font-bold text-slate-800">Unable to load slides</h3>
              <p className="text-xs text-slate-500 mt-1">{slideError}</p>
              <button
                onClick={() => setSelectedTemplate(null)}
                className="mt-4 px-4 py-2 bg-slate-100 hover:bg-slate-200 text-slate-700 text-xs font-bold rounded-lg transition-colors"
              >
                Back to Templates
              </button>
            </div>
          ) : slides.length === 0 ? (
            <div className="p-12 bg-white border border-slate-200 rounded-2xl text-center max-w-md mx-auto shadow-sm">
              <p className="text-sm font-semibold text-slate-700">No slides found in S3 for this template.</p>
              <button
                onClick={() => setSelectedTemplate(null)}
                className="mt-4 px-4 py-2 bg-[#FF5148] text-white text-xs font-bold rounded-lg"
              >
                Return to Templates
              </button>
            </div>
          ) : (
            <div className="space-y-12">
              {slides.map((slide, idx) => (
                <div key={slide.filename || idx} className="flex flex-col items-center group">
                  {/* Slide Container with 16:9 Aspect Ratio */}
                  <div
                    className="w-full aspect-[16/9] bg-white rounded-xl shadow-xl overflow-hidden border border-slate-200/80 relative transition-transform duration-200"
                    style={{ containerType: "inline-size" }}
                  >
                    <div
                      className="w-full h-full relative"
                      dangerouslySetInnerHTML={{ __html: slide.rendered_html }}
                    />
                  </div>

                  {/* Slide numbering label */}
                  <div className="mt-3 flex items-center gap-2 text-xs text-slate-400 font-medium">
                    <span>
                      Slide {idx + 1} of {slides.length}
                    </span>
                    <span>•</span>
                    <span className="font-semibold text-slate-600">{slide.name}</span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </main>

        {/* Modal: Create Project (Shared) */}
        {renderCreateProjectModal()}
      </div>
    );
  }

  // ============================================================================
  // VIEW 1: TEMPLATES CATALOG GRID (Matches Image 1)
  // ============================================================================
  return (
    <div className="w-full flex-1 min-h-screen bg-[#f8fafc] px-6 sm:px-10 lg:px-12 py-8 space-y-8 animate-in fade-in duration-200">
      {/* ======================================================================= */}
      {/* HEADER SECTION */}
      {/* ======================================================================= */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-6 pb-2 border-b border-slate-100">
        <div>
          <div className="flex items-center gap-2.5">
            <h1 className="text-2xl sm:text-3xl font-extrabold text-slate-900 tracking-tight">Presentation Templates</h1>
            <span className="px-2.5 py-0.5 rounded-full text-xs font-bold bg-orange-50 text-[#FF5148] border border-orange-200/80">
              {templates.length} {templates.length === 1 ? "Template" : "Templates"}
            </span>
          </div>
          <p className="text-sm text-slate-500 mt-1 max-w-2xl">
            Choose from boardroom-grade PowerPoint decks. Click any template to inspect live HTML slides or create a new presentation.
          </p>
        </div>

        {/* Search Bar */}
        <div className="relative shrink-0">
          <svg
            className="w-4 h-4 text-slate-400 absolute left-3.5 top-1/2 -translate-y-1/2 pointer-events-none"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
          >
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
          </svg>
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search templates..."
            className="pl-10 pr-4 py-2.5 text-sm rounded-xl border border-slate-200 bg-white text-slate-800 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-[#FF5148]/20 focus:border-[#FF5148] transition-all w-full sm:w-72 shadow-2xs"
          />
          {searchQuery && (
            <button
              onClick={() => setSearchQuery("")}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600 font-bold text-xs"
            >
              ✕
            </button>
          )}
        </div>
      </div>

      {/* ======================================================================= */}
      {/* CATEGORY FILTER TABS */}
      {/* ======================================================================= */}
      {categories.length > 1 && (
        <div className="flex items-center gap-2 overflow-x-auto pb-1 scrollbar-none">
          {categories.map((cat) => {
            const active = selectedCategory.toLowerCase() === cat.toLowerCase();
            return (
              <button
                key={cat}
                onClick={() => setSelectedCategory(cat)}
                className={`px-4 py-1.5 rounded-xl text-xs font-semibold whitespace-nowrap capitalize transition-all cursor-pointer ${
                  active
                    ? "bg-[#FF5148] text-white shadow-xs"
                    : "bg-white text-slate-600 hover:text-slate-900 border border-slate-200 hover:border-slate-300"
                }`}
              >
                {cat === "all" ? "All Categories" : cat}
              </button>
            );
          })}
        </div>
      )}

      {/* ======================================================================= */}
      {/* TEMPLATES GRID (Matches Image 1) */}
      {/* ======================================================================= */}
      {loadingTemplates ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-6">
          {[1, 2, 3, 4].map((n) => (
            <div key={n} className="rounded-2xl border border-slate-200 bg-white p-3 space-y-3 animate-pulse">
              <div className="aspect-[16/9] w-full bg-slate-100 rounded-xl" />
              <div className="h-4 bg-slate-100 rounded w-3/4" />
              <div className="h-3 bg-slate-50 rounded w-1/2" />
            </div>
          ))}
        </div>
      ) : templateError ? (
        <div className="p-8 rounded-2xl bg-white border border-rose-200 text-center max-w-lg mx-auto shadow-sm">
          <p className="text-sm font-semibold text-rose-600">{templateError}</p>
          <button
            onClick={fetchTemplates}
            className="mt-3 px-4 py-2 bg-slate-100 hover:bg-slate-200 text-slate-700 text-xs font-bold rounded-lg transition-colors"
          >
            Retry Loading
          </button>
        </div>
      ) : filteredTemplates.length === 0 ? (
        <div className="p-12 rounded-2xl bg-white border border-dashed border-slate-200 text-center max-w-md mx-auto">
          <p className="text-sm font-bold text-slate-700">No templates found</p>
          <p className="text-xs text-slate-400 mt-1">Try adjusting your search query or category filter.</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-6">
          {filteredTemplates.map((template) => {
            const isFav = !!favorites[template.template_id];
            const previewImgSrc = `${API_BASE_URL}${template.preview_url}`;

            return (
              <div
                key={template.template_id}
                onClick={() => setSelectedTemplate(template)}
                className="group flex flex-col cursor-pointer"
              >
                {/* 16:9 Card Preview Container with Drop Shadow & Hover Action */}
                <div className="relative aspect-[16/9] w-full rounded-2xl overflow-hidden bg-white border border-slate-200/90 shadow-sm group-hover:shadow-xl group-hover:border-[#FF5148]/50 transition-all duration-300">
                  {/* S3 Preview Image */}
                  <img
                    src={previewImgSrc}
                    alt={template.template_name}
                    loading="lazy"
                    className="w-full h-full object-cover transition-transform duration-300 group-hover:scale-[1.03]"
                    onError={(e) => {
                      // Fallback if image fails
                      (e.target as HTMLElement).style.display = "none";
                    }}
                  />

                  {/* Fallback pattern background behind image */}
                  <div className="absolute inset-0 bg-gradient-to-br from-orange-50/50 via-white to-orange-100/30 -z-10 flex items-center justify-center p-4">
                    <div className="text-center">
                      <div className="w-10 h-10 rounded-xl bg-orange-100 text-[#FF5148] flex items-center justify-center mx-auto mb-2 font-black text-sm">
                        PPT
                      </div>
                      <p className="text-xs font-bold text-slate-700 line-clamp-1">{template.template_name}</p>
                    </div>
                  </div>

                  {/* Top-Right Favorite Button */}
                  <button
                    type="button"
                    onClick={(e) => toggleFavorite(template.template_id, e)}
                    className={`absolute top-2.5 right-2.5 w-8 h-8 rounded-full flex items-center justify-center transition-all z-10 ${
                      isFav
                        ? "bg-white text-rose-500 shadow-md"
                        : "bg-white/80 backdrop-blur-xs text-slate-400 hover:text-rose-500 hover:bg-white shadow-xs opacity-0 group-hover:opacity-100"
                    }`}
                    title={isFav ? "Favorited" : "Favorite"}
                  >
                    <svg
                      className="w-4 h-4"
                      fill={isFav ? "currentColor" : "none"}
                      stroke="currentColor"
                      viewBox="0 0 24 24"
                    >
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        strokeWidth={2}
                        d="M4.318 6.318a4.5 4.5 0 000 6.364L12 20.364l7.682-7.682a4.5 4.5 0 00-6.364-6.364L12 7.636l-1.318-1.318a4.5 4.5 0 00-6.364 0z"
                      />
                    </svg>
                  </button>

                  {/* Hover Overlay with Action Buttons (Matches Image 1 hover state: Heart + Download replaced by + Create Project) */}
                  <div className="absolute inset-x-0 bottom-0 p-3 bg-gradient-to-t from-black/60 via-black/30 to-transparent flex items-center justify-end gap-2 opacity-0 group-hover:opacity-100 transition-opacity duration-200">
                    <button
                      type="button"
                      onClick={(e) => openCreateModal(template, e)}
                      className="px-3.5 py-1.5 rounded-xl bg-[#FF5148] hover:bg-[#e64037] text-white font-bold text-xs shadow-md hover:shadow-lg flex items-center gap-1.5 transition-all cursor-pointer"
                      title="Create presentation with this template"
                    >
                      <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M12 4v16m8-8H4" />
                      </svg>
                      <span>Create Project</span>
                    </button>
                  </div>
                </div>

                {/* Template Title and Metadata (Matches Image 1 captions) */}
                <div className="mt-2.5 flex flex-col">
                  <h3 className="font-bold text-sm text-slate-800 line-clamp-1 group-hover:text-[#FF5148] transition-colors">
                    {template.template_name}
                  </h3>
                  <div className="flex items-center gap-2 mt-0.5">
                    <span className="text-xs text-slate-400 capitalize font-medium">{template.category || "Presentation"}</span>
                    <span className="text-[10px] text-slate-300">•</span>
                    <span className="text-[11px] text-orange-600 font-semibold group-hover:underline">Preview Slides →</span>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Modal: Create Project (Shared) */}
      {renderCreateProjectModal()}
    </div>
  );

  // ============================================================================
  // STREAMLINED MODAL: CREATE PROJECT FROM TEMPLATE
  // User Requirement: "here user can only enter project name & select databases that's it"
  // ============================================================================
  function renderCreateProjectModal() {
    if (!createModalOpen || !targetTemplateForModal) return null;

    return (
      <div
        className="fixed inset-0 z-50 bg-black/50 backdrop-blur-sm flex items-center justify-center p-4 animate-in fade-in duration-150"
        onClick={() => !isCreatingProject && setCreateModalOpen(false)}
      >
        <div
          className="bg-white border border-slate-200 rounded-2xl w-full max-w-lg shadow-2xl overflow-hidden animate-in zoom-in-95 duration-200 flex flex-col"
          onClick={(e) => e.stopPropagation()}
        >
          {/* Header */}
          <div className="px-6 py-4 border-b border-slate-100 flex items-center justify-between bg-slate-50/50">
            <div className="flex items-center gap-3">
              <div className="w-9 h-9 rounded-xl bg-orange-100 text-[#FF5148] flex items-center justify-center font-black text-sm">
                +
              </div>
              <div>
                <h2 className="text-base font-bold text-slate-900 leading-tight">Create Presentation Project</h2>
                <p className="text-xs text-slate-500 mt-0.5">Configure your project details to launch workspace</p>
              </div>
            </div>
            <button
              onClick={() => !isCreatingProject && setCreateModalOpen(false)}
              className="text-slate-400 hover:text-slate-600 p-1.5 rounded-lg hover:bg-slate-100 transition-colors"
            >
              ✕
            </button>
          </div>

          {/* Form */}
          <form onSubmit={handleCreateProjectSubmit} className="p-6 space-y-5">
            {/* Selected Template Badge (Pre-selected, no selection needed!) */}
            <div className="p-3 rounded-xl bg-orange-50/60 border border-orange-200/80 flex items-center gap-3">
              <div className="w-12 h-8 rounded-lg overflow-hidden bg-white border border-orange-200/60 shrink-0">
                <img
                  src={`${API_BASE_URL}${targetTemplateForModal.preview_url}`}
                  alt=""
                  className="w-full h-full object-cover"
                />
              </div>
              <div className="min-w-0 flex-1">
                <span className="text-[10px] font-bold text-[#FF5148] uppercase tracking-wider block">Chosen Template</span>
                <p className="text-xs font-bold text-slate-800 truncate">{targetTemplateForModal.template_name}</p>
              </div>
            </div>

            {/* Field 1: Project Name */}
            <div>
              <label className="block text-xs font-bold text-slate-700 mb-1.5">
                Project Name <span className="text-rose-500">*</span>
              </label>
              <input
                type="text"
                value={projectName}
                onChange={(e) => setProjectName(e.target.value)}
                placeholder="e.g. Q4 Executive Growth Pitch Deck"
                required
                autoFocus
                className="w-full px-3.5 py-2.5 rounded-xl border border-slate-200 text-sm focus:outline-none focus:ring-2 focus:ring-[#FF5148]/20 focus:border-[#FF5148] transition-all"
              />
            </div>

            {/* Field 2: Select Database */}
            <div>
              <div className="flex items-center justify-between mb-1.5">
                <label className="block text-xs font-bold text-slate-700">
                  Select Connected Database <span className="text-rose-500">*</span>
                </label>
                {onNavigateTab && (
                  <button
                    type="button"
                    onClick={() => {
                      setCreateModalOpen(false);
                      onNavigateTab("databases");
                    }}
                    className="text-[11px] font-semibold text-[#FF5148] hover:underline"
                  >
                    + Connect New
                  </button>
                )}
              </div>

              {loadingDbs ? (
                <div className="p-4 bg-slate-50 rounded-xl text-center text-xs text-slate-400">
                  Loading connected databases...
                </div>
              ) : availableDbs.length === 0 ? (
                <div className="p-4 rounded-xl border border-dashed border-amber-300 bg-amber-50/50 text-center">
                  <p className="text-xs font-semibold text-amber-800">No connected databases found.</p>
                  <p className="text-[11px] text-amber-600 mt-0.5">Please connect a database first to generate data presentations.</p>
                </div>
              ) : (
                <div className="space-y-2 max-h-48 overflow-y-auto pr-1">
                  {availableDbs.map((db) => {
                    const isSelected = selectedDbId === db.db_id;
                    return (
                      <div
                        key={db.db_id}
                        onClick={() => setSelectedDbId(db.db_id)}
                        className={`p-3 rounded-xl border cursor-pointer transition-all flex items-center justify-between ${
                          isSelected
                            ? "border-[#FF5148] bg-orange-50/40 shadow-xs ring-1 ring-[#FF5148]/20"
                            : "border-slate-200 hover:border-slate-300 hover:bg-slate-50"
                        }`}
                      >
                        <div className="flex items-center gap-2.5 min-w-0">
                          <div
                            className={`w-7 h-7 rounded-lg flex items-center justify-center font-black text-[10px] uppercase ${
                              db.database_type === "postgres"
                                ? "bg-blue-100 text-blue-700"
                                : db.database_type === "mysql"
                                ? "bg-amber-100 text-amber-700"
                                : "bg-red-100 text-red-700"
                            }`}
                          >
                            {db.database_type.slice(0, 2)}
                          </div>
                          <div className="min-w-0">
                            <p className="text-xs font-bold text-slate-800 truncate">
                              {db.display_name || db.database_name || "Database"}
                            </p>
                            <p className="text-[10px] text-slate-400 truncate">
                              {db.username}@{db.host}:{db.port}
                            </p>
                          </div>
                        </div>

                        {/* Radio Checkbox */}
                        <div
                          className={`w-4 h-4 rounded-full border flex items-center justify-center shrink-0 ${
                            isSelected ? "border-[#FF5148] bg-[#FF5148]" : "border-slate-300"
                          }`}
                        >
                          {isSelected && <div className="w-1.5 h-1.5 rounded-full bg-white" />}
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>

            {/* Error notice */}
            {createError && (
              <div className="p-3 rounded-xl bg-rose-50 border border-rose-200 text-xs text-rose-600 font-medium">
                {createError}
              </div>
            )}

            {/* Actions */}
            <div className="pt-2 flex items-center justify-end gap-2.5">
              <button
                type="button"
                onClick={() => setCreateModalOpen(false)}
                disabled={isCreatingProject}
                className="px-4 py-2.5 rounded-xl border border-slate-200 text-xs font-semibold text-slate-600 hover:bg-slate-50 transition-colors"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={isCreatingProject || !selectedDbId || !projectName.trim()}
                className="px-5 py-2.5 rounded-xl bg-[#FF5148] hover:bg-[#e64037] disabled:opacity-50 text-white text-xs font-bold shadow-sm transition-all flex items-center gap-2 cursor-pointer"
              >
                {isCreatingProject ? (
                  <>
                    <div className="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                    <span>Creating Workspace...</span>
                  </>
                ) : (
                  <>
                    <span>Create Project</span>
                    <span>→</span>
                  </>
                )}
              </button>
            </div>
          </form>
        </div>
      </div>
    );
  }
}
