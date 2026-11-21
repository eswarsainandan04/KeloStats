"use client";

import React, { useState, useEffect, useRef } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { API_BASE_URL } from "@/lib/config";
import { fetchWithAuth, getStoredUserId } from "@/lib/api";

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
  collectionId?: string;
  collectionDisplayName?: string;
  source?: "database" | "documents";
  slideNumber?: number;
  totalSlides?: number;
  onSelectSlide?: (slideNum: number) => void;
  onSlideRefreshRequired?: (targetSlideNumber?: number) => void;
  onClose?: () => void;
  isExpanded?: boolean;
  onToggleExpand?: () => void;
}

export default function ChatInterface({
  projectId,
  userId,
  databaseId,
  databaseDisplayName,
  collectionId,
  collectionDisplayName,
  source,
  slideNumber,
  totalSlides,
  onSelectSlide,
  onSlideRefreshRequired,
  onClose,
  isExpanded,
  onToggleExpand,
}: ChatInterfaceProps) {
  const [resolvedDbId, setResolvedDbId] = useState<string>(databaseId || "");
  const [resolvedCollectionId, setResolvedCollectionId] = useState<string>(collectionId || "");
  const [dbDisplayName, setDbDisplayName] = useState<string>(databaseDisplayName || "");
  const [colDisplayName, setColDisplayName] = useState<string>(collectionDisplayName || "");

  // Strictly "database" or "documents" — no more "auto"
  const [currentSource, setCurrentSource] = useState<"database" | "documents">(
    source === "documents" || (!databaseId && collectionId) ? "documents" : "database"
  );
  const [activeSourceTab, setActiveSourceTab] = useState<"databases" | "documents">(
    source === "documents" || (!databaseId && collectionId) ? "documents" : "databases"
  );

  const [availableDbs, setAvailableDbs] = useState<any[]>([]);
  const [availableCollections, setAvailableCollections] = useState<any[]>([]);
  const [loadingSources, setLoadingSources] = useState(false);

  const [isSourceModalOpen, setIsSourceModalOpen] = useState(false);
  const [isUpdatingSource, setIsUpdatingSource] = useState(false);

  // Response / Request Mode: "agent" | "ask" (VS Code Copilot / Perplexity style)
  const [requestMode, setRequestMode] = useState<"ask" | "agent">("agent");
  const [isModeModalOpen, setIsModeModalOpen] = useState(false);
  const [isUpdatingMode, setIsUpdatingMode] = useState(false);

  useEffect(() => {
    setResolvedDbId(databaseId || "");
  }, [databaseId]);

  useEffect(() => {
    setResolvedCollectionId(collectionId || "");
  }, [collectionId]);

  useEffect(() => {
    if (collectionDisplayName && collectionDisplayName.trim() && collectionDisplayName.toLowerCase() !== "collection") {
      setColDisplayName(collectionDisplayName.trim());
    }
  }, [collectionDisplayName]);

  useEffect(() => {
    if (source === "documents") {
      setCurrentSource("documents");
      setActiveSourceTab("documents");
    } else if (source === "database") {
      setCurrentSource("database");
      setActiveSourceTab("databases");
    }
  }, [source]);

  const getEffectiveUserId = () => {
    if (userId && userId.trim()) {
      return userId.trim();
    }
    return getStoredUserId() || "";
  };
  const effectiveUserId = getEffectiveUserId();

  // Load user's connected databases and collections for source selector
  useEffect(() => {
    if (!effectiveUserId) return;
    let isMounted = true;
    const fetchSourcesList = async () => {
      setLoadingSources(true);
      try {
        const [dbRes, colRes] = await Promise.all([
          fetchWithAuth(`${API_BASE_URL}/api/databases/database_info?user_id=${effectiveUserId}`),
          fetchWithAuth(`${API_BASE_URL}/api/documents/collections?user_id=${effectiveUserId}`)
        ]);
        if (dbRes.ok && isMounted) {
          const dbData = await dbRes.json();
          setAvailableDbs(Array.isArray(dbData.databases) ? dbData.databases : (Array.isArray(dbData) ? dbData : []));
        }
        if (colRes.ok && isMounted) {
          const colData = await colRes.json();
          setAvailableCollections(Array.isArray(colData.collections) ? colData.collections : []);
        }
      } catch (err) {
        console.error("Failed to load databases and collections for source selector:", err);
      } finally {
        if (isMounted) setLoadingSources(false);
      }
    };
    fetchSourcesList();
    return () => {
      isMounted = false;
    };
  }, [effectiveUserId]);

  // Select a Database -> updates state, saves database_id and erases collection_id in DB
  const handleSelectDatabase = async (db: any) => {
    setIsSourceModalOpen(false);
    const newDbId = db.db_id;
    const newDbName = db.display_name || db.database_name || db.service_name || "Database";

    setResolvedDbId(newDbId);
    setDbDisplayName(newDbName);
    // Erase collection
    setResolvedCollectionId("");
    setColDisplayName("");
    setCurrentSource("database");

    if (projectId) {
      try {
        setIsUpdatingSource(true);
        await fetchWithAuth(`${API_BASE_URL}/api/workspace/update_source`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            project_id: projectId,
            user_id: effectiveUserId,
            source: "database",
            database_id: newDbId,
            collection_id: null,
          }),
        });
      } catch (err) {
        console.error("Failed to update workspace to database source:", err);
      } finally {
        setIsUpdatingSource(false);
      }
    }
  };

  // Select a Document Collection -> updates state, saves collection_id and erases database_id in DB
  const handleSelectCollection = async (col: any) => {
    setIsSourceModalOpen(false);
    const newColId = col.collection_id;
    const newColName = col.display_name || "Collection";

    setResolvedCollectionId(newColId);
    setColDisplayName(newColName);
    // Erase database
    setResolvedDbId("");
    setDbDisplayName("");
    setCurrentSource("documents");

    if (projectId) {
      try {
        setIsUpdatingSource(true);
        await fetchWithAuth(`${API_BASE_URL}/api/workspace/update_source`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            project_id: projectId,
            user_id: effectiveUserId,
            source: "documents",
            database_id: null,
            collection_id: newColId,
          }),
        });
      } catch (err) {
        console.error("Failed to update workspace to documents source:", err);
      } finally {
        setIsUpdatingSource(false);
      }
    }
  };

  // Select Response/Request Mode ("agent" | "ask") -> updates state & saves to workspace table
  const handleSelectMode = async (mode: "ask" | "agent") => {
    setIsModeModalOpen(false);
    setRequestMode(mode);

    if (projectId) {
      try {
        setIsUpdatingMode(true);
        await fetchWithAuth(`${API_BASE_URL}/api/workspace/update_request_mode`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            project_id: projectId,
            user_id: effectiveUserId,
            request_mode: mode,
          }),
        });
      } catch (err) {
        console.error("Failed to update workspace mode:", err);
      } finally {
        setIsUpdatingMode(false);
      }
    }
  };

  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [loadingHistory, setLoadingHistory] = useState(false);
  const [inputValue, setInputValue] = useState("");
  const [isTyping, setIsTyping] = useState(false);

  // Dynamically resolve workspace source IDs and display names
  useEffect(() => {
    if (databaseDisplayName && databaseDisplayName.trim() && databaseDisplayName.toLowerCase() !== "database") {
      setDbDisplayName(databaseDisplayName.trim());
    }

    if (!effectiveUserId) return;

    let isMounted = true;
    const resolveSourceMetadata = async () => {
      let targetDbId = (databaseId || "").trim();
      let targetColId = (collectionId || "").trim();
      let resolvedDbName =
        databaseDisplayName && databaseDisplayName.trim() && databaseDisplayName.trim().toLowerCase() !== "database"
          ? databaseDisplayName.trim()
          : "";
      let resolvedColName =
        collectionDisplayName && collectionDisplayName.trim() && collectionDisplayName.trim().toLowerCase() !== "collection"
          ? collectionDisplayName.trim()
          : "";

      try {
        // 1. Check workspace projects list for authoritative database_id, collection_id, and display names
        if (projectId && projectId !== "project_default") {
          const wsRes = await fetchWithAuth(`${API_BASE_URL}/api/workspace/list?user_id=${effectiveUserId}`);
          if (wsRes.ok && isMounted) {
            const wsData = await wsRes.json();
            const wsList = wsData.workspaces || [];
            const matchedWs = wsList.find((w: any) => w.project_id === projectId);
            if (matchedWs) {
              targetDbId = (matchedWs.database_id || "").trim();
              targetColId = (matchedWs.collection_id || "").trim();
              setResolvedDbId(targetDbId);
              setResolvedCollectionId(targetColId);

              const wsDbName = matchedWs.database_display_name || matchedWs.database_name;
              if (wsDbName && String(wsDbName).trim()) {
                resolvedDbName = String(wsDbName).trim();
                setDbDisplayName(resolvedDbName);
              }

              const wsColName = matchedWs.collection_display_name;
              if (wsColName && String(wsColName).trim()) {
                resolvedColName = String(wsColName).trim();
                setColDisplayName(resolvedColName);
              }

              const wsMode = (matchedWs.response_mode || matchedWs.request_mode || "").toLowerCase().trim();
              if (wsMode === "ask" || wsMode === "agent") {
                setRequestMode(wsMode as "ask" | "agent");
              }

              if (matchedWs.source === "documents" || (!targetDbId && targetColId)) {
                setCurrentSource("documents");
                setActiveSourceTab("documents");
              } else {
                setCurrentSource("database");
                setActiveSourceTab("databases");
              }
            }
          }
        }

        // 2. Fallback: look up matching database display name ONLY if a database is attached
        if (targetDbId && !resolvedDbName && isMounted) {
          const dbRes = await fetchWithAuth(`${API_BASE_URL}/api/databases/database_info?user_id=${effectiveUserId}`);
          if (dbRes.ok && isMounted) {
            const dbData = await dbRes.json();
            const dbList = Array.isArray(dbData.databases) ? dbData.databases : (Array.isArray(dbData) ? dbData : []);
            const matched = dbList.find((d: any) => d.db_id === targetDbId);
            if (matched) {
              const name = matched.display_name || matched.database_name || matched.service_name;
              if (name) {
                setDbDisplayName(String(name).trim());
              }
            }
          }
        }

        // 3. Fallback: look up matching collection display name ONLY if a collection is attached
        if (targetColId && !resolvedColName && isMounted) {
          const colRes = await fetchWithAuth(`${API_BASE_URL}/api/documents/collections?user_id=${effectiveUserId}`);
          if (colRes.ok && isMounted) {
            const colData = await colRes.json();
            const colList = Array.isArray(colData.collections) ? colData.collections : [];
            const matched = colList.find((c: any) => c.collection_id === targetColId);
            if (matched?.display_name) {
              setColDisplayName(String(matched.display_name).trim());
            }
          }
        }
      } catch (err) {
        console.warn("Could not load workspace source metadata:", err);
      }
    };

    resolveSourceMetadata();
    return () => {
      isMounted = false;
    };
  }, [databaseDisplayName, collectionDisplayName, effectiveUserId, databaseId, collectionId, projectId]);
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
        const res = await fetchWithAuth(`${API_BASE_URL}/api/workspace/chat/${projectId}`);
        if (res.ok) {
          const data = await res.json();
          const loadedMessages: ChatMessage[] = (data.messages || []).map((m: any) => {
            let msgText = m.text || "";
            // Clean up any raw slide markup stored in history so it doesn't clutter chat
            if (msgText.includes("<svg")) {
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
    const targetFilename = `slide_${String(targetSlideNumber).padStart(2, "0")}.svg`;

    try {
      const response = await fetchWithAuth(`${API_BASE_URL}/api/workflow/query`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          user_query: query,
          database_id: currentSource === "database" ? (resolvedDbId || undefined) : undefined,
          collection_id: currentSource === "documents" ? (resolvedCollectionId || undefined) : undefined,
          project_id: projectId || undefined,
          user_id: effectiveUserId || undefined,
          source: currentSource,
          request_mode: requestMode,
          slide_number: targetSlideNumber,
          slide_filename: targetFilename,
        }),
      });

      const data = await response.json();

      let replyText = "";
      if (response.ok) {
        if (data.decision === "agent") {
          const generatedSlideNum = data.slide_number || targetSlideNumber;
          const generatedFilename = data.slide_filename || `slide_${String(generatedSlideNum).padStart(2, "0")}.svg`;
          replyText = data.output && !data.output.includes("<svg")
            ? data.output
            : `✨ I've designed Slide ${generatedSlideNum} (${generatedFilename}) based on your data and updated your presentation canvas.`;
          if (onSlideRefreshRequired) {
            onSlideRefreshRequired(generatedSlideNum);
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
        <div className="flex items-center gap-2 overflow-hidden">
          <div className="w-6 h-6 rounded-md bg-gradient-to-tr from-[#FF5148] to-orange-400 text-white flex items-center justify-center shadow-2xs shrink-0">
            <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
            </svg>
          </div>
          <span className="text-xs font-bold text-slate-800 tracking-tight shrink-0">Copilot</span>
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
            placeholder={
              requestMode === "ask"
                ? (currentSource === "database"
                    ? (resolvedDbId ? `Ask questions about ${dbDisplayName || "database"}...` : "Select a database or ask a question...")
                    : (resolvedCollectionId ? `Ask questions from ${colDisplayName || "documents"}...` : "Select documents or ask a question..."))
                : (currentSource === "database"
                    ? (resolvedDbId ? `Describe slide edits or ask agent to design from ${dbDisplayName || "database"}...` : "Select a database or describe slide changes...")
                    : (resolvedCollectionId ? `Describe slide edits or ask agent to design from ${colDisplayName || "documents"}...` : "Select documents or describe slide changes..."))
            }
            className="w-full bg-transparent resize-none border-0 p-1 text-xs text-slate-800 placeholder:text-slate-400 focus:outline-none focus:ring-0 leading-5 custom-chat-scrollbar"
            style={{ maxHeight: "96px" }}
          />

          {/* Bottom Controls inside composer */}
          <div className="flex items-center justify-between pt-1 select-none">
            {/* Badges Container */}
            <div className="flex items-center gap-1.5 flex-wrap">
              {/* Database Badge in input chat field */}
              {currentSource === "database" && resolvedDbId && (
                <div
                  className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-md bg-white border border-slate-200/90 text-[10px] font-semibold text-slate-700 shadow-2xs shrink-0 cursor-default max-w-[160px] truncate"
                  title={dbDisplayName || "Database"}
                >
                  <img
                    src="/database.png"
                    alt="Database"
                    className="w-3.5 h-3.5 object-contain shrink-0"
                  />
                  <span className="tracking-tight text-[10px] font-semibold truncate">
                    {dbDisplayName || "Database"}
                  </span>
                </div>
              )}

              {/* Documents Badge in input chat field */}
              {currentSource === "documents" && resolvedCollectionId && (
                <div
                  className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-md bg-white border border-slate-200/90 text-[10px] font-semibold text-slate-700 shadow-2xs shrink-0 cursor-default max-w-[160px] truncate"
                  title={colDisplayName || "Collection"}
                >
                  <img
                    src="/collection.png"
                    alt="Collection"
                    className="w-3.5 h-3.5 object-contain shrink-0"
                  />
                  <span className="tracking-tight text-[10px] font-semibold truncate">
                    {colDisplayName || "Collection"}
                  </span>
                </div>
              )}

              {/* Small Slide Indicator Badge with ppt.png */}
              <div
                className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-md bg-white border border-slate-200/90 text-[10px] font-medium text-slate-600 shadow-2xs hover:border-slate-300 transition-colors cursor-default shrink-0"
                title={`Editing Slide ${slideNumber || 1} (${totalSlides ? `Slide ${slideNumber || 1} of ${totalSlides}` : `slide_${String(slideNumber || 1).padStart(2, "0")}.svg`})`}
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

            {/* Right Action Buttons: Mode Selector, Source Picker & Send Button */}
            <div className="flex items-center gap-1.5 shrink-0">
              {/* Mode Switcher Button with Drop-up Popover (Ask / Agent) - like VS Code & Perplexity */}
              <div className="relative">
                <button
                  type="button"
                  onClick={() => {
                    setIsModeModalOpen(!isModeModalOpen);
                    setIsSourceModalOpen(false);
                  }}
                  className={`h-7 px-2 rounded-xl flex items-center gap-1.5 border text-xs font-semibold transition-all cursor-pointer shrink-0 select-none ${
                    isModeModalOpen
                      ? "bg-slate-100 border-slate-300 text-slate-900 scale-105"
                      : "bg-white hover:bg-slate-50 border-slate-200/90 text-slate-700 shadow-2xs hover:scale-105 active:scale-95"
                  }`}
                  title="Select Mode: Ask or Agent"
                >
                  {requestMode === "agent" ? (
                    <>
                      <span className="text-[#FF5148] text-xs">✨</span>
                      <span className="text-[11px] font-bold text-slate-800 tracking-tight">Agent</span>
                    </>
                  ) : (
                    <>
                      <span className="text-blue-500 text-xs">💬</span>
                      <span className="text-[11px] font-bold text-slate-800 tracking-tight">Ask</span>
                    </>
                  )}
                  <svg
                    className={`w-3 h-3 text-slate-400 transition-transform ${isModeModalOpen ? "rotate-180" : ""}`}
                    fill="none"
                    stroke="currentColor"
                    viewBox="0 0 24 24"
                  >
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                  </svg>
                </button>

                {/* Drop-up Popover Menu for Mode Selection */}
                {isModeModalOpen && (
                  <>
                    <div
                      className="fixed inset-0 z-40"
                      onClick={() => setIsModeModalOpen(false)}
                    />
                    <div className="absolute bottom-full right-0 mb-2 z-50 w-60 bg-white rounded-2xl shadow-2xl border border-slate-200/90 p-1.5 animate-in fade-in zoom-in-95 duration-150 select-none">
                      <div className="px-2 pb-1.5 pt-1 text-[10px] font-bold text-slate-400 uppercase tracking-wider">
                        Copilot Mode
                      </div>

                      <div className="space-y-1">
                        {/* Agent Mode Option */}
                        <button
                          type="button"
                          onClick={() => handleSelectMode("agent")}
                          className={`w-full p-2 rounded-xl text-left flex items-center justify-between gap-2.5 transition-all cursor-pointer ${
                            requestMode === "agent"
                              ? "bg-orange-50/70 border border-orange-200/80 text-slate-900"
                              : "hover:bg-slate-50 text-slate-700 border border-transparent"
                          }`}
                        >
                          <div className="flex items-center gap-2.5 min-w-0">
                            <div className="w-6 h-6 rounded-lg bg-orange-100 flex items-center justify-center text-xs shrink-0">
                              ✨
                            </div>
                            <div className="min-w-0">
                              <div className="text-xs font-bold text-slate-800 flex items-center gap-1.5">
                                <span>Agent</span>
                                <span className="text-[9px] px-1.5 py-0.2 rounded bg-orange-100 text-[#FF5148] font-bold uppercase">
                                  Autonomous
                                </span>
                              </div>
                              <div className="text-[10px] text-slate-400 leading-tight">
                                Autonomous slide edits & planning
                              </div>
                            </div>
                          </div>
                          {requestMode === "agent" && (
                            <svg className="w-4 h-4 text-[#FF5148] shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 13l4 4L19 7" />
                            </svg>
                          )}
                        </button>

                        {/* Ask Mode Option */}
                        <button
                          type="button"
                          onClick={() => handleSelectMode("ask")}
                          className={`w-full p-2 rounded-xl text-left flex items-center justify-between gap-2.5 transition-all cursor-pointer ${
                            requestMode === "ask"
                              ? "bg-blue-50/70 border border-blue-200/80 text-slate-900"
                              : "hover:bg-slate-50 text-slate-700 border border-transparent"
                          }`}
                        >
                          <div className="flex items-center gap-2.5 min-w-0">
                            <div className="w-6 h-6 rounded-lg bg-blue-100 flex items-center justify-center text-xs shrink-0">
                              💬
                            </div>
                            <div className="min-w-0">
                              <div className="text-xs font-bold text-slate-800 flex items-center gap-1.5">
                                <span>Ask</span>
                                <span className="text-[9px] px-1.5 py-0.2 rounded bg-blue-100 text-blue-600 font-bold uppercase">
                                  Chat
                                </span>
                              </div>
                              <div className="text-[10px] text-slate-400 leading-tight">
                                Q&A & conversational answers
                              </div>
                            </div>
                          </div>
                          {requestMode === "ask" && (
                            <svg className="w-4 h-4 text-blue-600 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 13l4 4L19 7" />
                            </svg>
                          )}
                        </button>
                      </div>
                    </div>
                  </>
                )}
              </div>

              {/* Source Switcher Button with Drop-up Tabbed Popover */}
              <div className="relative">
                <button
                  type="button"
                  onClick={() => {
                    setIsSourceModalOpen(!isSourceModalOpen);
                    setIsModeModalOpen(false);
                  }}
                  className={`w-7 h-7 rounded-xl flex items-center justify-center border transition-all cursor-pointer shrink-0 ${
                    isSourceModalOpen
                      ? "bg-slate-100 border-slate-300 text-slate-800 scale-105"
                      : "bg-white hover:bg-slate-100 border-slate-200/90 text-slate-600 shadow-2xs hover:scale-105 active:scale-95"
                  }`}
                  title="Select Data Source"
                >
                  <img
                    src="/source.png"
                    alt="Source"
                    className="w-3.5 h-3.5 object-contain shrink-0"
                  />
                </button>

                {/* Drop-up Tabbed Popup Menu anchored at source button */}
                {isSourceModalOpen && (
                  <>
                    {/* Invisible backdrop to dismiss when clicking outside */}
                    <div
                      className="fixed inset-0 z-40"
                      onClick={() => setIsSourceModalOpen(false)}
                    />

                    <div className="absolute bottom-full right-0 mb-2 z-50 w-72 bg-white rounded-2xl shadow-2xl border border-slate-200/90 p-2.5 animate-in fade-in zoom-in-95 duration-150 select-none">
                      {/* Header Title */}
                      <div className="px-1.5 pb-2 text-[10px] font-bold text-slate-400 uppercase tracking-wider">
                        Select Data Source
                      </div>

                      {/* Tab Switcher: [Databases | Documents] */}
                      <div className="flex items-center p-0.5 bg-slate-100 rounded-xl mb-2.5">
                        <button
                          type="button"
                          onClick={() => setActiveSourceTab("databases")}
                          className={`flex-1 py-1.5 text-xs font-bold rounded-lg transition-all flex items-center justify-center gap-1.5 cursor-pointer ${
                            activeSourceTab === "databases"
                              ? "bg-white text-slate-900 shadow-xs"
                              : "text-slate-500 hover:text-slate-800"
                          }`}
                        >
                          <img src="/database.png" alt="" className="w-3.5 h-3.5 object-contain" />
                          <span>Databases</span>
                        </button>
                        <button
                          type="button"
                          onClick={() => setActiveSourceTab("documents")}
                          className={`flex-1 py-1.5 text-xs font-bold rounded-lg transition-all flex items-center justify-center gap-1.5 cursor-pointer ${
                            activeSourceTab === "documents"
                              ? "bg-white text-slate-900 shadow-xs"
                              : "text-slate-500 hover:text-slate-800"
                          }`}
                        >
                          <img src="/collection.png" alt="" className="w-3.5 h-3.5 object-contain" />
                          <span>Documents</span>
                        </button>
                      </div>

                      {/* Tab Content List */}
                      <div className="max-h-56 overflow-y-auto space-y-1 pr-0.5 custom-chat-scrollbar">
                        {loadingSources ? (
                          <div className="py-6 text-center text-xs text-slate-400">Loading sources...</div>
                        ) : activeSourceTab === "databases" ? (
                          availableDbs.length === 0 ? (
                            <div className="p-3 text-center rounded-xl bg-slate-50 text-slate-500 text-xs">
                              No databases connected yet.
                            </div>
                          ) : (
                            availableDbs.map((db: any) => {
                              const isSelected = currentSource === "database" && resolvedDbId === db.db_id;
                              const name = db.display_name || db.database_name || db.service_name || "Database";
                              return (
                                <button
                                  key={db.db_id}
                                  type="button"
                                  onClick={() => handleSelectDatabase(db)}
                                  className={`w-full p-2 rounded-xl text-left flex items-center justify-between gap-2 transition-all cursor-pointer ${
                                    isSelected
                                      ? "bg-orange-50/70 border border-orange-200/80 text-slate-900"
                                      : "hover:bg-slate-50 text-slate-700 border border-transparent"
                                  }`}
                                >
                                  <div className="flex items-center gap-2.5 min-w-0">
                                    <img src="/database.png" alt="" className="w-5 h-5 object-contain shrink-0" />
                                    <div className="min-w-0">
                                      <div className="text-xs font-bold truncate text-slate-800">{name}</div>
                                      <div className="text-[10px] text-slate-400 truncate uppercase font-medium">
                                        {db.database_type || "SQL"}
                                      </div>
                                    </div>
                                  </div>
                                  {isSelected && (
                                    <svg className="w-4 h-4 text-[#FF5148] shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 13l4 4L19 7" />
                                    </svg>
                                  )}
                                </button>
                              );
                            })
                          )
                        ) : (
                          availableCollections.length === 0 ? (
                            <div className="p-3 text-center rounded-xl bg-slate-50 text-slate-500 text-xs">
                              No document collections available.
                            </div>
                          ) : (
                            availableCollections.map((col: any) => {
                              const isSelected = currentSource === "documents" && resolvedCollectionId === col.collection_id;
                              const name = col.display_name || "Collection";
                              const count = col.total_files || (col.documents?.length || 0);
                              return (
                                <button
                                  key={col.collection_id}
                                  type="button"
                                  onClick={() => handleSelectCollection(col)}
                                  className={`w-full p-2 rounded-xl text-left flex items-center justify-between gap-2 transition-all cursor-pointer ${
                                    isSelected
                                      ? "bg-orange-50/70 border border-orange-200/80 text-slate-900"
                                      : "hover:bg-slate-50 text-slate-700 border border-transparent"
                                  }`}
                                >
                                  <div className="flex items-center gap-2.5 min-w-0">
                                    <img src="/collection.png" alt="" className="w-5 h-5 object-contain shrink-0" />
                                    <div className="min-w-0">
                                      <div className="text-xs font-bold truncate text-slate-800">{name}</div>
                                      <div className="text-[10px] text-slate-400 truncate font-medium">
                                        {count} {count === 1 ? "document" : "documents"}
                                      </div>
                                    </div>
                                  </div>
                                  {isSelected && (
                                    <svg className="w-4 h-4 text-[#FF5148] shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 13l4 4L19 7" />
                                    </svg>
                                  )}
                                </button>
                              );
                            })
                          )
                        )}
                      </div>
                    </div>
                  </>
                )}
              </div>

              {/* Send Message Button */}
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
    </div>
  );
}
