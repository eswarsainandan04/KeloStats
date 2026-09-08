"use client";

import React, { useState, useEffect, useRef, Suspense } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { API_BASE_URL } from "@/lib/config";
import ChatInterface from "./ChatInterface";
import Chart from "chart.js/auto";

interface SlideData {
  slide_number: number;
  filename?: string;
  name: string;
  s3_key?: string;
  json?: any;
  rendered_html: string;
}

function WorkspaceContent() {
  const searchParams = useSearchParams();

  const userId = searchParams.get("user_id") || searchParams.get("userid_id") || "00000000-0000-0000-0000-000000000000";
  const projectId = searchParams.get("project_id") || "project_default";
  const projectName = searchParams.get("project_name") || "Presentation Project";
  const databaseId = searchParams.get("database_id") || searchParams.get("db_id") || "";

  // Dynamic slides loaded directly from Supabase S3 JSON files
  const [slides, setSlides] = useState<SlideData[]>([]);
  const [activeSlideIndex, setActiveSlideIndex] = useState(0);

  // Left sidebar open/collapsed state
  const [isSidebarOpen, setIsSidebarOpen] = useState(true);

  // Right sidebar (Chatbot) open/collapsed & resizable state
  const [isChatOpen, setIsChatOpen] = useState(true);
  const [chatWidth, setChatWidth] = useState(380);
  const [isDraggingChat, setIsDraggingChat] = useState(false);
  const isDraggingRef = useRef(false);
  const slideCanvasRef = useRef<HTMLDivElement>(null);

  const handleMouseDownResize = (e: React.MouseEvent) => {
    e.preventDefault();
    isDraggingRef.current = true;
    setIsDraggingChat(true);

    const onMouseMove = (moveEvent: MouseEvent) => {
      if (!isDraggingRef.current) return;
      // When slides are closed, allow stretching up to 85% of screen width (like Antigravity / Cursor)!
      const maxW = isSidebarOpen ? window.innerWidth * 0.75 : window.innerWidth * 0.88;
      const minW = 320;
      const newWidth = window.innerWidth - moveEvent.clientX;
      if (newWidth >= minW && newWidth <= maxW) {
        setChatWidth(newWidth);
      }
    };

    const onMouseUp = () => {
      isDraggingRef.current = false;
      setIsDraggingChat(false);
      window.removeEventListener("mousemove", onMouseMove);
      window.removeEventListener("mouseup", onMouseUp);
    };

    window.addEventListener("mousemove", onMouseMove);
    window.addEventListener("mouseup", onMouseUp);
  };

  const isChatExpanded = chatWidth > 540;
  const toggleExpandChat = () => {
    if (isChatExpanded) {
      setChatWidth(380);
    } else {
      const targetW = isSidebarOpen
        ? Math.min(620, Math.max(480, window.innerWidth - 360))
        : Math.min(840, Math.max(540, window.innerWidth - 120));
      setChatWidth(targetW);
    }
  };

  // State for slide generation/saving indicator
  const [isSaving, setIsSaving] = useState(false);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [isAddingSlide, setIsAddingSlide] = useState(false);
  const [deletingSlideNum, setDeletingSlideNum] = useState<number | null>(null);

  // Speaker notes
  const [showNotes, setShowNotes] = useState(false);
  const [notesMap, setNotesMap] = useState<Record<number, string>>({});

  // Auto-load presentation slides from S3 bucket on mount or project switch
  const loadSlidesFromS3 = async (selectSlideIndex?: number) => {
    if (!userId || !projectId) return;
    setLoading(true);
    setLoadError(null);
    setRefreshing(true);
    try {
      // 1. Primary endpoint: workspace/render_ppt.py -> /api/workspace/render/slides
      const res = await fetch(
        `${API_BASE_URL}/api/workspace/render/slides?user_id=${userId}&project_id=${projectId}`
      );
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || `Failed to fetch presentation slides (status ${res.status})`);
      }
      const data = await res.json();
      const loadedSlides: SlideData[] = data.slides || [];
      setSlides(loadedSlides);
      if (typeof selectSlideIndex === "number" && selectSlideIndex >= 0 && selectSlideIndex < loadedSlides.length) {
        setActiveSlideIndex(selectSlideIndex);
      } else if (loadedSlides.length > 0 && activeSlideIndex >= loadedSlides.length) {
        setActiveSlideIndex(0);
      }
    } catch (err: any) {
      setLoadError(err.message || "An error occurred while loading presentation slides.");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  // Add new pure blank white slide in Supabase S3 (optionally after a specific slide number)
  const handleAddNewSlide = async (afterSlideNumber?: number) => {
    if (!userId || !projectId || isAddingSlide) return;
    setIsAddingSlide(true);
    try {
      const res = await fetch(`${API_BASE_URL}/api/workspace/editor/new_slide`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          user_id: userId,
          project_id: projectId,
          after_slide: typeof afterSlideNumber === "number" ? afterSlideNumber : undefined,
        }),
      });

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || "Failed to create new blank slide.");
      }

      const data = await res.json();
      const newSlideNum = data.slide_number;

      // Re-fetch slides list from S3 and select the new blank slide
      const fetchRes = await fetch(
        `${API_BASE_URL}/api/workspace/render/slides?user_id=${userId}&project_id=${projectId}`
      );
      if (fetchRes.ok) {
        const freshData = await fetchRes.json();
        const loaded: SlideData[] = freshData.slides || [];
        setSlides(loaded);
        const newIdx = loaded.findIndex((s) => s.slide_number === newSlideNum);
        if (newIdx !== -1) {
          setActiveSlideIndex(newIdx);
        } else if (loaded.length > 0) {
          setActiveSlideIndex(loaded.length - 1);
        }
      }
    } catch (err: any) {
      console.error("Error creating new blank slide:", err);
      alert(err.message || "Failed to create new slide.");
    } finally {
      setIsAddingSlide(false);
    }
  };

  // Delete slide from Supabase S3 via /api/workspace/editor/delete_slide
  const handleDeleteSlide = async (slideNumber: number) => {
    if (!userId || !projectId || deletingSlideNum !== null) return;
    if (slides.length <= 1) {
      alert("Cannot delete the only remaining slide in the presentation.");
      return;
    }

    setDeletingSlideNum(slideNumber);
    try {
      const res = await fetch(`${API_BASE_URL}/api/workspace/editor/delete_slide`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          user_id: userId,
          project_id: projectId,
          slide_number: slideNumber,
        }),
      });

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || "Failed to delete slide.");
      }

      // Re-fetch updated slides list from S3
      const fetchRes = await fetch(
        `${API_BASE_URL}/api/workspace/render/slides?user_id=${userId}&project_id=${projectId}`
      );
      if (fetchRes.ok) {
        const freshData = await fetchRes.json();
        const loaded: SlideData[] = freshData.slides || [];
        setSlides(loaded);

        // Safely adjust activeSlideIndex so it never points out of bounds
        setActiveSlideIndex((prevIdx) => {
          if (prevIdx >= loaded.length) {
            return Math.max(0, loaded.length - 1);
          }
          return prevIdx;
        });
      }
    } catch (err: any) {
      console.error("Error deleting slide:", err);
      alert(err.message || "Failed to delete slide.");
    } finally {
      setDeletingSlideNum(null);
    }
  };

  useEffect(() => {
    loadSlidesFromS3();
  }, [userId, projectId]);

  const currentSlide = slides[activeSlideIndex];

  // Dynamically initialize Chart.js and execute scripts in the active slide canvas
  useEffect(() => {
    // Helper SafeChart class that automatically destroys existing chart instances before re-creating
    class SafeChart extends Chart {
      constructor(target: any, config: any) {
        try {
          const canvasEl = target && target.canvas ? target.canvas : target;
          const existing =
            Chart.getChart(canvasEl) ||
            (typeof target === "string" ? Chart.getChart(target) : null) ||
            (canvasEl && canvasEl.id ? Chart.getChart(canvasEl.id) : null);
          if (existing) {
            existing.destroy();
          }
        } catch (e) {
          // ignore
        }
        super(target, config);
      }
    }

    const timer = setTimeout(() => {
      const container = slideCanvasRef.current;
      if (!container) return;

      // 1. Destroy any existing Chart instances on canvases inside the main slide canvas
      const canvases = container.querySelectorAll<HTMLCanvasElement>("canvas");
      canvases.forEach((canvas) => {
        try {
          const existing = Chart.getChart(canvas) || (canvas.id ? Chart.getChart(canvas.id) : null);
          if (existing) existing.destroy();
        } catch (err) {
          // ignore
        }
      });

      // 2. Support data-chart-config attribute if present
      canvases.forEach((canvas) => {
        const configAttr = canvas.getAttribute("data-chart-config");
        if (configAttr) {
          try {
            const config = JSON.parse(configAttr);
            new SafeChart(canvas, config);
          } catch (err) {
            console.error("Chart.js render error from data-chart-config:", err);
          }
        }
      });

      // 3. Find and execute all inline <script> tags generated by LLM (e.g. new Chart(...))
      const scripts = container.querySelectorAll<HTMLScriptElement>("script");
      scripts.forEach((script) => {
        // Skip external scripts (like chart.js CDN) because Chart is already registered and in scope
        if (script.src) {
          if (!script.src.includes("chart.js") && !script.src.includes("cdn.jsdelivr.net")) {
            const newScript = document.createElement("script");
            Array.from(script.attributes).forEach((attr) => newScript.setAttribute(attr.name, attr.value));
            document.head.appendChild(newScript);
          }
          return;
        }

        const scriptContent = script.textContent || "";
        if (!scriptContent.trim()) return;

        try {
          const trimmed = scriptContent.trim();
          // Skip if script appears truncated or has unbalanced curly braces
          const openBraces = (trimmed.match(/\{/g) || []).length;
          const closeBraces = (trimmed.match(/\}/g) || []).length;
          if (openBraces !== closeBraces) {
            console.warn("Skipping slide inline script due to unbalanced braces / truncated code.");
            return;
          }

          // Build a safe execution context where getElementById resolves inside the container
          // and SafeChart automatically destroys any existing charts before instantiation
          const runner = new Function("Chart", "container", `
            const getCanvas = (id) => container.querySelector('#' + id) || container.querySelector('canvas') || window.document.getElementById(id);
            const document = {
              ...window.document,
              getElementById: (id) => container.querySelector('#' + id) || window.document.getElementById(id),
              querySelector: (sel) => container.querySelector(sel) || window.document.querySelector(sel),
              querySelectorAll: (sel) => container.querySelectorAll(sel)
            };
            try {
              ${scriptContent}
            } catch (innerErr) {
              console.warn("Slide inline script execution notice:", innerErr);
            }
          `);
          runner(SafeChart, container);
        } catch (evalErr) {
          console.warn("Could not compile slide script:", evalErr);
        }
      });
    }, 60);

    return () => {
      clearTimeout(timer);
      const container = slideCanvasRef.current;
      if (container) {
        const canvases = container.querySelectorAll<HTMLCanvasElement>("canvas");
        canvases.forEach((canvas) => {
          try {
            const existing = Chart.getChart(canvas) || (canvas.id ? Chart.getChart(canvas.id) : null);
            if (existing) existing.destroy();
          } catch (err) {
            // ignore
          }
        });
      }
    };
  }, [activeSlideIndex, currentSlide?.rendered_html, slides]);

  const handleDownloadPptx = () => {
    window.open(
      `${API_BASE_URL}/api/workspace/editor/download?user_id=${userId}&project_id=${projectId}`,
      "_blank"
    );
  };

  return (
    <div className="h-screen w-screen flex flex-col bg-[#f0f2f5] text-slate-900 font-sans overflow-hidden select-none">
      {/* ========================================================================= */}
      {/* TOP COMPACT APPLICATION BAR */}
      {/* ========================================================================= */}
      <header className="h-14 bg-white border-b border-slate-200 px-4 flex items-center justify-between z-30 shrink-0">
        {/* Left: Brand & Breadcrumbs */}
        <div className="flex items-center gap-3">
          <Link href="/dashboard" className="flex items-center gap-2">
 
            <span className="font-extrabold text-base tracking-tight text-slate-900 hidden sm:inline">
              <span className="text-[#FF5148]">KeloStats</span>
            </span>
          </Link>
          <span className="text-slate-300">/</span>

          <button
            type="button"
            onClick={() => setIsSidebarOpen((prev) => !prev)}
            title={isSidebarOpen ? "Hide slides sidebar" : "Show slides sidebar"}
            className={`px-2.5 py-1 rounded-lg border text-xs font-medium transition-all flex items-center gap-1.5 cursor-pointer ${
              isSidebarOpen
                ? "bg-slate-100 text-slate-700 border-slate-200"
                : "bg-white text-slate-600 border-slate-200 hover:bg-slate-50 hover:text-slate-900 shadow-2xs"
            }`}
          >
            <svg className="w-3.5 h-3.5 text-slate-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h7" />
            </svg>
            <span className="hidden sm:inline font-semibold text-xs">Slides</span>
          </button>

          <span className="text-slate-300 hidden sm:inline">/</span>
          <div className="flex items-center gap-2">
            <span className="font-bold text-sm text-slate-800 truncate max-w-xs">{projectName}</span>
            <span className="text-[10px] font-semibold text-emerald-700 bg-emerald-50 border border-emerald-200 px-2 py-0.5 rounded-full hidden md:inline">
              16:9 Widescreen
            </span>
          </div>
        </div>

        {/* Center: Slide Count & Refresh Status */}
        <div className="hidden md:flex items-center gap-3">
          {slides.length > 0 && (
            <span className="text-xs font-semibold text-slate-500 bg-slate-100 px-3 py-1 rounded-lg">
              Slide {activeSlideIndex + 1} of {slides.length}
            </span>
          )}
          {refreshing && (
            <span className="flex items-center gap-1.5 text-xs font-medium text-orange-600 bg-orange-50 border border-orange-200 px-2.5 py-0.5 rounded-lg animate-pulse">
              <svg className="animate-spin w-3.5 h-3.5" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z" />
              </svg>
              <span>Loading slide JSONs from Supabase S3...</span>
            </span>
          )}
        </div>

        {/* Right: Actions */}
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => setIsChatOpen((prev) => !prev)}
            title={isChatOpen ? "Hide Copilot chat" : "Show Copilot chat"}
            className={`px-3 py-1.5 rounded-lg border text-xs font-semibold transition-all flex items-center gap-1.5 cursor-pointer ${
              isChatOpen
                ? "bg-orange-50 text-[#FF5148] border-orange-200 shadow-2xs"
                : "bg-slate-100 text-slate-700 border-slate-200 hover:bg-slate-200"
            }`}
          >
            <svg className="w-3.5 h-3.5 text-[#FF5148]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
            </svg>
            <span className="hidden sm:inline">Copilot</span>
          </button>

          <button
            type="button"
            onClick={() => { loadSlidesFromS3(); }}
            disabled={refreshing}
            className="px-3 py-1.5 rounded-lg text-xs font-semibold text-slate-700 bg-slate-100 hover:bg-slate-200 transition-colors flex items-center gap-1.5 cursor-pointer disabled:opacity-50"
            title="Reload slide JSONs from S3"
          >
            <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
            </svg>
            <span className="hidden sm:inline">Reload JSON</span>
          </button>

          <button
            type="button"
            onClick={handleDownloadPptx}
            className="px-3.5 py-1.5 rounded-lg text-xs font-bold text-white bg-[#FF5148] hover:bg-[#e64037] shadow-sm transition-all flex items-center gap-1.5 cursor-pointer"
          >
            <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
            </svg>
            <span>Download .pptx</span>
          </button>
        </div>
      </header>

      {/* ========================================================================= */}
      {/* MAIN BODY: (LEFT: PPT CANVA EDITOR) + (RIGHT: COPILOT CHATBOT) */}
      {/* ========================================================================= */}
      <div className="flex-1 flex overflow-hidden">
        {/* ======================================================================= */}
        {/* LEFT COLUMN: PPT EDITOR (THUMBNAILS + 16:9 CANVAS) */}
        {/* ======================================================================= */}
        <div className="flex-1 flex overflow-hidden">
          {/* Thumbnail Strip (Left Sidebar) */}
          <div
            className={`${
              isSidebarOpen ? "w-60 border-r" : "w-0 border-r-0"
            } shrink-0 bg-white border-slate-200 flex flex-col transition-all duration-300 ease-in-out overflow-hidden`}
          >
            {/* Sidebar Header: Slides Title + Count + Collapse Button */}
            <div className="h-11 border-b border-slate-200 flex items-center justify-between px-3.5 shrink-0 bg-white min-w-[240px]">
              <div className="flex items-center gap-2">
                <div className="w-6 h-6 rounded-md bg-orange-50 text-[#FF5148] flex items-center justify-center shadow-2xs">
                  <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6a2 2 0 012-2h12a2 2 0 012 2v12a2 2 0 01-2 2H6a2 2 0 01-2-2V6z" />
                  </svg>
                </div>
                <span className="text-xs font-bold text-slate-800 tracking-tight">Slides</span>
                {slides.length > 0 && (
                  <span className="text-[10px] font-semibold text-slate-500 bg-slate-100 px-2 py-0.5 rounded-full">
                    {slides.length}
                  </span>
                )}
              </div>

              {/* Close / Collapse Slide Bar Button */}
              <button
                type="button"
                onClick={() => setIsSidebarOpen(false)}
                title="Close slides sidebar"
                className="p-1.5 rounded-lg text-slate-400 hover:text-slate-700 hover:bg-slate-100 transition-colors cursor-pointer"
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 19l-7-7 7-7m8 14l-7-7 7-7" />
                </svg>
              </button>
            </div>

            {/* Thumbnails Scrollable List */}
            <div className="flex-1 overflow-y-auto p-3 space-y-3 min-w-[240px]">
              {loading ? (
                <div className="py-12 text-center text-xs text-slate-400">
                  Loading slides...
                </div>
              ) : slides.length === 0 ? (
                <div className="py-12 text-center text-xs text-slate-400 px-2">
                  No slides found in workspace.
                </div>
              ) : (
                slides.map((slide, idx) => {
                  const isActive = activeSlideIndex === idx;
                  return (
                    <div
                      key={slide.s3_key ? `${slide.s3_key}-${idx}` : `slide-${slide.slide_number}-${idx}`}
                      className="relative flex items-start gap-2 group"
                    >
                      {/* Slide Number */}
                      <span className="text-[11px] font-bold text-slate-400 w-3 pt-1 text-right shrink-0 group-hover:text-slate-600 transition-colors">
                        {idx + 1}
                      </span>

                      {/* Thumbnail Preview Card Wrapper */}
                      <div className="relative flex-1">
                        <div
                          onClick={() => setActiveSlideIndex(idx)}
                          className={`w-full aspect-[16/9] rounded-md cursor-pointer transition-all border overflow-hidden shadow-xs relative bg-white ${
                            isActive
                              ? "border-2 border-[#FF5148] ring-2 ring-[#FF5148]/20 shadow-sm"
                              : "border-slate-200 hover:border-slate-400 hover:bg-slate-50"
                          }`}
                        >
                          <div className="absolute inset-0 z-10 cursor-pointer" />
                          <div
                            className="w-full h-full pointer-events-none"
                            dangerouslySetInnerHTML={{ __html: slide.rendered_html }}
                          />
                        </div>

                        {/* Action Buttons: Add Slide After (+) & Delete Slide, placed side-by-side at bottom */}
                        <div
                          className={`absolute -bottom-2.5 -right-1.5 items-center gap-1.5 z-20 ${
                            isActive ? "flex" : "hidden group-hover:flex"
                          }`}
                        >
                          {/* Insert Slide After Button (+) */}
                          <button
                            type="button"
                            onClick={(e) => {
                              e.stopPropagation();
                              handleAddNewSlide(slide.slide_number);
                            }}
                            disabled={isAddingSlide}
                            title={`Insert new slide after Slide ${slide.slide_number}`}
                            className="w-7 h-7 rounded-full bg-slate-800 hover:bg-[#FF5148] text-white shadow-md flex items-center justify-center transition-all hover:scale-110 active:scale-95 cursor-pointer border-2 border-white disabled:opacity-50"
                          >
                            <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M12 4v16m8-8H4" />
                            </svg>
                          </button>

                          {/* Delete Slide Dustbin Icon Button */}
                          {slides.length > 1 && (
                            <button
                              type="button"
                              onClick={(e) => {
                                e.stopPropagation();
                                handleDeleteSlide(slide.slide_number);
                              }}
                              disabled={deletingSlideNum === slide.slide_number}
                              title="Delete slide"
                              className="w-7 h-7 rounded-full bg-[#E06D3E] hover:bg-red-600 text-white shadow-md flex items-center justify-center transition-all hover:scale-110 active:scale-95 cursor-pointer border-2 border-white disabled:opacity-50"
                            >
                              {deletingSlideNum === slide.slide_number ? (
                                <svg className="animate-spin w-3.5 h-3.5 text-white" fill="none" viewBox="0 0 24 24">
                                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z" />
                                </svg>
                              ) : (
                                <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                  <path
                                    strokeLinecap="round"
                                    strokeLinejoin="round"
                                    strokeWidth={2}
                                    d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"
                                  />
                                </svg>
                              )}
                            </button>
                          )}
                        </div>
                      </div>
                    </div>
                  );
                })
              )}

              {/* Quick Add Slide Button at bottom of thumbnail strip */}
              {!loading && slides.length > 0 && (
                <div className="pt-2 flex justify-center">
                  <button
                    type="button"
                    onClick={() => handleAddNewSlide()}
                    disabled={isAddingSlide}
                    className="w-full py-2.5 px-3 border border-dashed border-slate-300 hover:border-[#FF5148] hover:text-[#FF5148] hover:bg-orange-50/60 rounded-xl text-xs font-semibold text-slate-600 flex items-center justify-center gap-2 transition-all cursor-pointer shadow-2xs hover:shadow-xs disabled:opacity-50"
                  >
                    {isAddingSlide ? (
                      <svg className="animate-spin w-3.5 h-3.5 text-[#FF5148]" fill="none" viewBox="0 0 24 24">
                        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z" />
                      </svg>
                    ) : (
                      <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
                      </svg>
                    )}
                    <span>Add Blank Slide</span>
                  </button>
                </div>
              )}
            </div>
          </div>

          {/* ===================================================================== */}
          {/* CENTER CANVAS AREA (16:9 Presentation Canvas) */}
          {/* ===================================================================== */}
          <div className="flex-1 flex flex-col bg-[#e9ecef] overflow-y-auto relative">
            {/* Floating Open Slides Button (when sidebar is closed) */}
            {!isSidebarOpen && (
              <button
                type="button"
                onClick={() => setIsSidebarOpen(true)}
                title="Open slides sidebar"
                className="absolute top-4 left-4 z-20 flex items-center gap-2 px-3 py-2 bg-white/95 backdrop-blur-sm border border-slate-200/90 shadow-md hover:shadow-lg rounded-xl text-xs font-semibold text-slate-700 hover:text-[#FF5148] transition-all hover:scale-105 active:scale-95 cursor-pointer"
              >
                <div className="w-5 h-5 rounded-md bg-orange-50 text-[#FF5148] flex items-center justify-center">
                  <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6a2 2 0 012-2h12a2 2 0 012 2v12a2 2 0 01-2 2H6a2 2 0 01-2-2V6z" />
                  </svg>
                </div>
                <span>Show Slides</span>
                {slides.length > 0 && (
                  <span className="text-[10px] bg-slate-100 text-slate-600 px-1.5 py-0.5 rounded-full font-bold">
                    {slides.length}
                  </span>
                )}
                <svg className="w-3.5 h-3.5 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                </svg>
              </button>
            )}

            {/* Floating Open Copilot Button (when chat is closed) */}
            {!isChatOpen && (
              <button
                type="button"
                onClick={() => setIsChatOpen(true)}
                title="Open Copilot chat"
                className="absolute top-4 right-4 z-20 flex items-center gap-2 px-3 py-2 bg-white/95 backdrop-blur-sm border border-slate-200/90 shadow-md hover:shadow-lg rounded-xl text-xs font-semibold text-slate-700 hover:text-[#FF5148] transition-all hover:scale-105 active:scale-95 cursor-pointer"
              >
                <div className="w-5 h-5 rounded-md bg-gradient-to-tr from-[#FF5148] to-orange-400 text-white flex items-center justify-center shadow-2xs">
                  <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
                  </svg>
                </div>
                <span>Copilot</span>
                <svg className="w-3.5 h-3.5 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
                </svg>
              </button>
            )}
            {/* Canvas Viewport Container */}
            <div className="flex-1 flex items-center justify-center p-6 sm:p-10">
              {loading ? (
                <div className="flex flex-col items-center justify-center p-12 bg-white rounded-2xl shadow-sm border border-slate-200">
                  <svg className="animate-spin w-8 h-8 text-[#FF5148] mb-4" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z" />
                  </svg>
                  <p className="text-sm font-semibold text-slate-700">Loading slide JSONs...</p>
                  <p className="text-xs text-slate-400 mt-1">Rendering dynamic presentation from Supabase S3</p>
                </div>
              ) : loadError ? (
                <div className="p-8 max-w-md bg-white rounded-2xl shadow-sm border border-red-200 text-center">
                  <p className="text-sm font-bold text-red-600 mb-2">Failed to load presentation</p>
                  <p className="text-xs text-slate-500 mb-4">{loadError}</p>
                  <button
                    onClick={() => { loadSlidesFromS3(); }}
                    className="px-4 py-2 bg-[#FF5148] text-white text-xs font-semibold rounded-lg cursor-pointer"
                  >
                    Retry
                  </button>
                </div>
              ) : currentSlide ? (
                /* 16:9 Presentation Canvas rendered directly from slide JSON styles and elements */
                <div
                  ref={slideCanvasRef}
                  className="w-full max-w-4xl aspect-[16/9] rounded-xs shadow-2xl border border-slate-200 relative bg-white overflow-hidden transition-all"
                  dangerouslySetInnerHTML={{ __html: currentSlide.rendered_html }}
                />
              ) : (
                <div className="text-sm text-slate-400">No active slide found.</div>
              )}
            </div>

            {/* Bottom Bar: Click to add notes */}
            <div className="border-t border-slate-200 bg-white shrink-0">
              <button
                type="button"
                onClick={() => setShowNotes(!showNotes)}
                className="w-full px-6 py-2 text-left text-xs font-medium text-slate-500 hover:text-slate-800 flex items-center justify-between cursor-pointer"
              >
                <div className="flex items-center gap-2">
                  <svg className="w-3.5 h-3.5 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
                  </svg>
                  <span>Click to add notes</span>
                </div>
                <span className="text-[10px] text-slate-400">{showNotes ? "▲ Hide" : "▼ Show"}</span>
              </button>

              {showNotes && (
                <div className="px-6 pb-4 pt-1 bg-white">
                  <textarea
                    rows={2}
                    value={notesMap[activeSlideIndex] || ""}
                    onChange={(e) =>
                      setNotesMap({ ...notesMap, [activeSlideIndex]: e.target.value })
                    }
                    placeholder="Enter presenter notes for this slide..."
                    className="w-full p-2.5 text-xs text-slate-800 border border-slate-200 rounded-lg focus:outline-none focus:ring-1 focus:ring-[#FF5148]"
                  />
                </div>
              )}
            </div>
          </div>
        </div>

        {/* ======================================================================= */}
        {/* RIGHT COLUMN: COPILOT CHATBOT (RESIZABLE & COLLAPSIBLE) */}
        {/* ======================================================================= */}
        <div
          style={{ width: isChatOpen ? `${chatWidth}px` : "0px" }}
          className={`shrink-0 h-full bg-white relative flex flex-col ${
            isDraggingChat ? "select-none transition-none" : "transition-[width] duration-300 ease-in-out"
          } ${isChatOpen ? "border-l border-slate-200" : "border-l-0 overflow-hidden"}`}
        >
          {/* Draggable Resize Divider on left border */}
          {isChatOpen && (
            <div
              onMouseDown={handleMouseDownResize}
              className="absolute -left-1.5 top-0 bottom-0 w-3 cursor-col-resize z-30 group flex items-center justify-center"
              title="Drag to resize chat panel"
            >
              <div
                className={`w-1 h-full transition-colors ${
                  isDraggingChat ? "bg-[#FF5148]" : "bg-transparent group-hover:bg-[#FF5148]/60"
                }`}
              />
            </div>
          )}

          {isChatOpen && (
            <div className="h-full w-full overflow-hidden flex flex-col min-w-[300px]">
              <ChatInterface
                projectId={projectId}
                userId={userId}
                databaseId={databaseId}
                slideNumber={currentSlide?.slide_number ?? (activeSlideIndex + 1)}
                totalSlides={slides.length}
                onSelectSlide={(slideNum) => {
                  const idx = slides.findIndex((s) => s.slide_number === slideNum);
                  if (idx !== -1) setActiveSlideIndex(idx);
                }}
                onSlideRefreshRequired={() => {
                  loadSlidesFromS3(activeSlideIndex);
                }}
                onClose={() => setIsChatOpen(false)}
                isExpanded={isChatExpanded}
                onToggleExpand={toggleExpandChat}
              />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default function WorkspacePage() {
  return (
    <Suspense
      fallback={
        <div className="h-screen w-screen flex items-center justify-center bg-white text-slate-400 text-sm">
          Loading workspace editor...
        </div>
      }
    >
      <WorkspaceContent />
    </Suspense>
  );
}
