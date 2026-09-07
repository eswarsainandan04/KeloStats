"use client";

import React from "react";

export default function DocumentsPage() {
  return (
    <div className="space-y-8 animate-in fade-in duration-200">
      {/* Header Section */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2.5">
            <h1 className="text-2xl font-extrabold text-slate-900 tracking-tight">Documents (RAG)</h1>
            <span className="inline-flex items-center gap-1.5 px-3 py-0.5 rounded-full text-xs font-bold bg-gradient-to-r from-orange-100 to-amber-100 text-[#FF5148] border border-[#FF5148]/20">
              <span className="w-1.5 h-1.5 rounded-full bg-[#FF5148] animate-ping" />
              Coming Soon
            </span>
          </div>
          <p className="text-sm text-slate-500 mt-1">
            Enterprise document ingestion & Retrieval-Augmented Generation pipeline for AI presentations.
          </p>
        </div>
      </div>

      {/* Main Coming Soon Hero Container */}
      <div className="relative rounded-3xl border border-slate-200/90 bg-white p-8 sm:p-14 overflow-hidden shadow-sm text-center flex flex-col items-center justify-center">
        {/* Ambient background glow elements */}
        <div className="absolute -top-24 -left-24 w-72 h-72 rounded-full bg-orange-100/60 blur-3xl pointer-events-none" />
        <div className="absolute -bottom-24 -right-24 w-72 h-72 rounded-full bg-amber-100/60 blur-3xl pointer-events-none" />

        {/* Hero Icon */}
        <div className="relative w-20 h-20 rounded-3xl bg-gradient-to-tr from-[#FF5148] to-orange-400 text-white flex items-center justify-center shadow-lg shadow-[#FF5148]/20 mb-6">
          <svg className="w-10 h-10" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={1.75}
              d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
            />
          </svg>
          <div className="absolute -bottom-1 -right-1 w-6 h-6 rounded-full bg-white text-[#FF5148] flex items-center justify-center shadow-sm border border-orange-100">
            <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M13 10V3L4 14h7v7l9-11h-7z" />
            </svg>
          </div>
        </div>

        {/* Hero Headline & Description */}
        <h2 className="text-2xl sm:text-3xl font-extrabold text-slate-900 tracking-tight max-w-xl">
          Retrieval-Augmented Generation for Enterprise Documents
        </h2>
        <p className="text-sm sm:text-base text-slate-500 mt-3 max-w-2xl leading-relaxed">
          Connect unstructured PDFs, annual reports, market research, and corporate knowledge bases. Our multi-agent orchestrator will semantically chunk, index, and synthesize executive slide decks grounding both database telemetry and document knowledge.
        </p>

        {/* Feature Highlights Grid */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-5 mt-10 w-full max-w-3xl text-left">
          <div className="p-5 rounded-2xl bg-slate-50/80 border border-slate-100 hover:border-orange-200/80 transition-all">
            <div className="w-10 h-10 rounded-xl bg-orange-100 text-[#FF5148] flex items-center justify-center font-bold text-base mb-3 shadow-2xs">
              📄
            </div>
            <h4 className="text-sm font-bold text-slate-900">Document Ingestion</h4>
            <p className="text-xs text-slate-500 mt-1 leading-relaxed">
              Upload PDFs, Word files, and reports with automatic vector chunking and metadata extraction.
            </p>
          </div>

          <div className="p-5 rounded-2xl bg-slate-50/80 border border-slate-100 hover:border-orange-200/80 transition-all">
            <div className="w-10 h-10 rounded-xl bg-amber-100 text-amber-700 flex items-center justify-center font-bold text-base mb-3 shadow-2xs">
              🔍
            </div>
            <h4 className="text-sm font-bold text-slate-900">Hybrid Search</h4>
            <p className="text-xs text-slate-500 mt-1 leading-relaxed">
              Synthesize SQL metrics with semantic document context for rigorous factual accuracy.
            </p>
          </div>

          <div className="p-5 rounded-2xl bg-slate-50/80 border border-slate-100 hover:border-orange-200/80 transition-all">
            <div className="w-10 h-10 rounded-xl bg-emerald-100 text-emerald-700 flex items-center justify-center font-bold text-base mb-3 shadow-2xs">
              📊
            </div>
            <h4 className="text-sm font-bold text-slate-900">Slide Synthesis</h4>
            <p className="text-xs text-slate-500 mt-1 leading-relaxed">
              Automatically extract quotes, metrics, and tables into branded, presentation-ready slides.
            </p>
          </div>
        </div>

        {/* Status Badge */}
        <div className="mt-10 inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-slate-100 text-slate-600 text-xs font-semibold">
          <span className="w-2 h-2 rounded-full bg-amber-500 animate-pulse" />
          <span>Feature in active development • Coming soon for Documents (RAG)</span>
        </div>
      </div>
    </div>
  );
}
