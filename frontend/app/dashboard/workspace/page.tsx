"use client";

import React, { useState, useEffect, useRef, Suspense } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { API_BASE_URL } from "@/lib/config";
import { fetchWithAuth } from "@/lib/api";
import ChatInterface from "./ChatInterface";
import DesigningTools, { ActiveFormatInfo } from "./DesigningTools";




interface SlideData {
  slide_number: number;
  filename?: string;
  name: string;
  s3_key?: string;
  json?: any;
  rendered_html: string;
  raw_html?: string;
}

/**
 * High-fidelity scaled miniview for slide thumbnails in sidebar.
 * Renders the real HTML and Chart.js graphics inside an isolated scaled iframe,
 * ensuring charts, typography, and layouts are 100% proportionate and visible.
 */
function SlideThumbnail({ html, title }: { html: string; title?: string }) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [scale, setScale] = useState(0.2);

  useEffect(() => {
    if (!containerRef.current) return;
    const updateScale = () => {
      if (containerRef.current) {
        const w = containerRef.current.clientWidth;
        if (w > 0) {
          // Standard 16:9 base design canvas: 960 x 540
          setScale(w / 960);
        }
      }
    };
    updateScale();
    const ro = new ResizeObserver(updateScale);
    ro.observe(containerRef.current);
    return () => ro.disconnect();
  }, []);

  const slideCode = html || "";
  const lucideInject = `<script src="https://cdn.jsdelivr.net/npm/chart.js"></script><script src="https://unpkg.com/lucide@latest"></script><link rel="stylesheet" href="https://unpkg.com/lucide-static@1.45.0/font/lucide.css">`;
  const cleanDoc = slideCode.includes("<head>")
    ? slideCode.replace(
        "<head>",
        `<head>${lucideInject}<style>html,body{margin:0!important;padding:0!important;overflow:hidden!important;width:100%!important;height:100%!important;} .slide-canvas{width:100%!important;height:100%!important;max-width:100%!important;}</style>`
      )
    : `<!DOCTYPE html><html><head>${lucideInject}<style>html,body{margin:0!important;padding:0!important;overflow:hidden!important;width:100%!important;height:100%!important;} .slide-canvas{width:100%!important;height:100%!important;max-width:100%!important;}</style></head><body>${slideCode}</body></html>`;

  return (
    <div ref={containerRef} className="w-full h-full relative overflow-hidden bg-white pointer-events-none select-none">
      <iframe
        srcDoc={cleanDoc}
        tabIndex={-1}
        scrolling="no"
        sandbox="allow-scripts allow-same-origin"
        loading="lazy"
        title={title || "Slide miniview"}
        className="border-0 block absolute top-0 left-0 pointer-events-none"
        style={{
          width: "960px",
          height: "540px",
          transform: `scale(${scale})`,
          transformOrigin: "top left",
        }}
      />
    </div>
  );
}

