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
  databaseDisplayName?: string;
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
  databaseDisplayName,
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
  const [dbDisplayName, setDbDisplayName] = useState<string>(databaseDisplayName || "");

  // Dynamically resolve real database display name
  useEffect(() => {
    if (databaseDisplayName && databaseDisplayName.trim() && databaseDisplayName.toLowerCase() !== "database") {
      setDbDisplayName(databaseDisplayName.trim());
      return;
    }

    if (!userId) return;

    let isMounted = true;
    const resolveDatabaseName = async () => {
      try {
        // 1. Check workspace projects list for this project's database_display_name
        if (projectId && projectId !== "project_default") {
          const wsRes = await fetch(`${API_BASE_URL}/api/workspace/list?user_id=${userId}`);
          if (wsRes.ok) {
            const wsData = await wsRes.json();
            const wsList = wsData.workspaces || [];
            const matchedWs = wsList.find((w: any) => w.project_id === projectId);
            if (matchedWs && isMounted) {
              const name = matchedWs.database_display_name || matchedWs.database_name;
              if (name) {
                setDbDisplayName(name);
                return;
              }
            }
          }
        }

        // 2. Fallback: inspect user's connected database list
        const dbRes = await fetch(`${API_BASE_URL}/api/databases/database_info?user_id=${userId}`);
        if (dbRes.ok) {
          const dbData = await dbRes.json();
          const dbList = Array.isArray(dbData.databases) ? dbData.databases : (Array.isArray(dbData) ? dbData : []);
          let matched = databaseId ? dbList.find((d: any) => d.db_id === databaseId) : null;
          if (!matched && dbList.length > 0) {
            matched = dbList[0];
          }
          if (matched && isMounted) {
            const name = matched.display_name || matched.database_name || matched.service_name;
            if (name) {
              setDbDisplayName(name);
            }
          }
        }
      } catch (err) {
        console.warn("Could not load database display name:", err);
      }
    };

    resolveDatabaseName();
    return () => {
      isMounted = false;
    };
  }, [databaseDisplayName, userId, databaseId, projectId]);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Auto-resize textarea up to 4 lines (~96px) and enable sleek scrollbar beyond that
  useEffect(() => {
    const textarea = textareaRef.current;
    if (!textarea) return;
    textarea.style.height = "auto";
    const maxHeight = 96; // ~4 lines @ 20px line-height + padding
    const nextHeight = Math.min(textarea.scrollHeight, maxHeight);
    textarea.style.height = `${nextHeight}px`;
    textarea.style.overflowY = textarea.scrollHeight > maxHeight ? "auto" : "hidden";
  }, [inputValue]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter") {
      if (e.shiftKey) {
        // Shift + Enter: allow native newline up to 4 lines
        return;
      }
      // Enter without Shift: submit
      e.preventDefault();
      if (inputValue.trim() && !isTyping) {
        handleSendMessage();
      }
    }
  };

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
        replyText = "Sorry, I cant help you rght now";
      }

      // Safeguard against any technical exception strings leaking into chat
      if (
        replyText.includes("LLM API Error") ||
        replyText.includes("Rate limit") ||
        replyText.includes("tokens per minute") ||
        replyText.includes("execution failed")
      ) {
        replyText = "Sorry, I cant help you rght now";
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
        text: "Sorry, I cant help you rght now",
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
      <div className="flex-1 p-4 overflow-y-auto space-y-4 text-xs custom-chat-scrollbar">
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

      {/* Modern Executive Composer */}
      <div className="p-3 bg-white border-t border-slate-200/80">
        <div
          className={`rounded-2xl border transition-all duration-200 bg-slate-50/60 hover:bg-slate-50/80 focus-within:bg-white focus-within:border-slate-300 focus-within:ring-2 focus-within:ring-slate-900/5 shadow-2xs p-2.5 flex flex-col gap-1.5 ${
            isTyping ? "opacity-60 pointer-events-none" : "border-slate-200"
          }`}
        >
          <textarea
            ref={textareaRef}
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={isTyping}
            rows={1}
            placeholder="Ask questions or command presentation edits..."
            className="w-full bg-transparent resize-none border-0 p-1 text-xs text-slate-800 placeholder:text-slate-400 focus:outline-none focus:ring-0 leading-5 custom-chat-scrollbar"
            style={{ maxHeight: "96px" }}
          />

          {/* Bottom Controls inside composer */}
          <div className="flex items-center justify-between pt-1 select-none">
            {/* Badges Container */}
            <div className="flex items-center gap-1.5 flex-wrap">
              {/* Database Indicator Badge with database.png */}
              {dbDisplayName ? (
                <div
                  className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-md bg-white border border-slate-200/90 text-[10px] font-medium text-slate-600 shadow-2xs hover:border-slate-300 transition-colors cursor-default max-w-[160px] truncate"
                  title={`Connected Database: ${dbDisplayName}`}
                >
                  <img
                    src="/database.png"
                    alt="Database"
                    className="w-3.5 h-3.5 object-contain shrink-0"
                  />
                  <span className="tracking-tight text-slate-700 font-semibold text-[10px] truncate">
                    {dbDisplayName}
                  </span>
                </div>
              ) : null}

              {/* Small Slide Indicator Badge with ppt.png */}
              <div
                className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-md bg-white border border-slate-200/90 text-[10px] font-medium text-slate-600 shadow-2xs hover:border-slate-300 transition-colors cursor-default shrink-0"
                title={`Editing Slide ${slideNumber || 1} (${totalSlides ? `Slide ${slideNumber || 1} of ${totalSlides}` : `slide_${String(slideNumber || 1).padStart(2, "0")}.html`})`}
              >
                <img
                  src="/ppt.png"
                  alt="PPT"
                  className="w-3.5 h-3.5 object-contain shrink-0"
                />
                <span className="tracking-tight text-slate-700 font-semibold text-[10px]">
                  Slide {slideNumber || 1}
                </span>
              </div>
            </div>

            <button
              type="button"
              onClick={() => handleSendMessage()}
              disabled={!inputValue.trim() || isTyping}
              className={`w-7 h-7 rounded-xl flex items-center justify-center transition-all duration-150 cursor-pointer shrink-0 ${
                inputValue.trim() && !isTyping
                  ? "bg-[#FF5148] hover:bg-[#e03e35] text-white shadow-xs hover:scale-105 active:scale-95"
                  : "bg-slate-200/80 text-slate-400 cursor-not-allowed opacity-50"
              }`}
              title="Send query (Enter)"
            >
              <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.2} d="M5 12h14M12 5l7 7-7 7" />
              </svg>
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
