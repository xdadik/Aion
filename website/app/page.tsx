"use client";

import { useState, useEffect } from "react";

// ── Marketing site for Aion Hand ───────────────────────────────────────────

const STATS = [
  { label: "Tests passing", value: "600+" },
  { label: "Built-in skills", value: "93" },
  { label: "Personas (SOUL.md)", value: "26" },
  { label: "Core modules", value: "26" },
  { label: "Messaging adapters", value: "20+" },
  { label: "License", value: "MIT" },
];

const FEATURES = [
  {
    icon: "🧠",
    title: "6-Layer Memory System",
    desc: "Working → Session → Episodic → Semantic → Procedural → UserProfile. SQLite FTS5 semantic search. Auto-updating MEMORY.md and USER.md.",
  },
  {
    icon: "🤖",
    title: "Self-Improving Skills",
    desc: "Hermes-compatible SKILL.md format. Auto-create skills from experience. Skill marketplace (HTTP/git/local install). 93 skills out of the box.",
  },
  {
    icon: "🎭",
    title: "SOUL.md Persona System",
    desc: "OpenClaw-inspired personas. 26 built-in (researcher, coder, architect, SRE, mentor, etc.). User personas shadow built-ins. Runtime switching.",
  },
  {
    icon: "🔧",
    title: "25+ Built-in Tools",
    desc: "MCP-compatible tool registry. Web search, code execution, file I/O, shell, calculator, weather, todos, image generation. MCP client AND server.",
  },
  {
    icon: "🛡️",
    title: "Security Sandbox",
    desc: "Command validation, whitelists, three approval modes. Path-traversal guards. PII redaction. Per-tool timeouts. Execution audit log.",
  },
  {
    icon: "🤝",
    title: "Multi-Agent Orchestration",
    desc: "DAG workflows, dynamic subagent spawning, Mixture-of-Agents (MoA) loop. Pipeline: plan → execute → verify → critique → repair.",
  },
  {
    icon: "💬",
    title: "20+ Messaging Platforms",
    desc: "Real Telegram Bot API, Discord, Slack, WhatsApp, Signal, Teams, WeChat, QQ, Feishu, DingTalk, Matrix, IRC, Line, Email, Ntfy, Webhook.",
  },
  {
    icon: "📊",
    title: "Telemetry + Health",
    desc: "Counters, gauges, histograms, trace spans, event log. Liveness + readiness probes (K8s-friendly). JSON export to any observability backend.",
  },
  {
    icon: "🎯",
    title: "Benchmark Harness",
    desc: "Built-in task suite across categories and difficulties. Run Aion vs. baselines on identical tasks. Compare runs, detect regressions.",
  },
  {
    icon: "🎙️",
    title: "Voice (TTS + STT)",
    desc: "Multi-backend: pyttsx3, macOS say, Linux espeak, OpenAI Whisper. Graceful fallback when no backend available. Microphone transcription.",
  },
  {
    icon: "🌐",
    title: "Browser Automation",
    desc: "Playwright (full JS rendering) + stdlib urllib fallback. fetch, screenshot, click, fill_form. Returns parsed Page with title/text/links/meta.",
  },
  {
    icon: "🔌",
    title: "Plugin System",
    desc: "Drop Python files into ~/.aion-hand/plugins/. Each plugin adds tools, skills, personas, providers, cron tasks at runtime. No code changes needed.",
  },
];

const COMPARISON = [
  { feature: "6-layer memory", aion: true, hermes: true, openclaw: false },
  { feature: "SKILL.md format", aion: true, hermes: true, openclaw: false },
  { feature: "SOUL.md personas", aion: true, hermes: false, openclaw: true },
  { feature: "Pipeline + critic + verifiers", aion: true, hermes: false, openclaw: false },
  { feature: "Multi-agent DAG orchestration", aion: true, hermes: false, openclaw: false },
  { feature: "MCP server (Aion exposes tools)", aion: true, hermes: false, openclaw: false },
  { feature: "20+ messaging adapters", aion: true, hermes: false, openclaw: false },
  { feature: "Knowledge graph", aion: true, hermes: false, openclaw: false },
  { feature: "Model router + cost optimiser", aion: true, hermes: false, openclaw: false },
  { feature: "Backup / restore", aion: true, hermes: false, openclaw: false },
  { feature: "Plugin system", aion: true, hermes: false, openclaw: false },
  { feature: "RL training loop", aion: true, hermes: false, openclaw: true },
  { feature: "Native desktop app", aion: true, hermes: true, openclaw: false },
  { feature: "Zero hard dependencies", aion: true, hermes: false, openclaw: false },
  { feature: "Built-in benchmark", aion: true, hermes: false, openclaw: false },
];

