"use client";

import React, { useState, useEffect, useRef } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { API_BASE_URL } from "@/lib/config";

interface ChatMessage {
  id: string;
  sender: "ai" | "user";
  text: string;
  timestamp: string;
  decision?: string | null;
  generated_sql?: string | null;
}

interface ChatInterfaceProps {
  projectId?: string;
  userId?: string;
  databaseId?: string;
  slideNumber?: number;
  totalSlides?: number;
  onSelectSlide?: (slideNum: number) => void;
  onSlideRefreshRequired?: () => void;
  onClose?: () => void;
  isExpanded?: boolean;
  onToggleExpand?: () => void;
}

export default function ChatInterface({
  projectId,
  userId,
  databaseId,
  slideNumber,
  totalSlides,
  onSelectSlide,
  onSlideRefreshRequired,
  onClose,
  isExpanded,
  onToggleExpand,
}: ChatInterfaceProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [loadingHistory, setLoadingHistory] = useState(false);
  const [inputValue, setInputValue] = useState("");
  const [isTyping, setIsTyping] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const defaultWelcomeMessage: ChatMessage = {
    id: "welcome-1",
    sender: "ai",
    text: "👋 Hi! I'm your KeloStats Copilot. Ask me questions about your connected database metrics, or command me to generate presentation slides (e.g., 'What is total sales by category?' or 'Generate a slide on total sales').",
    timestamp: "Just now",
  };

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  // 1. Fetch chat history when projectId is available
  useEffect(() => {
    if (!projectId || projectId === "project_default") {
      setMessages([defaultWelcomeMessage]);
      return;
    }

    let isMounted = true;
    const fetchHistory = async () => {
      setLoadingHistory(true);
      try {
        const res = await fetch(`${API_BASE_URL}/api/workspace/chat/${projectId}`);
        if (res.ok) {
          const data = await res.json();
          const loadedMessages: ChatMessage[] = (data.messages || []).map((m: any) => {
            let msgText = m.text || "";
            // Clean up any raw slide HTML stored in history so it doesn't clutter chat
            if (msgText.includes("<!DOCTYPE html") || msgText.includes("class=\"slide-canvas\"")) {
              msgText = "✨ I've designed and updated your presentation slide based on your data insights.";
            }
            return {
              id: m.id || String(Math.random()),
              sender: m.sender === "user" ? "user" : "ai",
              text: msgText,
              timestamp: m.timestamp || "Recently",
            };
          });

          if (isMounted) {
            if (loadedMessages.length > 0) {
              setMessages(loadedMessages);
            } else {
              setMessages([defaultWelcomeMessage]);
            }
          }
        } else {
          if (isMounted) setMessages([defaultWelcomeMessage]);
        }
      } catch (err) {
        console.warn("Could not load chat history:", err);
        if (isMounted) setMessages([defaultWelcomeMessage]);
      } finally {
        if (isMounted) setLoadingHistory(false);
      }
    };

    fetchHistory();

    return () => {
      isMounted = false;
    };
  }, [projectId]);

  useEffect(() => {
    scrollToBottom();
  }, [messages, isTyping]);

  // 2. Handle Send Message -> POST /api/workflow/query
  const handleSendMessage = async (textToSend?: string) => {
    const query = (textToSend || inputValue).trim();
    if (!query || isTyping) return;

    const userMsgId = Date.now().toString();
    const nowTime = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

    const userMsg: ChatMessage = {
      id: userMsgId,
      sender: "user",
      text: query,
      timestamp: nowTime,
    };

    setMessages((prev) => [...prev, userMsg]);
    setInputValue("");
    setIsTyping(true);

    const targetSlideNumber = slideNumber && slideNumber > 0 ? slideNumber : 1;
    const targetFilename = `slide_${String(targetSlideNumber).padStart(2, "0")}.html`;

    try {
      const response = await fetch(`${API_BASE_URL}/api/workflow/query`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          user_query: query,
          database_id: databaseId || undefined,
          project_id: projectId || undefined,
          user_id: userId || undefined,
          slide_number: targetSlideNumber,
          slide_filename: targetFilename,
        }),
      });

      const data = await response.json();

      let replyText = "";
      if (response.ok) {
        if (data.decision === "agent") {
          const generatedSlideNum = data.slide_number || targetSlideNumber;
          const generatedFilename = data.slide_filename || `slide_${String(generatedSlideNum).padStart(2, "0")}.html`;
          replyText = data.output && !data.output.includes("<!DOCTYPE")
            ? data.output
            : `✨ I've designed Slide ${generatedSlideNum} (${generatedFilename}) based on your data and updated your presentation canvas.`;
          if (onSlideRefreshRequired) {
            onSlideRefreshRequired();
          }
        } else {
          replyText = data.output || "Query processed successfully.";
        }
      } else {
        replyText = data.detail || "Unable to process query. Please verify your database connection.";
      }

      const aiMsg: ChatMessage = {
        id: (Date.now() + 1).toString(),
        sender: "ai",
        text: replyText,
        timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
        decision: data.decision,
        generated_sql: data.generated_sql,
      };

      setMessages((prev) => [...prev, aiMsg]);
    } catch (err: any) {
      const errorMsg: ChatMessage = {
        id: (Date.now() + 1).toString(),
        sender: "ai",
        text: `Error connecting to backend service: ${err?.message || "Request failed"}. Please ensure backend server is running.`,
        timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
      };
      setMessages((prev) => [...prev, errorMsg]);
    } finally {
      setIsTyping(false);
    }
  };

  return (
    <div className="h-full flex flex-col bg-white">
      {/* Sleek Copilot Top Bar with Stretch & Close Controls */}
      <div className="h-11 border-b border-slate-200 flex items-center justify-between px-3.5 shrink-0 bg-white select-none">
        <div className="flex items-center gap-2">
          <div className="w-6 h-6 rounded-md bg-gradient-to-tr from-[#FF5148] to-orange-400 text-white flex items-center justify-center shadow-2xs">
            <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
            </svg>
          </div>
          <span className="text-xs font-bold text-slate-800 tracking-tight">Copilot</span>
          <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />

          {/* Active Target Slide Badge */}
          <div className="flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-slate-100 text-[10px] font-semibold text-slate-700 border border-slate-200">
            <span className="w-1.5 h-1.5 rounded-full bg-[#FF5148]" />
            <span>Slide {slideNumber || 1}</span>
            <span className="text-[9px] text-slate-400 font-mono">({`slide_${String(slideNumber || 1).padStart(2, "0")}.html`})</span>
          </div>
        </div>

        <div className="flex items-center gap-1 text-slate-400">
          {/* Stretch / Expand Toggle */}
          {onToggleExpand && (
            <button
              type="button"
              onClick={onToggleExpand}
              title={isExpanded ? "Restore standard width" : "Stretch chat width"}
              className="p-1.5 rounded-lg hover:text-slate-700 hover:bg-slate-100 transition-colors cursor-pointer"
            >
              {isExpanded ? (
                /* Collapse / Narrow width icon */
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                </svg>
              ) : (
                /* Stretch / Widen icon */
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
                </svg>
              )}
            </button>
          )}

          {/* Close Panel Button */}
          {onClose && (
            <button
              type="button"
              onClick={onClose}
              title="Close chat panel"
              className="p-1.5 rounded-lg hover:text-slate-700 hover:bg-slate-100 transition-colors cursor-pointer"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          )}
        </div>
      </div>

      {/* Messages Scroll Area */}
      <div className="flex-1 p-4 overflow-y-auto space-y-4 text-xs">
        {loadingHistory ? (
          <div className="flex items-center justify-center h-24 text-slate-400 text-xs">
            <svg className="w-4 h-4 animate-spin mr-2 text-[#FF5148]" fill="none" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z" />
            </svg>
            Loading conversation history...
          </div>
        ) : (
          messages.map((msg) => {
            const isAi = msg.sender === "ai";
            return (
              <div
                key={msg.id}
                className={`flex gap-2.5 ${isAi ? "items-start" : "items-end justify-end"}`}
              >
                {isAi && (
                  <div className="w-6 h-6 rounded-lg bg-orange-100 text-[#FF5148] font-bold text-[10px] flex items-center justify-center shrink-0 mt-0.5 shadow-2xs">
                    AI
                  </div>
                )}
                <div
                  className={`max-w-[85%] p-3.5 rounded-2xl leading-relaxed shadow-xs ${
                    isAi
                      ? "bg-slate-50 text-slate-800 border border-slate-200/80 rounded-tl-xs"
                      : "bg-[#FF5148] text-white rounded-br-xs font-medium"
                  }`}
                >
                  {isAi ? (
                    <div className="text-xs text-slate-800 leading-relaxed space-y-2">
                      <ReactMarkdown
                        remarkPlugins={[remarkGfm]}
                        components={{
                          p: ({ children }) => <p className="mb-2 last:mb-0 leading-relaxed">{children}</p>,
                          ul: ({ children }) => <ul className="list-disc pl-4 mb-2 space-y-1">{children}</ul>,
                          ol: ({ children }) => <ol className="list-decimal pl-4 mb-2 space-y-1">{children}</ol>,
                          li: ({ children }) => <li className="leading-relaxed">{children}</li>,
                          strong: ({ children }) => <strong className="font-semibold text-slate-900">{children}</strong>,
                          em: ({ children }) => <em className="italic text-slate-700">{children}</em>,
                          code: ({ className, children, ...props }: any) => {
                            const isCodeBlock = Boolean(className);
                            if (isCodeBlock) {
                              return (
                                <pre className="p-2.5 my-2 rounded-lg bg-slate-900 text-slate-100 font-mono text-[11px] overflow-x-auto">
                                  <code className={className} {...props}>
                                    {children}
                                  </code>
                                </pre>
                              );
                            }
                            return (
                              <code className="px-1.5 py-0.5 rounded bg-slate-200/80 text-[#FF5148] font-mono text-[11px]" {...props}>
                                {children}
                              </code>
                            );
                          },
                          table: ({ children }) => (
                            <div className="my-2 overflow-x-auto rounded-lg border border-slate-200">
                              <table className="min-w-full divide-y divide-slate-200 text-left text-[11px]">{children}</table>
                            </div>
                          ),
                          thead: ({ children }) => <thead className="bg-slate-100/90 font-semibold text-slate-700">{children}</thead>,
                          th: ({ children }) => <th className="px-2.5 py-1.5">{children}</th>,
                          td: ({ children }) => <td className="px-2.5 py-1.5 border-t border-slate-100">{children}</td>,
                          blockquote: ({ children }) => (
                            <blockquote className="border-l-2 border-[#FF5148] pl-2.5 italic text-slate-600 my-1.5">
                              {children}
                            </blockquote>
                          ),
                          a: ({ href, children }) => (
                            <a
                              href={href}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="text-[#FF5148] underline hover:text-orange-600 transition-colors"
                            >
                              {children}
                            </a>
                          ),
                        }}
                      >
                        {msg.text}
                      </ReactMarkdown>
                    </div>
                  ) : (
                    <div className="whitespace-pre-wrap leading-relaxed">{msg.text}</div>
                  )}
                  <span
                    className={`text-[9px] block mt-1.5 ${
                      isAi ? "text-slate-400" : "text-white/70 text-right"
                    }`}
                  >
                    {msg.timestamp}
                  </span>
                </div>
              </div>
            );
          })
        )}

        {isTyping && (
          <div className="flex items-center gap-2 text-slate-500 text-xs pl-8">
            <span className="inline-flex gap-1">
              <span className="w-1.5 h-1.5 bg-[#FF5148] rounded-full animate-bounce" style={{ animationDelay: "0ms" }} />
              <span className="w-1.5 h-1.5 bg-[#FF5148] rounded-full animate-bounce" style={{ animationDelay: "150ms" }} />
              <span className="w-1.5 h-1.5 bg-[#FF5148] rounded-full animate-bounce" style={{ animationDelay: "300ms" }} />
            </span>
            <span className="text-[11px] font-medium">Copilot is analyzing data...</span>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Target Slide Indicator Bar */}
      <div className="px-3.5 py-1.5 bg-slate-50 border-t border-slate-200 flex items-center justify-between text-[11px] text-slate-500">
        <div className="flex items-center gap-1.5">
          <span className="inline-block w-2 h-2 rounded-full bg-[#FF5148]" />
          <span className="font-semibold text-slate-700">Targeting: Slide {slideNumber || 1}</span>
          <span className="text-[10px] text-slate-400 font-mono">({`slide_${String(slideNumber || 1).padStart(2, "0")}.html`})</span>
        </div>
        {totalSlides && totalSlides > 1 && (
          <span className="text-[10px] text-slate-400">
            Slide {slideNumber || 1} of {totalSlides}
          </span>
        )}
      </div>

      {/* Input Form */}
      <div className="p-3 border-t border-slate-100 bg-white">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            handleSendMessage();
          }}
          className="flex items-center gap-2"
        >
          <input
            type="text"
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            disabled={isTyping}
            placeholder="Ask questions or command presentation edits..."
            className="flex-1 px-3.5 py-2.5 text-xs rounded-xl border border-slate-200 focus:outline-none focus:ring-2 focus:ring-[#FF5148]/30 focus:border-[#FF5148] text-slate-900 disabled:bg-slate-50 transition-all shadow-2xs"
          />
          <button
            type="submit"
            disabled={!inputValue.trim() || isTyping}
            className="w-9 h-9 rounded-xl bg-[#FF5148] hover:bg-[#e64037] text-white flex items-center justify-center transition-all disabled:opacity-40 disabled:cursor-not-allowed shadow-sm shrink-0 cursor-pointer hover:scale-105 active:scale-95"
            title="Send query"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14 5l7 7m0 0l-7 7m7-7H3" />
            </svg>
          </button>
        </form>
      </div>
    </div>
  );
}
