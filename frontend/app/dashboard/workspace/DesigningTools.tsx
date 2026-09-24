"use client";

import React, { useState, useEffect } from "react";

export interface ActiveFormatInfo {
  fontFamily: string;
  fontSize: string;
  bold: boolean;
  italic: boolean;
  underline: boolean;
  strikethrough: boolean;
  superscript: boolean;
  align: string;
  textColor?: string;
  highlightColor?: string;
}

interface DesigningToolsProps {
  onApplyFormat: (command: string, value?: string) => void;
  onSave: () => void;
  onClose: () => void;
  isSaving?: boolean;
  activeSlideNumber?: number;
  activeFormat?: ActiveFormatInfo;
}

export default function DesigningTools({
  onApplyFormat,
  onSave,
  onClose,
  isSaving = false,
  activeSlideNumber = 1,
  activeFormat,
}: DesigningToolsProps) {
  const [fontFamily, setFontFamily] = useState(activeFormat?.fontFamily || "Arial");
  const [fontSize, setFontSize] = useState(activeFormat?.fontSize || "16");
  const [textColor, setTextColor] = useState(activeFormat?.textColor || "#000000");
  const [highlightColor, setHighlightColor] = useState(activeFormat?.highlightColor || "#FFFF00");
  const [activeAlign, setActiveAlign] = useState(activeFormat?.align || "left");
  const [activeFormats, setActiveFormats] = useState<Record<string, boolean>>({
    bold: !!activeFormat?.bold,
    italic: !!activeFormat?.italic,
    underline: !!activeFormat?.underline,
    strikethrough: !!activeFormat?.strikethrough,
    superscript: !!activeFormat?.superscript,
    subscript: false,
  });

  const [fontOptions, setFontOptions] = useState<string[]>([
    "Arial",
    "Georgia",
    "Calibri",
    "Helvetica",
    "Inter",
    "Roboto",
    "Times New Roman",
    "Trebuchet MS",
    "Verdana",
    "Courier New",
    "Impact",
    "Comic Sans MS",
  ]);

  const [sizeOptions, setSizeOptions] = useState<string[]>([
    "8",
    "9",
    "10",
    "11",
    "12",
    "14",
    "16",
    "18",
    "20",
    "24",
    "28",
    "32",
    "36",
    "40",
    "48",
    "56",
    "64",
    "72",
  ]);

  // Synchronize toolbar with cursor selection inside slide iframe
  useEffect(() => {
    if (activeFormat) {
      if (activeFormat.fontFamily) {
        setFontFamily(activeFormat.fontFamily);
        setFontOptions((prev) =>
          prev.includes(activeFormat.fontFamily) ? prev : [activeFormat.fontFamily, ...prev]
        );
      }
      if (activeFormat.fontSize) {
        setFontSize(activeFormat.fontSize);
        setSizeOptions((prev) =>
          prev.includes(activeFormat.fontSize)
            ? prev
            : [...prev, activeFormat.fontSize].sort((a, b) => parseInt(a) - parseInt(b))
        );
      }
      if (activeFormat.textColor) setTextColor(activeFormat.textColor);
      if (activeFormat.highlightColor) setHighlightColor(activeFormat.highlightColor);
      if (activeFormat.align) setActiveAlign(activeFormat.align);
      setActiveFormats({
        bold: !!activeFormat.bold,
        italic: !!activeFormat.italic,
        underline: !!activeFormat.underline,
        strikethrough: !!activeFormat.strikethrough,
        superscript: !!activeFormat.superscript,
        subscript: false,
      });
    }
  }, [activeFormat]);

  const handleFontChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const val = e.target.value;
    setFontFamily(val);
    onApplyFormat("fontName", val);
  };

  const handleSizeChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const val = e.target.value;
    setFontSize(val);
    onApplyFormat("fontSizeCustom", `${val}px`);
  };

  const handleIncreaseSize = () => {
    const current = parseInt(fontSize) || 16;
    const standardSizes = [8, 9, 10, 11, 12, 14, 16, 18, 20, 24, 28, 32, 36, 40, 48, 56, 64, 72, 96];
    let next = standardSizes.find((s) => s > current);
    if (!next) next = current + 8;
    const nextSize = `${Math.min(96, next)}`;

    setFontSize(nextSize);
    setSizeOptions((prev) =>
      prev.includes(nextSize) ? prev : [...prev, nextSize].sort((a, b) => parseInt(a) - parseInt(b))
    );
    onApplyFormat("fontSizeCustom", `${nextSize}px`);
  };

  const handleDecreaseSize = () => {
    const current = parseInt(fontSize) || 16;
    const standardSizes = [8, 9, 10, 11, 12, 14, 16, 18, 20, 24, 28, 32, 36, 40, 48, 56, 64, 72, 96];
    const reversed = [...standardSizes].reverse();
    let prev = reversed.find((s) => s < current);
    if (!prev) prev = Math.max(8, current - 2);
    const prevSize = `${prev}`;

    setFontSize(prevSize);
    setSizeOptions((prev) =>
      prev.includes(prevSize) ? prev : [...prev, prevSize].sort((a, b) => parseInt(a) - parseInt(b))
    );
    onApplyFormat("fontSizeCustom", `${prevSize}px`);
  };

  const toggleFormat = (cmd: string, formatKey: string) => {
    setActiveFormats((prev) => ({ ...prev, [formatKey]: !prev[formatKey] }));
    onApplyFormat(cmd);
  };

  const handleAlign = (align: string) => {
    setActiveAlign(align);
    if (align === "left") onApplyFormat("justifyLeft");
    else if (align === "center") onApplyFormat("justifyCenter");
    else if (align === "right") onApplyFormat("justifyRight");
    else if (align === "justify") onApplyFormat("justifyFull");
  };

  const handleTextColorChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const color = e.target.value;
    setTextColor(color);
    onApplyFormat("foreColor", color);
  };

  const handleHighlightColorChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const color = e.target.value;
    setHighlightColor(color);
    onApplyFormat("hiliteColor", color);
  };

  // Prevent focus blur from the iframe selection when clicking toolbar buttons
  const preventBlur = (e: React.MouseEvent) => {
    const tag = (e.target as HTMLElement).tagName;
    if (tag !== "INPUT" && tag !== "SELECT" && tag !== "OPTION") {
      e.preventDefault();
    }
  };

  return (
    <div
      onMouseDown={preventBlur}
      className="w-full bg-white border-b border-slate-300 shadow-sm px-4 py-2 flex items-center justify-between gap-4 text-slate-800 select-none z-30 animate-in fade-in slide-in-from-top-2 duration-200"
    >
      {/* 2-Row Ribbon Editor (Matches PPT Ribbon Layout) */}
      <div className="flex items-center gap-4 overflow-x-auto custom-chat-scrollbar py-0.5">
        {/* ================================================================= */}
        {/* SECTION 1: FONT FORMATTING (2 ROWS) */}
        {/* ================================================================= */}
        <div className="flex flex-col gap-1.5 shrink-0">
          {/* Row 1: Font Family, Font Size, A+, A-, Eraser */}
          <div className="flex items-center gap-1.5">
            {/* Dynamic Font Dropdown */}
            <div className="relative inline-flex items-center">
              <select
                value={fontFamily}
                onChange={handleFontChange}
                className="h-7 pl-2.5 pr-6 text-xs font-medium bg-white border border-slate-300 rounded hover:border-slate-400 focus:outline-none focus:ring-1 focus:ring-[#FF5148] cursor-pointer appearance-none min-w-[120px]"
                title="Font Family"
              >
                {fontOptions.map((f) => (
                  <option key={f} value={f} style={{ fontFamily: f }}>
                    {f}
                  </option>
                ))}
              </select>
              <svg
                className="w-3 h-3 text-slate-500 absolute right-2 pointer-events-none"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
              </svg>
            </div>

            {/* Dynamic Font Size Dropdown */}
            <div className="relative inline-flex items-center">
              <select
                value={fontSize}
                onChange={handleSizeChange}
                className="h-7 pl-2 pr-5 text-xs font-medium bg-white border border-slate-300 rounded hover:border-slate-400 focus:outline-none focus:ring-1 focus:ring-[#FF5148] cursor-pointer appearance-none w-14"
                title="Font Size"
              >
                {sizeOptions.map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </select>
              <svg
                className="w-3 h-3 text-slate-500 absolute right-1.5 pointer-events-none"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
              </svg>
            </div>

            {/* A+ Increase Font */}
            <button
              type="button"
              onClick={handleIncreaseSize}
              className="h-7 px-1.5 flex items-center justify-center rounded hover:bg-slate-100 text-xs font-bold text-slate-700 cursor-pointer"
              title="Increase Font Size"
            >
              <span>A</span>
              <span className="text-[10px] text-blue-600 font-extrabold ml-0.5">+</span>
            </button>

            {/* A- Decrease Font */}
            <button
              type="button"
              onClick={handleDecreaseSize}
              className="h-7 px-1.5 flex items-center justify-center rounded hover:bg-slate-100 text-xs font-bold text-slate-700 cursor-pointer"
              title="Decrease Font Size"
            >
              <span>A</span>
              <span className="text-[10px] text-blue-600 font-extrabold ml-0.5">-</span>
            </button>

            {/* Eraser / Clear Formatting */}
            <button
              type="button"
              onClick={() => onApplyFormat("removeFormat")}
              className="h-7 w-7 flex items-center justify-center rounded hover:bg-slate-100 text-slate-600 cursor-pointer ml-1"
              title="Clear All Formatting"
            >
              <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19.5 8.5l-6-6a2.121 2.121 0 00-3 0l-7.5 7.5a2.121 2.121 0 000 3l5 5a2.121 2.121 0 003 0l8.5-8.5a2.121 2.121 0 000-3z" />
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M18 14l-4 4M2 21h20" />
              </svg>
            </button>
          </div>

          {/* Row 2: B, I, U, Strikethrough, X^2, Font Color, Highlight Color */}
          <div className="flex items-center gap-1">
            {/* Bold */}
            <button
              type="button"
              onClick={() => toggleFormat("bold", "bold")}
              className={`h-7 w-7 flex items-center justify-center rounded text-xs font-bold cursor-pointer transition-colors ${
                activeFormats.bold ? "bg-slate-200 text-[#FF5148]" : "hover:bg-slate-100 text-slate-800"
              }`}
              title="Bold (Ctrl+B)"
            >
              B
            </button>

            {/* Italic */}
            <button
              type="button"
              onClick={() => toggleFormat("italic", "italic")}
              className={`h-7 w-7 flex items-center justify-center rounded text-xs italic font-serif cursor-pointer transition-colors ${
                activeFormats.italic ? "bg-slate-200 text-[#FF5148]" : "hover:bg-slate-100 text-slate-800"
              }`}
              title="Italic (Ctrl+I)"
            >
              I
            </button>

            {/* Underline */}
            <button
              type="button"
              onClick={() => toggleFormat("underline", "underline")}
              className={`h-7 w-7 flex items-center justify-center rounded text-xs underline cursor-pointer transition-colors ${
                activeFormats.underline ? "bg-slate-200 text-[#FF5148]" : "hover:bg-slate-100 text-slate-800"
              }`}
              title="Underline (Ctrl+U)"
            >
              U
            </button>

            {/* Strikethrough */}
            <button
              type="button"
              onClick={() => toggleFormat("strikeThrough", "strikethrough")}
              className={`h-7 w-7 flex items-center justify-center rounded text-xs cursor-pointer transition-colors ${
                activeFormats.strikethrough ? "bg-slate-200 text-[#FF5148]" : "hover:bg-slate-100 text-slate-800"
              }`}
              title="Strikethrough"
            >
              <span className="line-through">S</span>
            </button>

            {/* Superscript X^2 */}
            <button
              type="button"
              onClick={() => toggleFormat("superscript", "superscript")}
              className={`h-7 w-7 flex items-center justify-center rounded text-xs cursor-pointer transition-colors ${
                activeFormats.superscript ? "bg-slate-200 text-[#FF5148]" : "hover:bg-slate-100 text-slate-800"
              }`}
              title="Superscript"
            >
              <span>X</span>
              <sup className="text-[9px] font-semibold -top-1">2</sup>
            </button>

            {/* Font Color with color indicator bar */}
            <label
              className="relative h-7 px-1.5 flex flex-col items-center justify-center rounded hover:bg-slate-100 cursor-pointer"
              title="Font Color"
            >
              <div className="flex items-center gap-0.5">
                <span className="text-xs font-bold leading-none">A</span>
                <svg className="w-2.5 h-2.5 text-slate-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                </svg>
              </div>
              <span
                className="w-4 h-1 rounded-xs mt-0.5"
                style={{ backgroundColor: textColor }}
              ></span>
              <input
                type="color"
                value={textColor}
                onChange={handleTextColorChange}
                className="opacity-0 absolute inset-0 w-full h-full cursor-pointer"
              />
            </label>

            {/* Highlight Color with highlighter pen */}
            <label
              className="relative h-7 px-1.5 flex flex-col items-center justify-center rounded hover:bg-slate-100 cursor-pointer"
              title="Highlight Color"
            >
              <div className="flex items-center gap-0.5">
                <svg className="w-3.5 h-3.5 text-slate-700" viewBox="0 0 24 24" fill="none" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z" />
                </svg>
                <svg className="w-2.5 h-2.5 text-slate-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                </svg>
              </div>
              <span
                className="w-4 h-1 rounded-xs mt-0.5"
                style={{ backgroundColor: highlightColor }}
              ></span>
              <input
                type="color"
                value={highlightColor}
                onChange={handleHighlightColorChange}
                className="opacity-0 absolute inset-0 w-full h-full cursor-pointer"
              />
            </label>
          </div>
        </div>

        {/* ================================================================= */}
        {/* VERTICAL DIVIDER */}
        {/* ================================================================= */}
        <div className="h-14 w-[1px] bg-slate-200 shrink-0 mx-1"></div>

        {/* ================================================================= */}
        {/* SECTION 2: PARAGRAPH FORMATTING (2 ROWS) */}
        {/* ================================================================= */}
        <div className="flex flex-col gap-1.5 shrink-0">
          {/* Row 1: Bullets, Numbering, Decrease Indent, Increase Indent, Direction */}
          <div className="flex items-center gap-1">
            {/* Bullets */}
            <button
              type="button"
              onClick={() => onApplyFormat("insertUnorderedList")}
              className="h-7 px-1.5 flex items-center gap-0.5 rounded hover:bg-slate-100 text-slate-700 cursor-pointer"
              title="Bullets"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h.01M4 12h.01M4 18h.01M8 6h12M8 12h12M8 18h12" />
              </svg>
              <svg className="w-2.5 h-2.5 text-slate-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
              </svg>
            </button>

            {/* Numbering */}
            <button
              type="button"
              onClick={() => onApplyFormat("insertOrderedList")}
              className="h-7 px-1.5 flex items-center gap-0.5 rounded hover:bg-slate-100 text-slate-700 cursor-pointer"
              title="Numbering"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 6h13M7 12h13M7 18h13M3 6h.01M3 12h.01M3 18h.01" />
              </svg>
              <svg className="w-2.5 h-2.5 text-slate-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
              </svg>
            </button>

            {/* Decrease Indent */}
            <button
              type="button"
              onClick={() => onApplyFormat("outdent")}
              className="h-7 w-7 flex items-center justify-center rounded hover:bg-slate-100 text-slate-700 cursor-pointer"
              title="Decrease List Level"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 19l-7-7 7-7m8 14l-7-7 7-7" />
              </svg>
            </button>

            {/* Increase Indent */}
            <button
              type="button"
              onClick={() => onApplyFormat("indent")}
              className="h-7 w-7 flex items-center justify-center rounded hover:bg-slate-100 text-blue-600 cursor-pointer"
              title="Increase List Level"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 5l7 7-7 7M5 5l7 7-7 7" />
              </svg>
            </button>

            {/* Line Spacing / Sort Indicator */}
            <button
              type="button"
              onClick={() => onApplyFormat("formatBlock", "<p>")}
              className="h-7 px-1.5 flex items-center gap-0.5 rounded hover:bg-slate-100 text-slate-700 cursor-pointer"
              title="Line & Paragraph Spacing"
            >
              <span className="text-xs font-semibold text-slate-700">ab</span>
              <svg className="w-2.5 h-2.5 text-slate-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
              </svg>
            </button>
          </div>

          {/* Row 2: Align Left, Align Center, Align Right, Justify, Columns */}
          <div className="flex items-center gap-1">
            {/* Align Left */}
            <button
              type="button"
              onClick={() => handleAlign("left")}
              className={`h-7 w-7 flex items-center justify-center rounded cursor-pointer transition-colors ${
                activeAlign === "left" ? "bg-slate-200 text-[#FF5148]" : "hover:bg-slate-100 text-slate-700"
              }`}
              title="Align Left (Ctrl+L)"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h10M4 18h14" />
              </svg>
            </button>

            {/* Align Center */}
            <button
              type="button"
              onClick={() => handleAlign("center")}
              className={`h-7 w-7 flex items-center justify-center rounded cursor-pointer transition-colors ${
                activeAlign === "center" ? "bg-slate-200 text-[#FF5148]" : "hover:bg-slate-100 text-slate-700"
              }`}
              title="Center (Ctrl+E)"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M7 12h10M5 18h14" />
              </svg>
            </button>

            {/* Align Right */}
            <button
              type="button"
              onClick={() => handleAlign("right")}
              className={`h-7 w-7 flex items-center justify-center rounded cursor-pointer transition-colors ${
                activeAlign === "right" ? "bg-slate-200 text-[#FF5148]" : "hover:bg-slate-100 text-slate-700"
              }`}
              title="Align Right (Ctrl+R)"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M10 12h10M6 18h14" />
              </svg>
            </button>

            {/* Justify */}
            <button
              type="button"
              onClick={() => handleAlign("justify")}
              className={`h-7 w-7 flex items-center justify-center rounded cursor-pointer transition-colors ${
                activeAlign === "justify" ? "bg-slate-200 text-[#FF5148]" : "hover:bg-slate-100 text-slate-700"
              }`}
              title="Justify (Ctrl+J)"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
              </svg>
            </button>

            {/* Distributed / Columns */}
            <button
              type="button"
              onClick={() => onApplyFormat("formatBlock", "<blockquote>")}
              className="h-7 w-7 flex items-center justify-center rounded hover:bg-slate-100 text-slate-700 cursor-pointer"
              title="Quote / Block"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 8h10M7 12h4m1 8l-4-4H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-3l-4 4z" />
              </svg>
            </button>
          </div>
        </div>
      </div>

      {/* ===================================================================== */}
      {/* RIGHT SIDE: SAVE & CLOSE ACTIONS */}
      {/* ===================================================================== */}
      <div className="flex items-center gap-2 shrink-0">
        {/* Save Slide Button */}
        <button
          type="button"
          onClick={onSave}
          disabled={isSaving}
          className="h-8 px-3.5 bg-[#FF5148] hover:bg-[#e0443c] text-white text-xs font-bold rounded-lg shadow-sm flex items-center gap-1.5 cursor-pointer disabled:opacity-50 transition-all hover:scale-105 active:scale-95"
          title="Save Slide Changes to S3"
        >
          {isSaving ? (
            <>
              <svg className="animate-spin w-3.5 h-3.5" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z" />
              </svg>
              <span>Saving...</span>
            </>
          ) : (
            <>
              <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 13l4 4L19 7" />
              </svg>
              <span>Save Slide</span>
            </>
          )}
        </button>

        {/* Close Button */}
        <button
          type="button"
          onClick={onClose}
          className="h-8 px-2.5 text-slate-500 hover:text-slate-800 hover:bg-slate-100 rounded-lg text-xs font-medium flex items-center gap-1 cursor-pointer transition-colors"
          title="Exit Editing Mode"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
          </svg>
          <span className="hidden sm:inline">Done</span>
        </button>
      </div>
    </div>
  );
}