function WorkspaceContent() {
  const searchParams = useSearchParams();

  const userId = searchParams.get("user_id") || searchParams.get("userid_id") || "00000000-0000-0000-0000-000000000000";
  const projectId = searchParams.get("project_id") || "project_default";
  const projectName = searchParams.get("project_name") || "Presentation Project";
  const databaseId = searchParams.get("database_id") || searchParams.get("db_id") || "";
  const databaseDisplayName = searchParams.get("display_name") || searchParams.get("database_display_name") || searchParams.get("db_name") || "";
  const collectionId = searchParams.get("collection_id") || "";
  const collectionDisplayName = searchParams.get("collection_display_name") || searchParams.get("col_name") || "";
  const rawSource = searchParams.get("source");
  const source: "database" | "documents" | "auto" =
    rawSource === "database" || rawSource === "documents" || rawSource === "auto"
      ? rawSource
      : (databaseId && collectionId)
      ? "auto"
      : databaseId
      ? "database"
      : collectionId
      ? "documents"
      : "auto";

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
  const [isSlideRefreshing, setIsSlideRefreshing] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [isAddingSlide, setIsAddingSlide] = useState(false);
  const [deletingSlideNum, setDeletingSlideNum] = useState<number | null>(null);

  // Speaker notes
  const [showNotes, setShowNotes] = useState(false);
  const [notesMap, setNotesMap] = useState<Record<number, string>>({});

  // Auto-load presentation slides from S3 bucket on mount or project switch
  const loadSlidesFromS3 = async (selectSlideIndex?: number, targetSlideNumber?: number) => {
    if (!userId || !projectId) return;

    // Only set full loading if we don't have slides yet
    // When slides exist, preserve them on the slide bar and smoothly blur the PPT canvas
    if (slides.length === 0) {
      setLoading(true);
    } else {
      setIsSlideRefreshing(true);
    }
    setLoadError(null);
    setRefreshing(true);
    try {
      // 1. Primary endpoint: workspace/render_ppt.py -> /api/workspace/render/slides
      const res = await fetchWithAuth(
        `${API_BASE_URL}/api/workspace/render/slides?user_id=${userId}&project_id=${projectId}`
      );
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || `Failed to fetch presentation slides (status ${res.status})`);
      }
      const data = await res.json();
      const loadedSlides: SlideData[] = data.slides || [];
      setSlides(loadedSlides);

      // Determine active slide index
      if (typeof targetSlideNumber === "number" && targetSlideNumber > 0) {
        const foundIdx = loadedSlides.findIndex((s) => s.slide_number === targetSlideNumber);
        if (foundIdx !== -1) {
          setActiveSlideIndex(foundIdx);
        } else if (typeof selectSlideIndex === "number" && selectSlideIndex >= 0 && selectSlideIndex < loadedSlides.length) {
          setActiveSlideIndex(selectSlideIndex);
        }
      } else if (typeof selectSlideIndex === "number" && selectSlideIndex >= 0 && selectSlideIndex < loadedSlides.length) {
        setActiveSlideIndex(selectSlideIndex);
      } else if (loadedSlides.length > 0 && activeSlideIndex >= loadedSlides.length) {
        setActiveSlideIndex(0);
      }
    } catch (err: any) {
      setLoadError(err.message || "An error occurred while loading presentation slides.");
    } finally {
      setLoading(false);
      setRefreshing(false);
      // Reveal the PPT widget smoothly from blur to crisp presentation
      setTimeout(() => {
        setIsSlideRefreshing(false);
      }, 500);
    }
  };

  // Add new pure blank white slide in Supabase S3 (optionally after a specific slide number)
  const handleAddNewSlide = async (afterSlideNumber?: number) => {
    if (!userId || !projectId || isAddingSlide) return;
    setIsAddingSlide(true);
    try {
      const res = await fetchWithAuth(`${API_BASE_URL}/api/workspace/editor/new_slide`, {
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
      const fetchRes = await fetchWithAuth(
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
      const res = await fetchWithAuth(`${API_BASE_URL}/api/workspace/editor/delete_slide`, {
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
      const fetchRes = await fetchWithAuth(
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

  // Designing Tools state
  const [isEditingSlide, setIsEditingSlide] = useState(false);
  const [isSavingTools, setIsSavingTools] = useState(false);
  const [saveSuccessMsg, setSaveSuccessMsg] = useState<string | null>(null);
  const [activeFormat, setActiveFormat] = useState<ActiveFormatInfo | undefined>(undefined);
  const iframeRef = useRef<HTMLIFrameElement | null>(null);

  const triggerFormatDetection = () => {
    const iframe = iframeRef.current;
    if (!iframe || !iframe.contentDocument) return;
    const doc = iframe.contentDocument;
    const sel = doc.getSelection();
    if (!sel || !sel.anchorNode) return;

    const elem =
      sel.anchorNode.nodeType === Node.ELEMENT_NODE
        ? (sel.anchorNode as HTMLElement)
        : sel.anchorNode.parentElement;
    if (!elem) return;

    const computed = doc.defaultView?.getComputedStyle(elem);
    if (!computed) return;

    const rawFamily = computed.fontFamily || "Arial";
    const cleanFamily = rawFamily.split(",")[0].replace(/['"]/g, "").trim();

    const pxSize = Math.round(parseFloat(computed.fontSize) || 16);

    const isBold =
      computed.fontWeight === "bold" ||
      parseInt(computed.fontWeight) >= 600 ||
      computed.fontWeight === "700" ||
      computed.fontWeight === "800" ||
      computed.fontWeight === "900";

    const isItalic = computed.fontStyle === "italic";
    const isUnderline = (computed.textDecorationLine || computed.textDecoration || "").includes("underline");
    const isStrike = (computed.textDecorationLine || computed.textDecoration || "").includes("line-through");

    const rgbToHex = (rgb: string) => {
      const match = rgb.match(/\d+/g);
      if (!match || match.length < 3) return "#000000";
      return "#" + match.slice(0, 3).map((x) => parseInt(x).toString(16).padStart(2, "0")).join("");
    };

    const textColor = computed.color ? rgbToHex(computed.color) : "#000000";
    const bgColor =
      computed.backgroundColor &&
      computed.backgroundColor !== "rgba(0, 0, 0, 0)" &&
      computed.backgroundColor !== "transparent"
        ? rgbToHex(computed.backgroundColor)
        : "#FFFF00";

    setActiveFormat({
      fontFamily: cleanFamily,
      fontSize: `${pxSize}`,
      bold: isBold,
      italic: isItalic,
      underline: isUnderline,
      strikethrough: isStrike,
      superscript: false,
      align: computed.textAlign || "left",
      textColor,
      highlightColor: bgColor,
    });
  };

  const handleIframeKeyDown = (e: KeyboardEvent) => {
    const iframe = iframeRef.current;
    if (!iframe || !iframe.contentDocument) return;
    const doc = iframe.contentDocument;

    if (e.key === "Enter") {
      const sel = doc.getSelection();
      if (!sel || !sel.anchorNode) return;

      const parent =
        sel.anchorNode.nodeType === Node.ELEMENT_NODE
          ? (sel.anchorNode as HTMLElement)
          : sel.anchorNode.parentElement;

      if (parent) {
        parent.style.height = "auto";
        parent.style.maxHeight = "none";
        parent.style.overflow = "visible";
        parent.style.whiteSpace = "normal";
      }

      if (e.shiftKey) {
        e.preventDefault();
        doc.execCommand("insertLineBreak");
      }
    }
  };

  const setupEditableDocument = (doc: Document) => {
    try {
      doc.designMode = "on";
      if (doc.body) {
        doc.body.contentEditable = "true";
      }

      try {
        doc.execCommand("defaultParagraphSeparator", false, "p");
      } catch (e) {}

      const protectNonText = () => {
        const nonText = doc.querySelectorAll("svg, canvas, img, .lucide, [data-lucide], i");
        nonText.forEach((el) => {
          el.setAttribute("contenteditable", "false");
          el.setAttribute("data-protected", "true");
        });
      };
      protectNonText();

      try {
        const win = iframeRef.current?.contentWindow as any;
        if (win && win.lucide && typeof win.lucide.createIcons === "function") {
          win.lucide.createIcons();
          protectNonText();
        }
      } catch (err) {}

      let style = doc.getElementById("kelostats-edit-styles");
      if (!style) {
        style = doc.createElement("style");
        style.id = "kelostats-edit-styles";
        style.textContent = `
          [contenteditable="true"] {
            cursor: text !important;
            min-height: 1em !important;
          }
          [contenteditable="true"]:hover {
            outline: 1px dashed rgba(255, 81, 72, 0.45) !important;
            outline-offset: 2px !important;
          }
          [contenteditable="true"]:focus {
            outline: 2px solid #FF5148 !important;
            outline-offset: 3px !important;
          }
          .slide-title, .slide-subtitle, h1, h2, h3, h4, h5, h6, p, li, .metric-card {
            height: auto !important;
            max-height: none !important;
            overflow: visible !important;
            white-space: normal !important;
          }
          svg, canvas, img, .lucide, [data-lucide] {
            user-select: none !important;
            -webkit-user-select: none !important;
            pointer-events: auto !important;
            display: inline-block !important;
            vertical-align: middle !important;
          }
        `;
        doc.head.appendChild(style);
      }

      doc.removeEventListener("keydown", handleIframeKeyDown);
      doc.addEventListener("keydown", handleIframeKeyDown);

      doc.removeEventListener("selectionchange", triggerFormatDetection);
      doc.addEventListener("selectionchange", triggerFormatDetection);

      doc.removeEventListener("keyup", triggerFormatDetection);
      doc.addEventListener("keyup", triggerFormatDetection);

      doc.removeEventListener("mouseup", triggerFormatDetection);
      doc.addEventListener("mouseup", triggerFormatDetection);

      doc.removeEventListener("click", triggerFormatDetection);
      doc.addEventListener("click", triggerFormatDetection);

      triggerFormatDetection();
    } catch (err) {
      console.warn("Notice enabling slide designMode:", err);
    }
  };

  const teardownEditableDocument = (doc: Document) => {
    try {
      doc.designMode = "off";
      if (doc.body) {
        doc.body.contentEditable = "false";
      }
      const style = doc.getElementById("kelostats-edit-styles");
      if (style) {
        style.remove();
      }
      doc.removeEventListener("keydown", handleIframeKeyDown);
      doc.removeEventListener("selectionchange", triggerFormatDetection);
      doc.removeEventListener("keyup", triggerFormatDetection);
      doc.removeEventListener("mouseup", triggerFormatDetection);
      doc.removeEventListener("click", triggerFormatDetection);
    } catch (err) {
      console.warn("Notice disabling slide designMode:", err);
    }
  };

  const enableSlideEditing = () => {
    setIsEditingSlide(true);
    const doc = iframeRef.current?.contentDocument;
    if (doc) {
      setupEditableDocument(doc);
    }
  };

  const disableSlideEditing = () => {
    setIsEditingSlide(false);
    const doc = iframeRef.current?.contentDocument;
    if (doc) {
      teardownEditableDocument(doc);
    }
  };

  const handleIframeLoad = () => {
    const iframe = iframeRef.current;
    if (!iframe) return;
    const doc = iframe.contentDocument;
    if (!doc) return;

    try {
      const win = iframe.contentWindow as any;
      if (win && win.lucide && typeof win.lucide.createIcons === "function") {
        win.lucide.createIcons();
      }
    } catch (err) {}

    doc.addEventListener("dblclick", () => {
      enableSlideEditing();
    });

    if (isEditingSlide) {
      setupEditableDocument(doc);
    }

    // When the iframe finishes rendering, smoothly reveal the PPT from blur
    if (isSlideRefreshing) {
      setTimeout(() => {
        setIsSlideRefreshing(false);
      }, 250);
    }
  };

  const handleApplyFormat = (command: string, value?: string) => {
    const iframe = iframeRef.current;
    if (!iframe || !iframe.contentDocument) return;
    const doc = iframe.contentDocument;

    iframe.contentWindow?.focus();

    if (command === "fontSizeCustom" && value) {
      const numPx = parseInt(value) || 16;
      const sel = doc.getSelection();

      if (sel && sel.rangeCount > 0) {
        if (!sel.isCollapsed) {
          try {
            doc.execCommand("styleWithCSS", false, "false");
            doc.execCommand("fontSize", false, "7");

            const fontTags = doc.querySelectorAll("font[size='7']");
            fontTags.forEach((fontTag) => {
              fontTag.removeAttribute("size");
              (fontTag as HTMLElement).style.fontSize = `${numPx}px`;
            });

            const largeSpans = doc.querySelectorAll('span[style*="xxx-large"]');
            largeSpans.forEach((spanTag) => {
              (spanTag as HTMLElement).style.fontSize = `${numPx}px`;
            });
          } catch (e) {}

          try {
            const range = sel.getRangeAt(0);
            let container: Node | null = range.commonAncestorContainer;
            if (container.nodeType !== Node.ELEMENT_NODE) {
              container = container.parentElement;
            }
            if (container && container !== doc.body) {
              const el = container as HTMLElement;
              if (el.style && el.style.fontSize) {
                el.style.fontSize = `${numPx}px`;
              }
              const styledChildren = el.querySelectorAll("[style*='font-size']");
              styledChildren.forEach((child) => {
                (child as HTMLElement).style.fontSize = `${numPx}px`;
              });
            }
          } catch (e) {}
        } else if (sel.anchorNode) {
          let cur: HTMLElement | null =
            sel.anchorNode.nodeType === Node.ELEMENT_NODE
              ? (sel.anchorNode as HTMLElement)
              : sel.anchorNode.parentElement;
          while (cur && cur !== doc.body) {
            if (
              cur.style.fontSize ||
              ["H1", "H2", "H3", "H4", "H5", "H6", "P", "SPAN", "LI", "DIV"].includes(cur.tagName)
            ) {
              cur.style.fontSize = `${numPx}px`;
              break;
            }
            cur = cur.parentElement;
          }
        }
      }
      setTimeout(triggerFormatDetection, 30);
    } else if (command === "fontName" && value) {
      doc.execCommand("styleWithCSS", false, "true");
      doc.execCommand("fontName", false, value);
      const sel = doc.getSelection();
      if (sel && sel.anchorNode) {
        const parent =
          sel.anchorNode.nodeType === Node.ELEMENT_NODE
            ? (sel.anchorNode as HTMLElement)
            : sel.anchorNode.parentElement;
        if (parent) {
          parent.style.fontFamily = value;
        }
      }
      triggerFormatDetection();
    } else if (command === "hiliteColor" && value) {
      doc.execCommand("styleWithCSS", false, "true");
      if (!doc.execCommand("hiliteColor", false, value)) {
        doc.execCommand("backColor", false, value);
      }
      triggerFormatDetection();
    } else {
      doc.execCommand("styleWithCSS", false, "true");
      doc.execCommand(command, false, value ?? undefined);
      triggerFormatDetection();
    }
  };

  const handleSaveSlideChanges = async () => {
    if (!userId || !projectId || !currentSlide || isSavingTools) return;
    const iframe = iframeRef.current;
    if (!iframe || !iframe.contentDocument) return;
    const doc = iframe.contentDocument;

    setIsSavingTools(true);
    try {
      const clone = doc.documentElement.cloneNode(true) as HTMLElement;
      const editStyles = clone.querySelectorAll("#kelostats-edit-styles");
      editStyles.forEach((el) => el.remove());

      clone.removeAttribute("contenteditable");
      const editables = clone.querySelectorAll("[contenteditable]");
      editables.forEach((el) => el.removeAttribute("contenteditable"));

      const updatedHtml = "<!DOCTYPE html>\n" + clone.outerHTML;

      const res = await fetchWithAuth(`${API_BASE_URL}/api/workspace/editor/tools`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          user_id: userId,
          project_id: projectId,
          slide_number: currentSlide.slide_number,
          html_code: updatedHtml,
          action: "update_html",
        }),
      });

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.detail || "Failed to update slide design.");
      }

      setSlides((prevSlides) =>
        prevSlides.map((s, idx) =>
          idx === activeSlideIndex
            ? {
                ...s,
                raw_html: updatedHtml,
                rendered_html: updatedHtml,
              }
            : s
        )
      );

      setSaveSuccessMsg(`Slide ${currentSlide.slide_number} design saved successfully!`);
      setTimeout(() => setSaveSuccessMsg(null), 3500);
    } catch (err: any) {
      console.error("Error saving slide design:", err);
      alert(err.message || "Failed to save slide design changes.");
    } finally {
      setIsSavingTools(false);
    }
  };

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
          {(refreshing || isSlideRefreshing) && (
            <span className="flex items-center gap-1.5 text-xs font-medium text-orange-600 bg-orange-50 border border-orange-200 px-2.5 py-0.5 rounded-lg animate-pulse shadow-2xs">
              <svg className="animate-spin w-3.5 h-3.5" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z" />
              </svg>
              <span>Syncing slides...</span>
            </span>
          )}
        </div>

        {/* Right: Actions */}
        <div className="flex items-center gap-2">
          {/* Edit Slide Button */}
          <button
            type="button"
            onClick={() => {
              if (isEditingSlide) disableSlideEditing();
              else enableSlideEditing();
            }}
            title="Edit slide design and text (or double-click the slide)"
            className={`px-3 py-1.5 rounded-lg border text-xs font-semibold transition-all flex items-center gap-1.5 cursor-pointer ${
              isEditingSlide
                ? "bg-amber-100 text-amber-900 border-amber-300 shadow-2xs font-bold"
                : "bg-slate-100 text-slate-700 border-slate-200 hover:bg-slate-200"
            }`}
          >
            <svg className="w-3.5 h-3.5 text-[#FF5148]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z" />
            </svg>
            <span className="hidden sm:inline">{isEditingSlide ? "Done Editing" : "Edit Slide"}</span>
          </button>

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
            onClick={() => { loadSlidesFromS3(activeSlideIndex); }}
            disabled={refreshing || isSlideRefreshing}
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

            {/* Subtle Slim Progress Bar on sidebar during refresh (non-disruptive) */}
            {isSlideRefreshing && (
              <div className="h-0.5 w-full bg-orange-100 overflow-hidden shrink-0">
                <div className="h-full bg-gradient-to-r from-orange-400 to-[#FF5148] animate-pulse w-full" />
              </div>
            )}

            {/* Thumbnails Scrollable List */}
            <div className="flex-1 overflow-y-auto p-3 space-y-3 min-w-[240px] custom-chat-scrollbar">
              {loading && slides.length === 0 ? (
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
                          onClick={() => {
                            if (isEditingSlide) disableSlideEditing();
                            setActiveSlideIndex(idx);
                          }}
                          className={`w-full aspect-[16/9] rounded-md cursor-pointer transition-all border overflow-hidden shadow-xs relative bg-white ${
                            isActive
                              ? "border-2 border-[#FF5148] ring-2 ring-[#FF5148]/20 shadow-sm"
                              : "border-slate-200 hover:border-slate-400 hover:bg-slate-50"
                          }`}
                        >
                          <div className="absolute inset-0 z-10 cursor-pointer" />
                          <SlideThumbnail
                            html={slide.raw_html || slide.rendered_html}
                            title={`Slide ${idx + 1} preview`}
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
            {/* Designing Tools Toolbar placed at top of PPT page */}
            {isEditingSlide && (
              <div className="sticky top-0 z-30 w-full shadow-xs">
                <DesigningTools
                  onApplyFormat={handleApplyFormat}
                  onSave={handleSaveSlideChanges}
                  onClose={disableSlideEditing}
                  isSaving={isSavingTools}
                  activeSlideNumber={currentSlide?.slide_number ?? (activeSlideIndex + 1)}
                  activeFormat={activeFormat}
                />
              </div>
            )}

            {/* Floating Open Slides Button (when sidebar is closed) */}
            {!isSidebarOpen && (
              <button
                type="button"
                onClick={() => setIsSidebarOpen(true)}
                title="Open slides sidebar"
                className="absolute top-4 left-4 z-20 flex items-center gap-2 px-3 py-2 bg-white/95 backdrop-blur-sm border border-slate-200/90 shadow-md hover:shadow-lg rounded-xl text-xs font-semibold text-slate-700 hover:text-[#FF5148] transition-all hover:scale-105 active:scale-95 cursor-pointer"
              >
                <div className="w-5 h-5 rounded-md bg-orange-50 text-[#FF5148] flex items-center justify-center">
                  <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
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
                  <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
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
              {loading && slides.length === 0 ? (
                <div className="flex flex-col items-center justify-center p-12 bg-white rounded-2xl shadow-sm border border-slate-200">
                  <svg className="animate-spin w-8 h-8 text-[#FF5148] mb-4" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z" />
                  </svg>
                  <p className="text-sm font-semibold text-slate-700">Loading presentation...</p>
                </div>
              ) : loadError && slides.length === 0 ? (
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
                /* 16:9 Presentation Canvas rendered in isolated native iframe */
                <div
                  onDoubleClick={isSlideRefreshing ? undefined : enableSlideEditing}
                  className={`w-full max-w-4xl aspect-[16/9] rounded-xs shadow-2xl relative bg-white overflow-hidden group ${
                    isEditingSlide
                      ? "ring-4 ring-[#FF5148]/50 border-2 border-[#FF5148]"
                      : "border border-slate-200 hover:border-slate-300 cursor-pointer"
                  }`}
                  title={
                    isSlideRefreshing
                      ? "Updating slide..."
                      : isEditingSlide
                      ? "Slide in edit mode - double-click any text to edit directly"
                      : "Double-click slide to open Designing Tools"
                  }
                >
                  {/* PPT Content with smooth blur-to-crisp reveal transition */}
                  <div
                    className="w-full h-full relative"
                    style={{
                      filter: isSlideRefreshing ? "blur(14px) brightness(0.97)" : "blur(0px) brightness(1)",
                      opacity: isSlideRefreshing ? 0.88 : 1,
                      transform: isSlideRefreshing ? "scale(0.992)" : "scale(1)",
                      transition: "filter 0.8s cubic-bezier(0.16, 1, 0.3, 1), opacity 0.8s cubic-bezier(0.16, 1, 0.3, 1), transform 0.8s cubic-bezier(0.16, 1, 0.3, 1)",
                      willChange: "filter, opacity, transform",
                    }}
                  >
                    {(() => {
                      const slideCode = currentSlide.raw_html || currentSlide.rendered_html;
                      const lucideInject = `<script src="https://cdn.jsdelivr.net/npm/chart.js"></script><script src="https://unpkg.com/lucide@latest"></script><link rel="stylesheet" href="https://unpkg.com/lucide-static@1.45.0/font/lucide.css">`;
                      const cleanDoc = slideCode.includes("<head>")
                        ? slideCode.replace(
                            "<head>",
                            `<head>${lucideInject}<style>html,body{margin:0!important;padding:0!important;overflow:hidden!important;width:100%!important;height:100%!important;} .slide-canvas{width:100%!important;height:100%!important;max-width:100%!important;}</style>`
                          )
                        : `<!DOCTYPE html><html><head>${lucideInject}<style>html,body{margin:0!important;padding:0!important;overflow:hidden!important;width:100%!important;height:100%!important;} .slide-canvas{width:100%!important;height:100%!important;max-width:100%!important;}</style></head><body>${slideCode}</body></html>`;

                      return (
                        <iframe
                          ref={iframeRef}
                          key={`${currentSlide.s3_key || activeSlideIndex}-${currentSlide.slide_number}-${slideCode.length}`}
                          srcDoc={cleanDoc}
                          className="w-full h-full border-0 block"
                          scrolling="no"
                          sandbox="allow-scripts allow-same-origin"
                          title={currentSlide.name || `Slide ${activeSlideIndex + 1}`}
                          onLoad={handleIframeLoad}
                        />
                      );
                    })()}
                  </div>

                  {/* Elegant Floating Badge during S3 Refresh */}
                  {isSlideRefreshing && (
                    <div className="absolute inset-0 z-30 flex items-center justify-center pointer-events-none animate-in fade-in duration-300">
                      <div className="flex items-center gap-2.5 px-4 py-2 bg-white/90 backdrop-blur-md shadow-xl border border-slate-200/80 rounded-full text-xs font-semibold text-slate-700">
                        <svg className="animate-spin w-4 h-4 text-[#FF5148]" fill="none" viewBox="0 0 24 24">
                          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z" />
                        </svg>
                        <span>Updating Slide...</span>
                      </div>
                    </div>
                  )}

                  {!isEditingSlide && !isSlideRefreshing && (
                    <div className="absolute bottom-2.5 right-3 z-20 opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none bg-slate-900/80 backdrop-blur-xs text-white px-2.5 py-1 rounded-md text-[10px] font-medium shadow-sm">
                      Double-click slide to edit design
                    </div>
                  )}
                </div>
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
                databaseDisplayName={databaseDisplayName}
                collectionId={collectionId}
                collectionDisplayName={collectionDisplayName}
                source={source}
                slideNumber={currentSlide?.slide_number ?? (activeSlideIndex + 1)}
                totalSlides={slides.length}
                onSelectSlide={(slideNum) => {
                  const idx = slides.findIndex((s) => s.slide_number === slideNum);
                  if (idx !== -1) setActiveSlideIndex(idx);
                }}
                onSlideRefreshRequired={(targetSlideNum) => {
                  loadSlidesFromS3(undefined, targetSlideNum);
                }}
                onClose={() => setIsChatOpen(false)}
                isExpanded={isChatExpanded}
                onToggleExpand={toggleExpandChat}
              />
            </div>
          )}
        </div>
      </div>

      {/* Toast Notification for Error when slides are already loaded */}
      {loadError && slides.length > 0 && (
        <div className="fixed top-14 right-6 z-50 bg-red-50 border border-red-200 text-red-700 px-4 py-2.5 rounded-xl shadow-lg text-xs font-semibold flex items-center gap-2 animate-in fade-in">
          <svg className="w-4 h-4 text-red-500 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          <span>{loadError}</span>
          <button onClick={() => setLoadError(null)} className="ml-2 text-red-400 hover:text-red-700 font-bold cursor-pointer">&times;</button>
        </div>
      )}

      {/* Toast Notification for Success */}
      {saveSuccessMsg && (
        <div className="fixed bottom-6 right-6 z-50 bg-slate-900/95 backdrop-blur-md text-white px-4 py-2.5 rounded-xl shadow-2xl text-xs font-semibold flex items-center gap-2 animate-in fade-in slide-in-from-bottom-2 border border-slate-700">
          <svg className="w-4 h-4 text-emerald-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 13l4 4L19 7" />
          </svg>
          <span>{saveSuccessMsg}</span>
        </div>
      )}
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