export default function HomePage() {
  return (
    <div style={{
      fontFamily: "system-ui, -apple-system, sans-serif",
      background: "#0a0e1a",
      color: "#e2e8f0",
      minHeight: "100vh",
    }}>
      {/* Hero */}
      <section style={{
        textAlign: "center",
        padding: "120px 24px 80px",
        background: "radial-gradient(circle at 50% 30%, rgba(0,229,255,0.15) 0%, transparent 60%)",
      }}>
        <div style={{
          display: "inline-block",
          padding: "6px 14px",
          borderRadius: 999,
          background: "rgba(0,229,255,0.1)",
          color: "#00E5FF",
          fontSize: 13,
          fontWeight: 600,
          marginBottom: 24,
          border: "1px solid rgba(0,229,255,0.2)",
        }}>
          v0.4.0 · 600+ tests · MIT License
        </div>
        <h1 style={{
          fontSize: "clamp(40px, 6vw, 72px)",
          fontWeight: 800,
          margin: "0 0 24px",
          background: "linear-gradient(135deg, #00E5FF 0%, #A78BFA 100%)",
          WebkitBackgroundClip: "text",
          WebkitTextFillColor: "transparent",
          lineHeight: 1.1,
        }}>
          Aion Hand
        </h1>
        <p style={{
          fontSize: "clamp(18px, 2vw, 24px)",
          color: "#94a3b8",
          maxWidth: 720,
          margin: "0 auto 40px",
          lineHeight: 1.5,
        }}>
          The open-source, self-improving autonomous AI agent framework that
          combines the best of <strong style={{color:"#00E5FF"}}>OpenClaw</strong>,
          {" "}<strong style={{color:"#00E5FF"}}>Hermes</strong>,
          {" "}<strong style={{color:"#00E5FF"}}>NullClaw</strong>,
          {" "}<strong style={{color:"#00E5FF"}}>CrewAI</strong>,
          {" "}<strong style={{color:"#00E5FF"}}>AutoGPT</strong>, and
          {" "}<strong style={{color:"#00E5FF"}}>LangGraph</strong>.
        </p>
        <div style={{ display: "flex", gap: 12, justifyContent: "center", flexWrap: "wrap" }}>
          <a href="https://github.com/xdadik/Aion" style={{
            background: "#00E5FF",
            color: "#0a0e1a",
            padding: "14px 28px",
            borderRadius: 8,
            textDecoration: "none",
            fontWeight: 700,
            fontSize: 16,
          }}>
            ⭐ Star on GitHub
          </a>
          <a href="https://github.com/xdadik/Aion/blob/main/docs/INSTALL.md" style={{
            background: "transparent",
            color: "#e2e8f0",
            padding: "14px 28px",
            borderRadius: 8,
            textDecoration: "none",
            fontWeight: 600,
            fontSize: 16,
            border: "1px solid #334155",
          }}>
            📦 Install
          </a>
          <a href="https://github.com/xdadik/Aion/blob/main/docs/examples/COOKBOOK.md" style={{
            background: "transparent",
            color: "#e2e8f0",
            padding: "14px 28px",
            borderRadius: 8,
            textDecoration: "none",
            fontWeight: 600,
            fontSize: 16,
            border: "1px solid #334155",
          }}>
            📖 Cookbook
          </a>
        </div>
      </section>

      {/* Stats */}
      <section style={{
        padding: "40px 24px",
        background: "rgba(15, 23, 42, 0.6)",
      }}>
        <div style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))",
          gap: 24,
          maxWidth: 1100,
          margin: "0 auto",
        }}>
          {STATS.map((s) => (
            <div key={s.label} style={{ textAlign: "center" }}>
              <div style={{ fontSize: 32, fontWeight: 800, color: "#00E5FF" }}>{s.value}</div>
              <div style={{ fontSize: 13, color: "#94a3b8", marginTop: 4 }}>{s.label}</div>
            </div>
          ))}
        </div>
      </section>

      {/* Features */}
      <section style={{ padding: "80px 24px", maxWidth: 1200, margin: "0 auto" }}>
        <h2 style={{
          fontSize: 36,
          fontWeight: 700,
          textAlign: "center",
          marginBottom: 12,
        }}>
          Everything you need to build autonomous agents
        </h2>
        <p style={{ textAlign: "center", color: "#94a3b8", marginBottom: 60, fontSize: 17 }}>
          30+ capabilities in a single, modular framework. No external services required.
        </p>
        <div style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))",
          gap: 24,
        }}>
          {FEATURES.map((f) => (
            <div key={f.title} style={{
              background: "rgba(15, 23, 42, 0.6)",
              border: "1px solid #1e293b",
              borderRadius: 12,
              padding: 24,
              transition: "border-color 0.2s",
            }}>
              <div style={{ fontSize: 32, marginBottom: 12 }}>{f.icon}</div>
              <h3 style={{ margin: "0 0 8px", fontSize: 18, color: "#00E5FF" }}>{f.title}</h3>
              <p style={{ margin: 0, color: "#94a3b8", fontSize: 14, lineHeight: 1.6 }}>{f.desc}</p>
            </div>
          ))}
        </div>
      </section>

      {/* Comparison table */}
      <section style={{ padding: "80px 24px", background: "rgba(15, 23, 42, 0.6)" }}>
        <div style={{ maxWidth: 1000, margin: "0 auto" }}>
          <h2 style={{ fontSize: 36, fontWeight: 700, textAlign: "center", marginBottom: 12 }}>
            How Aion compares
          </h2>
          <p style={{ textAlign: "center", color: "#94a3b8", marginBottom: 60, fontSize: 17 }}>
            Every claim is verifiable in the repo. No marketing fluff.
          </p>
          <table style={{
            width: "100%",
            borderCollapse: "collapse",
            fontSize: 15,
          }}>
            <thead>
              <tr style={{ borderBottom: "2px solid #334155" }}>
                <th style={{ textAlign: "left", padding: "12px 16px", color: "#94a3b8" }}>Capability</th>
                <th style={{ padding: "12px 16px", color: "#00E5FF" }}>Aion Hand</th>
                <th style={{ padding: "12px 16px", color: "#94a3b8" }}>Hermes</th>
                <th style={{ padding: "12px 16px", color: "#94a3b8" }}>OpenClaw</th>
              </tr>
            </thead>
            <tbody>
              {COMPARISON.map((row) => (
                <tr key={row.feature} style={{ borderBottom: "1px solid #1e293b" }}>
                  <td style={{ padding: "12px 16px", color: "#e2e8f0" }}>{row.feature}</td>
                  <td style={{ padding: "12px 16px", textAlign: "center", color: row.aion ? "#10B981" : "#64748b", fontSize: 18 }}>
                    {row.aion ? "✅" : "❌"}
                  </td>
                  <td style={{ padding: "12px 16px", textAlign: "center", color: row.hermes ? "#10B981" : "#64748b", fontSize: 18 }}>
                    {row.hermes ? "✅" : "❌"}
                  </td>
                  <td style={{ padding: "12px 16px", textAlign: "center", color: row.openclaw ? "#10B981" : "#64748b", fontSize: 18 }}>
                    {row.openclaw ? "✅" : "❌"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {/* Quick start */}
      <section style={{ padding: "80px 24px", maxWidth: 900, margin: "0 auto" }}>
        <h2 style={{ fontSize: 36, fontWeight: 700, textAlign: "center", marginBottom: 40 }}>
          Quick start
        </h2>
        <div style={{
          background: "#0f172a",
          border: "1px solid #1e293b",
          borderRadius: 12,
          padding: 24,
          fontFamily: "monospace",
          fontSize: 14,
          lineHeight: 1.8,
          color: "#86EFAC",
        }}>
          <div><span style={{color: "#64748b"}}># Install</span></div>
          <div>pip install -e <span style={{color: "#FCD34D"}}>"[all]"</span></div>
          <div style={{height: 16}}></div>
          <div><span style={{color: "#64748b"}}># Set your LLM API key</span></div>
          <div><span style={{color: "#C084FC"}}>export</span> OPENAI_API_KEY=<span style={{color: "#FCD34D"}}>"sk-..."</span></div>
          <div style={{height: 16}}></div>
          <div><span style={{color: "#64748b"}}># Launch the TUI</span></div>
          <div>aion-tui</div>
          <div style={{height: 16}}></div>
          <div><span style={{color: "#64748b"}}># Or the web UI</span></div>
          <div>cd aion_web && npm install && npm run dev</div>
          <div style={{height: 16}}></div>
          <div><span style={{color: "#64748b"}}># Or the HTTP API</span></div>
          <div>aion-hand serve --port 8000</div>
        </div>
      </section>

      {/* CTA */}
      <section style={{
        padding: "80px 24px",
        textAlign: "center",
        background: "radial-gradient(circle at 50% 50%, rgba(167,139,250,0.1) 0%, transparent 60%)",
      }}>
        <h2 style={{ fontSize: 36, fontWeight: 700, marginBottom: 16 }}>
          Ready to build with Aion?
        </h2>
        <p style={{ color: "#94a3b8", marginBottom: 32, fontSize: 17 }}>
          Open source. Self-hosted. Yours to extend.
        </p>
        <a href="https://github.com/xdadik/Aion" style={{
          display: "inline-block",
          background: "#00E5FF",
          color: "#0a0e1a",
          padding: "16px 36px",
          borderRadius: 8,
          textDecoration: "none",
          fontWeight: 700,
          fontSize: 18,
        }}>
          Get started →
        </a>
      </section>

      {/* Footer */}
      <footer style={{
        padding: "40px 24px",
        textAlign: "center",
        borderTop: "1px solid #1e293b",
        color: "#64748b",
        fontSize: 13,
      }}>
        <p>© 2026 Aion Hand Contributors · MIT License</p>
        <p style={{ marginTop: 8 }}>
          <a href="https://github.com/xdadik/Aion" style={{color: "#94a3b8"}}>GitHub</a>
          {" · "}
          <a href="https://github.com/xdadik/Aion/blob/main/docs/examples/COOKBOOK.md" style={{color: "#94a3b8"}}>Cookbook</a>
          {" · "}
          <a href="https://github.com/xdadik/Aion/blob/main/CHANGELOG.md" style={{color: "#94a3b8"}}>Changelog</a>
          {" · "}
          <a href="https://github.com/xdadik/Aion/blob/main/CONTRIBUTING.md" style={{color: "#94a3b8"}}>Contributing</a>
        </p>
      </footer>
    </div>
  );
}
