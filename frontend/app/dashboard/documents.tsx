"use client";

import React, { useState, useEffect, useRef } from "react";
import { API_BASE_URL } from "@/lib/config";
import { fetchWithAuth } from "@/lib/api";

interface DocumentItem {
  document_id: string;
  file_name: string;
  file_type?: string;
  file_size?: number;
  total_pages?: number;
  chunks_count?: number;
  s3_path?: string;
  created_at?: string;
}

interface CollectionItem {
  collection_id: string;
  display_name: string;
  user_id?: string;
  total_files: number;
  documents: DocumentItem[];
  created_at?: string;
  updated_at?: string;
  status: "processing" | "completed" | "failed";
  errorMessage?: string;
}

export default function DocumentsPage() {
  const [collections, setCollections] = useState<CollectionItem[]>([]);
  const [loading, setLoading] = useState(true);

  // Create Collection Modal states
  const [createModalOpen, setCreateModalOpen] = useState(false);
  const [displayName, setDisplayName] = useState("");
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [dragActive, setDragActive] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  // Collection Details Popup state
  const [activeCollection, setActiveCollection] = useState<CollectionItem | null>(null);
  const [selectedPdf, setSelectedPdf] = useState<DocumentItem | null>(null);

  // Deletion loading states
  const [isDeletingCollection, setIsDeletingCollection] = useState(false);
  const [isDeletingPdf, setIsDeletingPdf] = useState<string | null>(null);
  const [showDeleteCollConfirm, setShowDeleteCollConfirm] = useState(false);

  // Append new PDF states
  const [isAppendingPdf, setIsAppendingPdf] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const appendFileInputRef = useRef<HTMLInputElement>(null);

  // Helper to retrieve current user_id
  const getUserId = (): string => {
    if (typeof window !== "undefined") {
      try {
        const saved = localStorage.getItem("kelostats_user");
        if (saved) {
          const parsed = JSON.parse(saved);
          return parsed.user_id || "76d244ff-0b4f-476f-b306-844948064e56";
        }
      } catch {
        // Fallback
      }
    }
    return "76d244ff-0b4f-476f-b306-844948064e56";
  };

  // Format file sizes
  const formatFileSize = (bytes?: number): string => {
    if (!bytes || bytes <= 0) return "0 KB";
    const k = 1024;
    const sizes = ["B", "KB", "MB", "GB"];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + " " + sizes[i];
  };

  // Format dates
  const formatDate = (isoStr?: string): string => {
    if (!isoStr) return "Just now";
    try {
      const d = new Date(isoStr);
      return d.toLocaleDateString("en-US", {
        month: "short",
        day: "numeric",
        year: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      });
    } catch {
      return isoStr;
    }
  };

  // Fetch collections on mount
  const fetchCollections = async () => {
    setLoading(true);
    const userId = getUserId();
    try {
      const res = await fetchWithAuth(`${API_BASE_URL}/api/documents/collections?user_id=${userId}`);
      if (res.ok) {
        const data = await res.json();
        const loaded: CollectionItem[] = (data.collections || []).map((c: any) => ({
          ...c,
          status: "completed",
        }));
        setCollections(loaded);
      }
    } catch (err) {
      console.error("Error fetching collections:", err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchCollections();
  }, []);

  // Handle Drag & Drop
  const handleDrag = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === "dragenter" || e.type === "dragover") {
      setDragActive(true);
    } else if (e.type === "dragleave") {
      setDragActive(false);
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);
    setFormError(null);

    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      const droppedFiles = Array.from(e.dataTransfer.files);
      const pdfFiles = droppedFiles.filter((f) => f.name.toLowerCase().endsWith(".pdf"));

      if (pdfFiles.length < droppedFiles.length) {
        setFormError("Only .pdf documents are supported for RAG indexing.");
      }

      if (pdfFiles.length > 0) {
        setSelectedFiles((prev) => [...prev, ...pdfFiles]);
      }
    }
  };

  const handleFileInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setFormError(null);
    if (e.target.files && e.target.files.length > 0) {
      const files = Array.from(e.target.files);
      const pdfFiles = files.filter((f) => f.name.toLowerCase().endsWith(".pdf"));

      if (pdfFiles.length < files.length) {
        setFormError("Only .pdf documents are supported.");
      }

      if (pdfFiles.length > 0) {
        setSelectedFiles((prev) => [...prev, ...pdfFiles]);
      }
    }
  };

  const removeSelectedFile = (index: number) => {
    setSelectedFiles((prev) => prev.filter((_, i) => i !== index));
  };

  const openCreateModal = () => {
    setDisplayName("");
    setSelectedFiles([]);
    setFormError(null);
    setCreateModalOpen(true);
  };

  const closeCreateModal = () => {
    setCreateModalOpen(false);
    setDisplayName("");
    setSelectedFiles([]);
    setFormError(null);
  };

  // Submit Upload and initiate Collection Pipeline
  const handleUploadSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const cleanName = displayName.trim();

    if (!cleanName) {
      setFormError("Please enter a collection display name.");
      return;
    }

    if (selectedFiles.length === 0) {
      setFormError("Please attach at least one .pdf document.");
      return;
    }

    const userId = getUserId();
    const tempId = `pool_temp_${Date.now()}`;
    const filesToUpload = [...selectedFiles];

    // Optimistically create collection item with 'processing' status
    const optimisticColl: CollectionItem = {
      collection_id: tempId,
      display_name: cleanName,
      user_id: userId,
      total_files: filesToUpload.length,
      documents: filesToUpload.map((f, i) => ({
        document_id: `doc_temp_${i}`,
        file_name: f.name,
        file_size: f.size,
      })),
      created_at: new Date().toISOString(),
      status: "processing",
    };

    // Prepend new processing folder to UI immediately
    setCollections((prev) => [optimisticColl, ...prev]);

    // Close modal right away so user sees the folder processing below
    closeCreateModal();

    // Prepare multipart FormData
    const formData = new FormData();
    formData.append("user_id", userId);
    formData.append("display_name", cleanName);
    filesToUpload.forEach((file) => {
      formData.append("file", file);
    });

    try {
      const response = await fetchWithAuth(`${API_BASE_URL}/api/documents/upload`, {
        method: "POST",
        body: formData,
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.detail || "Document upload and indexing failed.");
      }

      const result = await response.json();

      // Update card status to 'completed' with real collection_id and documents
      setCollections((prev) =>
        prev.map((c) =>
          c.collection_id === tempId
            ? {
              ...c,
              collection_id: result.collection_id,
              display_name: result.display_name || cleanName,
              total_files: result.total_files || filesToUpload.length,
              documents: result.documents || c.documents,
              status: "completed",
            }
            : c
        )
      );

      // If active collection popup happens to be open for this temp collection, update it
      setActiveCollection((prev) =>
        prev && prev.collection_id === tempId
          ? {
            ...prev,
            collection_id: result.collection_id,
            display_name: result.display_name || cleanName,
            total_files: result.total_files || filesToUpload.length,
            documents: result.documents || prev.documents,
            status: "completed",
          }
          : prev
      );
    } catch (err: any) {
      console.error("Upload error:", err);
      setCollections((prev) =>
        prev.map((c) =>
          c.collection_id === tempId
            ? {
              ...c,
              status: "failed",
              errorMessage: err.message || "Failed to process and index documents.",
            }
            : c
        )
      );
    }
  };

  // Open Collection Details Popup
  const handleOpenCollectionDetails = (coll: CollectionItem) => {
    setActiveCollection(coll);
    setSelectedPdf(coll.documents && coll.documents.length > 0 ? coll.documents[0] : null);
    setShowDeleteCollConfirm(false);
  };

  // Close Collection Details Popup
  const handleCloseCollectionDetails = () => {
    setActiveCollection(null);
    setSelectedPdf(null);
    setShowDeleteCollConfirm(false);
  };

  // Delete Collection
  const handleDeleteCollection = async () => {
    if (!activeCollection) return;
    const collectionId = activeCollection.collection_id;
    setIsDeletingCollection(true);
    const userId = getUserId();

    try {
      const res = await fetchWithAuth(
        `${API_BASE_URL}/api/documents/collections/${collectionId}?user_id=${userId}`,
        { method: "DELETE" }
      );
      if (res.ok) {
        setCollections((prev) => prev.filter((c) => c.collection_id !== collectionId));
        handleCloseCollectionDetails();
      } else {
        const err = await res.json().catch(() => ({}));
        alert(err.detail || "Failed to delete collection.");
      }
    } catch (err) {
      console.error("Delete collection error:", err);
      alert("Error deleting collection.");
    } finally {
      setIsDeletingCollection(false);
      setShowDeleteCollConfirm(false);
    }
  };

  // Delete PDF Document inside Popup
  const handleDeletePdf = async (docId: string) => {
    if (!activeCollection) return;
    setIsDeletingPdf(docId);

    try {
      const res = await fetchWithAuth(
        `${API_BASE_URL}/api/documents/document/${docId}?collection_id=${activeCollection.collection_id}`,
        { method: "DELETE" }
      );

      if (res.ok) {
        const updatedDocs = activeCollection.documents.filter((d) => d.document_id !== docId);

        // Update active collection state
        const updatedActive: CollectionItem = {
          ...activeCollection,
          documents: updatedDocs,
          total_files: updatedDocs.length,
        };
        setActiveCollection(updatedActive);

        // Update selected PDF view
        if (selectedPdf && selectedPdf.document_id === docId) {
          setSelectedPdf(updatedDocs.length > 0 ? updatedDocs[0] : null);
        }

        // Update collections list
        setCollections((prev) =>
          prev.map((c) => (c.collection_id === activeCollection.collection_id ? updatedActive : c))
        );
      } else {
        const err = await res.json().catch(() => ({}));
        alert(err.detail || "Failed to delete document.");
      }
    } catch (err) {
      console.error("Delete PDF error:", err);
      alert("Error deleting document.");
    } finally {
      setIsDeletingPdf(null);
    }
  };

  // Add new PDF(s) to existing collection via POST /api/documents/modify
  const handleAppendPdfFiles = async (e: React.ChangeEvent<HTMLInputElement>) => {
    if (!activeCollection || !e.target.files || e.target.files.length === 0) return;
    const files = Array.from(e.target.files).filter((f) => f.name.toLowerCase().endsWith(".pdf"));
    if (files.length === 0) {
      alert("Please select .pdf files only.");
      return;
    }

    setIsAppendingPdf(true);
    const userId = getUserId();
    const formData = new FormData();
    formData.append("collection_id", activeCollection.collection_id);
    formData.append("user_id", userId);
    files.forEach((file) => {
      formData.append("file", file);
    });

    try {
      const res = await fetchWithAuth(`${API_BASE_URL}/api/documents/modify`, {
        method: "POST",
        body: formData,
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || "Failed to add PDF to collection.");
      }

      const data = await res.json();
      const newDocs: DocumentItem[] = data.added_documents || [];

      // Update active collection in popup
      const updatedDocs = [...(activeCollection.documents || []), ...newDocs];
      const updatedCollection: CollectionItem = {
        ...activeCollection,
        documents: updatedDocs,
        total_files: updatedDocs.length,
      };
      setActiveCollection(updatedCollection);

      // Select the first newly added PDF
      if (newDocs.length > 0) {
        setSelectedPdf(newDocs[0]);
      }

      // Update main dashboard collections list
      setCollections((prev) =>
        prev.map((c) => (c.collection_id === activeCollection.collection_id ? updatedCollection : c))
      );
    } catch (err: any) {
      console.error("Modify collection error:", err);
      alert(err.message || "Failed to add PDF to collection.");
    } finally {
      setIsAppendingPdf(false);
      if (appendFileInputRef.current) {
        appendFileInputRef.current.value = "";
      }
    }
  };

  return (
    <div className="w-full flex-1 min-h-screen bg-[#f8fafc] px-6 sm:px-10 lg:px-12 py-8 space-y-8 animate-in fade-in duration-200">
      {/* Top Header Section matching Presentation Templates */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-6 pb-2 border-b border-slate-100">
        <div>
          <div className="flex items-center gap-2.5">
            <h1 className="text-2xl sm:text-3xl font-extrabold text-slate-900 tracking-tight">
              Upload documents
            </h1>
            <span className="px-2.5 py-0.5 rounded-full text-xs font-bold bg-orange-50 text-[#FF5148] border border-orange-200/80">
              {collections.length} {collections.length === 1 ? "Collection" : "Collections"}
            </span>
          </div>
          <p className="text-sm text-slate-500 mt-1 max-w-2xl">
            Organize documents into vectorized knowledge pools for semantic search and AI presentation grounding.
          </p>
        </div>

        {/* + Create Collection Button */}
        <button
          onClick={openCreateModal}
          className="px-5 py-2.5 rounded-xl bg-[#FF5148] hover:bg-[#e64037] text-white font-bold text-sm shadow-md hover:shadow-lg transition-all flex items-center justify-center gap-2 shrink-0 cursor-pointer active:scale-95"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M12 4v16m8-8H4" />
          </svg>
          <span>Create Collection</span>
        </button>
      </div>

      {/* ========================================================================= */}
      {/* Collections Section                                                      */}
      {/* ========================================================================= */}
      {loading ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-6">
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className="rounded-2xl border border-slate-200 bg-white p-5 aspect-square animate-pulse flex flex-col justify-between items-center">
              <div className="w-full flex justify-between">
                <div className="h-5 w-16 bg-slate-100 rounded-full" />
                <div className="w-2.5 h-2.5 rounded-full bg-slate-100" />
              </div>
              <div className="w-20 h-20 bg-slate-100 rounded-2xl" />
              <div className="w-full space-y-2">
                <div className="h-4 bg-slate-100 rounded mx-auto w-3/4" />
                <div className="h-3 bg-slate-50 rounded mx-auto w-1/2" />
              </div>
            </div>
          ))}
        </div>
      ) : collections.length === 0 ? (
        /* Empty State */
        <div className="p-12 text-center rounded-2xl border-2 border-dashed border-slate-200 bg-white/70">
          <div className="w-16 h-16 mb-4 flex items-center justify-center mx-auto">
            <img
              src="/collection.png"
              alt="No collections"
              className="w-14 h-14 object-contain opacity-50 grayscale hover:grayscale-0 transition-all"
            />
          </div>
          <h3 className="text-lg font-bold text-slate-800">No Document Collections Yet</h3>
          <p className="text-sm text-slate-500 max-w-sm mt-1 mb-6 leading-relaxed mx-auto">
            Create your first collection to upload PDFs, generate vector chunks, and enable multi-document AI querying.
          </p>
          <button
            onClick={openCreateModal}
            className="px-5 py-2.5 rounded-xl text-sm font-bold text-white bg-[#FF5148] hover:bg-[#e64037] shadow-md transition-all cursor-pointer"
          >
            + Create Collection
          </button>
        </div>
      ) : (
        /* Collections Grid matching Databases card layout & aspect-square size */
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-6">
          {collections.map((coll) => {
            const isProcessing = coll.status === "processing";
            const isFailed = coll.status === "failed";
            const fileCount = coll.documents?.length || coll.total_files || 0;

            return (
              <div
                key={coll.collection_id}
                onClick={() => !isProcessing && handleOpenCollectionDetails(coll)}
                className="group relative bg-white border border-slate-200 hover:border-[#FF5148] rounded-2xl p-5 shadow-xs hover:shadow-xl hover:-translate-y-1 transition-all duration-200 cursor-pointer flex flex-col justify-between items-center text-center aspect-square"
              >
                {/* Top: Collection Badge & Status dot */}
                <div className="w-full flex items-center justify-between">
                  <div className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-slate-50 border border-slate-200/80 text-[11px] font-semibold text-slate-700">
                    <span className="w-2 h-2 rounded-full bg-[#FF5148]" />
                    <span>Collection</span>
                  </div>
                  {isProcessing ? (
                    <span className="w-2.5 h-2.5 rounded-full bg-amber-500 animate-ping shadow-xs" title="Processing" />
                  ) : isFailed ? (
                    <span className="w-2.5 h-2.5 rounded-full bg-red-500 shadow-xs" title="Failed" />
                  ) : (
                    <span className="w-2.5 h-2.5 rounded-full bg-emerald-500 shadow-xs" title="Active" />
                  )}
                </div>

                {/* Center: Collection 3D Icon */}
                <div className="w-20 h-20 sm:w-24 sm:h-24 p-1 my-auto flex items-center justify-center group-hover:scale-110 transition-transform duration-200 relative">
                  <img
                    src="/collection.png"
                    alt={coll.display_name}
                    className="w-full h-full object-contain pointer-events-none drop-shadow-sm"
                  />

                  {/* Processing Overlay Icon */}
                  {isProcessing && (
                    <div className="absolute inset-0 flex flex-col items-center justify-center bg-white/70 backdrop-blur-[1px] rounded-2xl">
                      <svg className="w-8 h-8 animate-spin text-[#FF5148]" fill="none" viewBox="0 0 24 24">
                        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
                      </svg>
                    </div>
                  )}

                  {/* Failed Badge */}
                  {isFailed && (
                    <div className="absolute -top-1 -right-1 w-6 h-6 rounded-full bg-red-500 text-white flex items-center justify-center shadow-md">
                      <span className="text-xs font-bold">!</span>
                    </div>
                  )}
                </div>

                {/* Bottom: Collection Title & Subtitle */}
                <div className="w-full">
                  <h3
                    className="text-sm font-bold text-slate-800 group-hover:text-[#FF5148] transition-colors truncate"
                    title={coll.display_name}
                  >
                    {coll.display_name}
                  </h3>
                  <p className="text-[11px] text-slate-400 truncate mt-0.5">
                    {isProcessing ? "Processing..." : isFailed ? "Failed" : `${fileCount} ${fileCount === 1 ? "file" : "files"}`}
                  </p>
                  <span className="inline-flex items-center gap-1 text-[11px] font-semibold text-[#FF5148] opacity-0 group-hover:opacity-100 transition-opacity mt-1">
                    View Details &rarr;
                  </span>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* ========================================================================= */}
      {/* POPUP 1: Create Collection Modal                                          */}
      {/* ========================================================================= */}
      {createModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/50 backdrop-blur-sm animate-in fade-in duration-150">
          <div className="relative w-full max-w-lg bg-white rounded-3xl border border-slate-200/90 shadow-2xl p-6 sm:p-7 overflow-hidden animate-in zoom-in-95 duration-150">
            {/* Modal Header */}
            <div className="flex items-start justify-between pb-4 border-b border-slate-100">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 flex items-center justify-center">
                  <img src="/collection.png" alt="Collection" className="w-9 h-9 object-contain drop-shadow-sm" />
                </div>
                <div>
                  <h2 className="text-xl font-extrabold text-slate-900 tracking-tight">Create Collection</h2>
                  <p className="text-xs text-slate-500 mt-0.5">
                    Pool multiple PDFs into a vectorized knowledge pool.
                  </p>
                </div>
              </div>

              {/* Close Button */}
              <button
                onClick={closeCreateModal}
                className="w-8 h-8 rounded-full bg-slate-100 hover:bg-slate-200 text-slate-500 hover:text-slate-800 flex items-center justify-center transition-colors cursor-pointer"
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>

            {/* Modal Form */}
            <form onSubmit={handleUploadSubmit} className="mt-5 space-y-5">
              {/* Display Name Input */}
              <div className="space-y-1.5">
                <label className="block text-xs font-bold text-slate-700 tracking-wide uppercase">
                  Display Name <span className="text-[#FF5148]">*</span>
                </label>
                <input
                  type="text"
                  value={displayName}
                  onChange={(e) => {
                    setDisplayName(e.target.value);
                    setFormError(null);
                  }}
                  placeholder="e.g. Q3 Financial Reports, HR Policies..."
                  className="w-full px-4 py-2.5 rounded-2xl border border-slate-200 bg-slate-50/50 text-slate-900 text-sm focus:outline-none focus:ring-2 focus:ring-[#FF5148]/30 focus:border-[#FF5148] transition-all"
                  autoFocus
                />
              </div>

              {/* Drag & Drop Area */}
              <div className="space-y-1.5">
                <label className="block text-xs font-bold text-slate-700 tracking-wide uppercase">
                  Attach Documents (.pdf) <span className="text-[#FF5148]">*</span>
                </label>

                <div
                  onDragEnter={handleDrag}
                  onDragLeave={handleDrag}
                  onDragOver={handleDrag}
                  onDrop={handleDrop}
                  onClick={() => fileInputRef.current?.click()}
                  className={`border-2 border-dashed rounded-2xl p-6 text-center transition-all cursor-pointer flex flex-col items-center justify-center gap-2 ${dragActive
                      ? "border-[#FF5148] bg-orange-50/80 scale-[1.01]"
                      : "border-slate-300 hover:border-[#FF5148] bg-slate-50/50 hover:bg-orange-50/30"
                    }`}
                >
                  <input
                    ref={fileInputRef}
                    type="file"
                    accept=".pdf"
                    multiple
                    onChange={handleFileInputChange}
                    className="hidden"
                  />

                  <div className="w-10 h-10 rounded-2xl bg-orange-100 text-[#FF5148] flex items-center justify-center shadow-2xs">
                    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        strokeWidth={2}
                        d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12"
                      />
                    </svg>
                  </div>
                  <div>
                    <p className="text-xs font-bold text-slate-800">
                      Drag & drop your <span className="text-[#FF5148]">.pdf</span> files here, or browse
                    </p>
                    <p className="text-[11px] text-slate-400 mt-0.5">Supports multiple files simultaneously</p>
                  </div>
                </div>
              </div>

              {/* Attached Files List with Small Scroll Bar */}
              {selectedFiles.length > 0 && (
                <div className="space-y-1.5">
                  <div className="flex items-center justify-between text-xs font-bold text-slate-700">
                    <span>Attached Documents ({selectedFiles.length})</span>
                    <button
                      type="button"
                      onClick={() => setSelectedFiles([])}
                      className="text-xs text-red-500 hover:underline font-normal cursor-pointer"
                    >
                      Clear all
                    </button>
                  </div>

                  {/* Scrollable list with thin scrollbar */}
                  <div className="max-h-40 overflow-y-auto space-y-1.5 pr-1 border border-slate-100 rounded-2xl p-2 bg-slate-50/40">
                    {selectedFiles.map((file, idx) => (
                      <div
                        key={idx}
                        className="flex items-center justify-between gap-3 p-2.5 rounded-xl bg-white border border-slate-200/80 shadow-2xs text-xs"
                      >
                        <div className="flex items-center gap-2.5 min-w-0">
                          <span className="px-1.5 py-0.5 rounded bg-red-100 text-red-700 font-bold text-[10px] shrink-0">
                            PDF
                          </span>
                          <span className="font-semibold text-slate-800 truncate" title={file.name}>
                            {file.name}
                          </span>
                          <span className="text-[11px] text-slate-400 shrink-0">
                            ({formatFileSize(file.size)})
                          </span>
                        </div>

                        {/* Remove file button */}
                        <button
                          type="button"
                          onClick={() => removeSelectedFile(idx)}
                          className="w-6 h-6 rounded-lg text-slate-400 hover:text-red-500 hover:bg-red-50 flex items-center justify-center transition-colors cursor-pointer shrink-0"
                          title="Remove file"
                        >
                          <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M6 18L18 6M6 6l12 12" />
                          </svg>
                        </button>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Error Message */}
              {formError && (
                <div className="p-3 rounded-2xl bg-red-50 border border-red-200 text-xs text-red-700 flex items-center gap-2">
                  <svg className="w-4 h-4 text-red-500 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                      d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
                    />
                  </svg>
                  <span>{formError}</span>
                </div>
              )}

              {/* Modal Actions */}
              <div className="flex items-center justify-end gap-3 pt-3 border-t border-slate-100">
                <button
                  type="button"
                  onClick={closeCreateModal}
                  className="px-4 py-2.5 rounded-2xl border border-slate-200 hover:bg-slate-100 text-slate-600 font-semibold text-xs transition-colors cursor-pointer"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={!displayName.trim() || selectedFiles.length === 0}
                  className={`inline-flex items-center gap-2 px-5 py-2.5 rounded-2xl font-bold text-xs shadow-md transition-all ${!displayName.trim() || selectedFiles.length === 0
                      ? "bg-slate-200 text-slate-400 cursor-not-allowed shadow-none"
                      : "bg-gradient-to-r from-[#FF5148] to-orange-500 hover:opacity-95 text-white shadow-[#FF5148]/25 cursor-pointer active:scale-95"
                    }`}
                >
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2.5}
                      d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12"
                    />
                  </svg>
                  <span>Upload & Process</span>
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* ========================================================================= */}
      {/* POPUP 2: Collection Contents & PDF Inspector Modal                        */}
      {/* ========================================================================= */}
      {activeCollection && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/50 backdrop-blur-sm animate-in fade-in duration-150">
          <div className="relative w-full max-w-3xl bg-white rounded-3xl border border-slate-200/90 shadow-2xl overflow-hidden flex flex-col max-h-[85vh] animate-in zoom-in-95 duration-150">
            {/* Header */}
            <div className="p-6 pb-4 border-b border-slate-100 flex items-start justify-between gap-4">
              <div className="flex items-center gap-4">
                <img
                  src="/collection.png"
                  alt="Collection"
                  className="w-14 h-14 object-contain drop-shadow-sm shrink-0"
                />
                <div>
                  <div className="flex items-center gap-2.5">
                    <h2 className="text-xl font-extrabold text-slate-900 tracking-tight">
                      {activeCollection.display_name}
                    </h2>
                    <span className="px-2.5 py-0.5 rounded-full text-xs font-bold bg-orange-50 text-[#FF5148] border border-[#FF5148]/20">
                      {activeCollection.documents?.length || 0} PDFs
                    </span>
                  </div>
                </div>
              </div>

              {/* Close Button */}
              <button
                onClick={handleCloseCollectionDetails}
                className="w-8 h-8 rounded-full bg-slate-100 hover:bg-slate-200 text-slate-500 hover:text-slate-800 flex items-center justify-center transition-colors cursor-pointer shrink-0"
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>

            {/* Modal Body: Left PDF List Box | Right PDF Info View */}
            <div className="flex-1 overflow-hidden grid grid-cols-1 md:grid-cols-5 min-h-[350px]">
              {/* Box inside containing the PDFs (3 cols) */}
              <div className="md:col-span-3 border-r border-slate-100 p-5 overflow-y-auto space-y-3 bg-slate-50/40">
                <div className="flex items-center justify-between">
                  <h4 className="text-xs font-bold text-slate-700 uppercase tracking-wider">
                    PDF Documents ({activeCollection.documents?.length || 0})
                  </h4>
                  <span className="text-[11px] text-slate-400">Click a PDF to view details</span>
                </div>

                <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 pt-1">
                  {(activeCollection.documents || []).map((doc, idx) => {
                    const isSelected = selectedPdf?.document_id === doc.document_id;
                    const truncatedName =
                      doc.file_name && doc.file_name.length > 15
                        ? doc.file_name.slice(0, 12) + "..."
                        : doc.file_name;

                    return (
                      <div
                        key={doc.document_id || idx}
                        onClick={() => setSelectedPdf(doc)}
                        className={`flex flex-col items-center text-center p-3 rounded-2xl border transition-all cursor-pointer group ${isSelected
                            ? "border-[#FF5148] bg-white ring-2 ring-[#FF5148]/20 shadow-xs"
                            : "border-slate-200/80 bg-white hover:border-orange-200 hover:shadow-xs"
                          }`}
                      >
                        {/* PDF Icon */}
                        <div className="w-12 h-12 rounded-2xl bg-red-50 text-red-600 flex items-center justify-center mb-2 shadow-2xs group-hover:scale-105 transition-transform">
                          <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path
                              strokeLinecap="round"
                              strokeLinejoin="round"
                              strokeWidth={1.75}
                              d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
                            />
                          </svg>
                        </div>
                        <span
                          className="text-xs font-bold text-slate-800 w-full break-words"
                          title={doc.file_name}
                        >
                          {truncatedName}
                        </span>
                        <span className="text-[10px] text-slate-400 mt-1">
                          {formatFileSize(doc.file_size)}
                        </span>
                      </div>
                    );
                  })}

                  {/* Dotted Square + Card to Add New PDFs */}
                  <div
                    onClick={() => !isAppendingPdf && appendFileInputRef.current?.click()}
                    className={`flex flex-col items-center justify-center p-3 rounded-2xl border-2 border-dashed transition-all cursor-pointer select-none min-h-[110px] ${
                      isAppendingPdf
                        ? "border-orange-300 bg-orange-50/50 cursor-wait opacity-80"
                        : "border-slate-300 hover:border-[#FF5148] bg-slate-50/60 hover:bg-orange-50/30 group active:scale-95"
                    }`}
                  >
                    <input
                      ref={appendFileInputRef}
                      type="file"
                      accept=".pdf"
                      multiple
                      onChange={handleAppendPdfFiles}
                      className="hidden"
                    />

                    {isAppendingPdf ? (
                      <div className="flex flex-col items-center gap-1.5 text-center">
                        <svg className="w-6 h-6 animate-spin text-[#FF5148]" fill="none" viewBox="0 0 24 24">
                          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
                        </svg>
                        <span className="text-[10px] font-bold text-orange-600">Indexing...</span>
                      </div>
                    ) : (
                      <div className="flex flex-col items-center gap-1.5 text-center">
                        <div className="w-10 h-10 rounded-2xl bg-orange-100/80 text-[#FF5148] flex items-center justify-center shadow-2xs group-hover:scale-110 transition-transform">
                          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M12 4v16m8-8H4" />
                          </svg>
                        </div>
                        <span className="text-[11px] font-bold text-slate-600 group-hover:text-[#FF5148] transition-colors">
                          Add PDF
                        </span>
                      </div>
                    )}
                  </div>
                </div>
              </div>

              {/* Right Side: PDF Info Panel (2 cols) */}
              <div className="md:col-span-2 p-5 bg-white flex flex-col justify-between overflow-y-auto">
                {selectedPdf ? (
                  <div className="space-y-4">
                    <div>
                      <span className="px-2 py-0.5 rounded-md bg-red-100 text-red-700 font-bold text-[10px] uppercase">
                        PDF Details
                      </span>
                      <h3
                        className="text-base font-extrabold text-slate-900 mt-1.5 break-words"
                        title={selectedPdf.file_name}
                      >
                        {selectedPdf.file_name && selectedPdf.file_name.length > 18
                          ? selectedPdf.file_name.slice(0, 14) + "..."
                          : selectedPdf.file_name}
                      </h3>
                    </div>

                    {/* Metadata Specs Table: strictly File Name, File Type, File Size, Total Pages */}
                    <div className="space-y-2.5 rounded-2xl bg-slate-50 p-4 border border-slate-100 text-xs">
                      <div className="flex justify-between items-center py-1 border-b border-slate-200/60">
                        <span className="text-slate-500">File Name:</span>
                        <span
                          className="font-semibold text-slate-800 text-right max-w-[140px] truncate"
                          title={selectedPdf.file_name}
                        >
                          {selectedPdf.file_name && selectedPdf.file_name.length > 14
                            ? selectedPdf.file_name.slice(0, 11) + "..."
                            : selectedPdf.file_name}
                        </span>
                      </div>
                      <div className="flex justify-between items-center py-1 border-b border-slate-200/60">
                        <span className="text-slate-500">File Type:</span>
                        <span className="font-semibold text-slate-800 uppercase">
                          {selectedPdf.file_type || "PDF"}
                        </span>
                      </div>
                      <div className="flex justify-between items-center py-1 border-b border-slate-200/60">
                        <span className="text-slate-500">File Size:</span>
                        <span className="font-semibold text-slate-800">{formatFileSize(selectedPdf.file_size)}</span>
                      </div>
                      <div className="flex justify-between items-center py-1">
                        <span className="text-slate-500">Total Pages:</span>
                        <span className="font-semibold text-slate-800">{selectedPdf.total_pages ?? "—"}</span>
                      </div>
                    </div>

                    {/* Delete PDF Button */}
                    <div className="pt-2">
                      <button
                        type="button"
                        onClick={() => handleDeletePdf(selectedPdf.document_id)}
                        disabled={isDeletingPdf === selectedPdf.document_id}
                        className="w-full flex items-center justify-center gap-2 px-3.5 py-2 rounded-xl bg-red-50 hover:bg-red-100 text-red-600 font-bold text-xs border border-red-200 transition-colors cursor-pointer"
                      >
                        <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path
                            strokeLinecap="round"
                            strokeLinejoin="round"
                            strokeWidth={2}
                            d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"
                          />
                        </svg>
                        <span>{isDeletingPdf === selectedPdf.document_id ? "Deleting PDF..." : "Delete PDF"}</span>
                      </button>
                    </div>
                  </div>
                ) : (
                  <div className="flex flex-col items-center justify-center h-full text-center text-slate-400 py-8">
                    <svg className="w-8 h-8 text-slate-300 mb-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        strokeWidth={1.5}
                        d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
                      />
                    </svg>
                    <p className="text-xs">Select a PDF to view information</p>
                  </div>
                )}
              </div>
            </div>

            {/* Modal Bottom Bar: Delete Collection Button */}
            <div className="p-4 px-6 bg-slate-50 border-t border-slate-100 flex items-center justify-between">
              <div>
                <span className="text-xs text-slate-400">Created: {formatDate(activeCollection.created_at)}</span>
              </div>

              {showDeleteCollConfirm ? (
                <div className="flex items-center gap-2">
                  <span className="text-xs font-bold text-red-600">Delete collection and all vectors?</span>
                  <button
                    onClick={handleDeleteCollection}
                    disabled={isDeletingCollection}
                    className="px-3 py-1.5 rounded-xl bg-red-600 hover:bg-red-700 text-white font-bold text-xs cursor-pointer shadow-xs"
                  >
                    {isDeletingCollection ? "Deleting..." : "Yes, Delete"}
                  </button>
                  <button
                    onClick={() => setShowDeleteCollConfirm(false)}
                    className="px-3 py-1.5 rounded-xl bg-slate-200 hover:bg-slate-300 text-slate-700 font-semibold text-xs cursor-pointer"
                  >
                    Cancel
                  </button>
                </div>
              ) : (
                <button
                  type="button"
                  onClick={() => setShowDeleteCollConfirm(true)}
                  className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-xl text-red-600 hover:bg-red-50 hover:border-red-200 border border-transparent font-bold text-xs transition-colors cursor-pointer"
                >
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={1.75}
                      d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"
                    />
                  </svg>
                  <span>Delete Collection</span>
                </button>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
