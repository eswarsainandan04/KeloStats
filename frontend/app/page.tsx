import Link from "next/link";

export default function Home() {
  return (
    <div className="min-h-screen bg-white text-slate-900 flex flex-col font-sans selection:bg-orange-100 selection:text-orange-600">
      {/* ========================================================================= */}
      {/* TOP NAVIGATION BAR */}
      {/* ========================================================================= */}
      <header className="sticky top-0 z-50 bg-white/90 backdrop-blur-md border-b border-slate-100">
        <div className="max-w-6xl mx-auto px-6 h-18 flex items-center justify-between">
          {/* Brand Logo */}
          <Link href="/" className="flex items-center gap-2.5">
            <span className="font-extrabold text-2xl tracking-tight text-slate-900">
              <span className="text-[#FF5148]">KeloStats</span>
            </span>
          </Link>

          {/* Navigation Links */}
          <nav className="hidden md:flex items-center gap-8 text-sm font-medium text-slate-600">
            <a href="#features" className="hover:text-[#FF5148] transition-colors">Features</a>
            <a href="#how-it-works" className="hover:text-[#FF5148] transition-colors">How It Works</a>
            <a href="#templates" className="hover:text-[#FF5148] transition-colors">Templates</a>
          </nav>

          {/* Top Login & Signup Action Buttons */}
          <div className="flex items-center gap-3">
            <Link
              href="/login"
              className="px-4 py-2 text-sm font-semibold text-slate-700 hover:text-[#FF5148] transition-colors"
            >
              Log In
            </Link>
            <Link
              href="/signup"
              className="px-5 py-2.5 text-sm font-semibold text-white rounded-lg bg-[#FF5148] hover:bg-[#e64037] shadow-sm hover:shadow-md transition-all"
            >
              Sign Up
            </Link>
          </div>
        </div>
      </header>

      {/* ========================================================================= */}
      {/* HERO SECTION */}
      {/* ========================================================================= */}
      <main className="flex-1">
        <section className="pt-24 pb-20 px-6 max-w-4xl mx-auto text-center flex flex-col items-center">
          {/* Simple Tag */}
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-orange-50 border border-orange-200/60 text-xs font-semibold text-[#FF5148] mb-6">
            <span>⚡ AI-POWERED DATABASE PRESENTATIONS</span>
          </div>

          {/* Primary Headline with Orange Font */}
          <h1 className="text-4xl sm:text-6xl font-extrabold tracking-tight text-slate-900 leading-[1.15]">
            Turn Your Database Data into{" "}
            <span className="text-[#FF5148]">Executive PowerPoint Decks</span>
          </h1>

          {/* Subtitle */}
          <p className="mt-6 text-lg sm:text-xl text-slate-600 max-w-2xl leading-relaxed">
            Connect your PostgreSQL, MySQL, or Oracle databases. Our autonomous AI agents analyze your schema, run verified queries, and generate boardroom-ready slides in seconds.
          </p>

          {/* Primary CTA Buttons */}
          <div className="mt-9 flex flex-col sm:flex-row items-center justify-center gap-4 w-full max-w-sm">
            <Link
              href="/signup"
              className="w-full sm:w-auto px-7 py-3.5 rounded-lg font-semibold text-white bg-[#FF5148] hover:bg-[#e64037] shadow-lg shadow-[#FF5148]/25 hover:shadow-xl transition-all"
            >
              Get Started Free
            </Link>
            <Link
              href="/login"
              className="w-full sm:w-auto px-7 py-3.5 rounded-lg font-semibold text-slate-700 bg-slate-50 hover:bg-slate-100 border border-slate-200 transition-all"
            >
              Log In
            </Link>
          </div>

          {/* Feature Highlights */}
          <div className="mt-12 flex flex-wrap items-center justify-center gap-8 text-xs font-medium text-slate-500">
            <div className="flex items-center gap-2">
              <span className="w-1.5 h-1.5 rounded-full bg-[#FF5148]" />
              <span>Zero ETL Required</span>
            </div>
            <div className="flex items-center gap-2">
              <span className="w-1.5 h-1.5 rounded-full bg-[#FF5148]" />
              <span>Sub-Second Query Latency</span>
            </div>
            <div className="flex items-center gap-2">
              <span className="w-1.5 h-1.5 rounded-full bg-[#FF5148]" />
              <span>Instant .PPTX Downloads</span>
            </div>
          </div>
        </section>

        {/* ========================================================================= */}
        {/* SIMPLE 3-STEP SECTION */}
        {/* ========================================================================= */}
        <section id="how-it-works" className="py-16 px-6 bg-slate-50/60 border-y border-slate-100">
          <div className="max-w-5xl mx-auto">
            <div className="text-center mb-12">
              <h2 className="text-xs font-bold uppercase tracking-widest text-[#FF5148]">Simple 3-Step Process</h2>
              <p className="mt-2 text-2xl sm:text-3xl font-extrabold text-slate-900">
                From Raw Database to Complete Presentation
              </p>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
              {/* Step 1 */}
              <div className="p-6 rounded-xl bg-white border border-slate-200 shadow-sm">
                <div className="text-2xl font-black text-[#FF5148] mb-3">01</div>
                <h3 className="text-lg font-bold text-slate-900 mb-2">Connect Database</h3>
                <p className="text-sm text-slate-600 leading-relaxed">
                  Provide credentials for PostgreSQL, MySQL, or Oracle. Schemas and tables are securely extracted automatically.
                </p>
              </div>

              {/* Step 2 */}
              <div className="p-6 rounded-xl bg-white border border-slate-200 shadow-sm">
                <div className="text-2xl font-black text-[#FF5148] mb-3">02</div>
                <h3 className="text-lg font-bold text-slate-900 mb-2">Ask Any Question</h3>
                <p className="text-sm text-slate-600 leading-relaxed">
                  Our multi-agent system verifies safety, generates precise SQL, and extracts the exact metrics needed.
                </p>
              </div>

              {/* Step 3 */}
              <div className="p-6 rounded-xl bg-white border border-slate-200 shadow-sm">
                <div className="text-2xl font-black text-[#FF5148] mb-3">03</div>
                <h3 className="text-lg font-bold text-slate-900 mb-2">Download Slide Deck</h3>
                <p className="text-sm text-slate-600 leading-relaxed">
                  Get a beautifully styled, branded corporate PowerPoint presentation ready to present to your board or executive team.
                </p>
              </div>
            </div>
          </div>
        </section>

        {/* ========================================================================= */}
        {/* SIMPLE CALL TO ACTION */}
        {/* ========================================================================= */}
        <section className="py-20 px-6 max-w-4xl mx-auto text-center">
          <h3 className="text-2xl sm:text-3xl font-extrabold text-slate-900">
            Start Generating Decks with <span className="text-[#FF5148]">KeloStats</span> Today
          </h3>
          <p className="mt-3 text-slate-600 text-sm max-w-lg mx-auto">
            Create an account in seconds and connect your first database.
          </p>
          <div className="mt-7 flex justify-center gap-4">
            <Link
              href="/signup"
              className="px-7 py-3 rounded-lg font-semibold text-white bg-[#FF5148] hover:bg-[#e64037] shadow-md shadow-[#FF5148]/20 transition-all"
            >
              Sign Up Free
            </Link>
            <Link
              href="/login"
              className="px-6 py-3 rounded-lg font-semibold text-slate-700 border border-slate-200 hover:bg-slate-50 transition-all"
            >
              Log In
            </Link>
          </div>
        </section>
      </main>

      {/* ========================================================================= */}
      {/* FOOTER */}
      {/* ========================================================================= */}
      <footer className="border-t border-slate-100 py-8 px-6 bg-white">
        <div className="max-w-6xl mx-auto flex flex-col sm:flex-row items-center justify-between gap-4 text-xs text-slate-500">
          <div className="flex items-center gap-2">
            <span className="font-bold text-slate-800">Kelo<span className="text-[#FF5148]">Stats</span></span>
            <span>• © {new Date().getFullYear()} All rights reserved.</span>
          </div>
          <div className="flex items-center gap-6">
            <Link href="/login" className="hover:text-[#FF5148] transition-colors">Log In</Link>
            <Link href="/signup" className="hover:text-[#FF5148] transition-colors">Sign Up</Link>
            <a href="#" className="hover:text-[#FF5148] transition-colors">Privacy</a>
            <a href="#" className="hover:text-[#FF5148] transition-colors">Terms</a>
          </div>
        </div>
      </footer>
    </div>
  );
}
