"use client";

import { useState, useRef, useEffect } from "react";
import { Send, Bot, User, Loader2, Settings, Trash2, MessageSquare, Wrench } from "lucide-react";

// ── Types ────────────────────────────────────────────────────────────────

interface ChatMessage {
  id: string;
  role: "user" | "agent" | "system";
  content: string;
  timestamp: string;
  tools?: string[];
  tokens?: number;
}

interface AgentConfig {
  provider: string;
  model: string;
  persona: string;
  systemPrompt: string;
  temperature: number;
}

// ── Default config ───────────────────────────────────────────────────────

const DEFAULT_CONFIG: AgentConfig = {
  provider: "openai",
  model: "gpt-4o",
  persona: "default",
  systemPrompt: "",
  temperature: 0.7,
};

// ── Main component ───────────────────────────────────────────────────────

export default function ChatPage() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [config, setConfig] = useState<AgentConfig>(DEFAULT_CONFIG);
  const [showConfig, setShowConfig] = useState(false);
  const [isThinking, setIsThinking] = useState(false);
  const [totalTokens, setTotalTokens] = useState(0);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Auto-scroll on new message
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Load saved config from localStorage
  useEffect(() => {
    const saved = localStorage.getItem("aion-chat-config");
    if (saved) {
      try {
        setConfig({ ...DEFAULT_CONFIG, ...JSON.parse(saved) });
      } catch {}
    }
  }, []);

  // Save config to localStorage
  useEffect(() => {
    localStorage.setItem("aion-chat-config", JSON.stringify(config));
  }, [config]);

  // ── Send message ──────────────────────────────────────────────────────

  async function sendMessage() {
    if (!input.trim() || isThinking) return;

    const userMsg: ChatMessage = {
      id: crypto.randomUUID(),
      role: "user",
      content: input.trim(),
      timestamp: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, userMsg]);
    setInput("");
    setIsThinking(true);

    try {
      // In a real deployment, this calls the Aion backend HTTP API.
      // For now, we simulate the response so the UI is fully functional
      // even without a backend running.
      const response = await simulateAgentResponse(userMsg.content, config);
      setMessages((prev) => [...prev, response]);
      if (response.tokens) {
        setTotalTokens((prev) => prev + (response.tokens ?? 0));
      }
    } catch (err) {
      const errMsg: ChatMessage = {
        id: crypto.randomUUID(),
        role: "system",
        content: `Error: ${err instanceof Error ? err.message : String(err)}`,
        timestamp: new Date().toISOString(),
      };
      setMessages((prev) => [...prev, errMsg]);
    } finally {
      setIsThinking(false);
    }
  }

  // ── Clear conversation ─────────────────────────────────────────────────

  function clearChat() {
    setMessages([]);
    setTotalTokens(0);
  }

  // ── Key handler ─────────────────────────────────────────────────────────

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  }

  // ── Render ─────────────────────────────────────────────────────────────

  return (
    <div style={{
      display: "flex",
      flexDirection: "column",
      height: "100vh",
      background: "linear-gradient(135deg, #0f172a 0%, #1e293b 100%)",
      color: "#e2e8f0",
      fontFamily: "system-ui, -apple-system, sans-serif",
    }}>
      {/* Header */}
      <header style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        padding: "16px 24px",
        borderBottom: "1px solid #1e293b",
        background: "rgba(15, 23, 42, 0.8)",
        backdropFilter: "blur(10px)",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <Bot size={28} color="#00E5FF" />
          <div>
            <h1 style={{ margin: 0, fontSize: 20, fontWeight: 700 }}>
              Aion Hand Chat
            </h1>
            <p style={{ margin: 0, fontSize: 12, color: "#94a3b8" }}>
              Persona: {config.persona} · Model: {config.model} · Tokens: {totalTokens}
            </p>
          </div>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button
            onClick={() => setShowConfig(!showConfig)}
            style={{
              background: "transparent",
              border: "1px solid #334155",
              color: "#94a3b8",
              padding: "8px 12px",
              borderRadius: 6,
              cursor: "pointer",
              display: "flex",
              alignItems: "center",
              gap: 6,
            }}
          >
            <Settings size={16} /> Settings
          </button>
          <button
            onClick={clearChat}
            style={{
              background: "transparent",
              border: "1px solid #334155",
              color: "#94a3b8",
              padding: "8px 12px",
              borderRadius: 6,
              cursor: "pointer",
              display: "flex",
              alignItems: "center",
              gap: 6,
            }}
          >
            <Trash2 size={16} /> Clear
          </button>
        </div>
      </header>

      {/* Config panel */}
      {showConfig && (
        <div style={{
          padding: "16px 24px",
          background: "#1e293b",
          borderBottom: "1px solid #334155",
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))",
          gap: 12,
        }}>
          <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            <span style={{ fontSize: 12, color: "#94a3b8" }}>Provider</span>
            <select
              value={config.provider}
              onChange={(e) => setConfig({ ...config, provider: e.target.value })}
              style={inputStyle}
            >
              <option value="openai">OpenAI</option>
              <option value="anthropic">Anthropic</option>
              <option value="ollama">Ollama (local)</option>
              <option value="groq">Groq</option>
              <option value="mistral">Mistral</option>
            </select>
          </label>
          <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            <span style={{ fontSize: 12, color: "#94a3b8" }}>Model</span>
            <input
              type="text"
              value={config.model}
              onChange={(e) => setConfig({ ...config, model: e.target.value })}
              style={inputStyle}
            />
          </label>
          <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            <span style={{ fontSize: 12, color: "#94a3b8" }}>Persona</span>
            <select
              value={config.persona}
              onChange={(e) => setConfig({ ...config, persona: e.target.value })}
              style={inputStyle}
            >
              <option value="default">Default (Aion)</option>
              <option value="researcher">Researcher</option>
              <option value="coder">Senior Engineer</option>
              <option value="assistant">Personal Assistant</option>
              <option value="analyst">Data Analyst</option>
              <option value="writer">Writer</option>
              <option value="tutor">Tutor</option>
              <option value="devops">DevOps Engineer</option>
              <option value="pm">Product Manager</option>
              <option value="architect">Systems Architect</option>
              <option value="sre">SRE</option>
              <option value="philosopher">Philosopher</option>
            </select>
          </label>
          <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            <span style={{ fontSize: 12, color: "#94a3b8" }}>Temperature: {config.temperature.toFixed(1)}</span>
            <input
              type="range"
              min={0}
              max={2}
              step={0.1}
              value={config.temperature}
              onChange={(e) => setConfig({ ...config, temperature: parseFloat(e.target.value) })}
              style={{ accentColor: "#00E5FF" }}
            />
          </label>
        </div>
      )}

      {/* Messages */}
      <main style={{
        flex: 1,
        overflowY: "auto",
        padding: "24px",
        display: "flex",
        flexDirection: "column",
        gap: 16,
      }}>
        {messages.length === 0 && (
          <div style={{
            textAlign: "center",
            color: "#64748b",
            marginTop: "20%",
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            gap: 12,
          }}>
            <MessageSquare size={48} color="#334155" />
            <p>Send a message to start chatting with Aion.</p>
            <p style={{ fontSize: 12 }}>
              Try: "Hello", "What can you do?", or "Search for the latest news about AI"
            </p>
          </div>
        )}
        {messages.map((msg) => (
          <MessageBubble key={msg.id} msg={msg} />
        ))}
        {isThinking && (
          <div style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            color: "#00E5FF",
            padding: "12px 16px",
          }}>
            <Loader2 size={16} className="animate-spin" />
            <span>Aion is thinking…</span>
          </div>
        )}
        <div ref={messagesEndRef} />
      </main>

      {/* Input */}
      <footer style={{
        padding: "16px 24px",
        borderTop: "1px solid #1e293b",
        background: "rgba(15, 23, 42, 0.8)",
        backdropFilter: "blur(10px)",
      }}>
        <div style={{
          display: "flex",
          gap: 12,
          alignItems: "flex-end",
          maxWidth: 1200,
          margin: "0 auto",
        }}>
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Send a message to Aion… (Enter to send, Shift+Enter for new line)"
            rows={1}
            style={{
              flex: 1,
              background: "#1e293b",
              border: "1px solid #334155",
              borderRadius: 8,
              padding: "12px 16px",
              color: "#e2e8f0",
              fontFamily: "inherit",
              fontSize: 14,
              resize: "none",
              minHeight: 44,
              maxHeight: 200,
              outline: "none",
            }}
          />
          <button
            onClick={sendMessage}
            disabled={!input.trim() || isThinking}
            style={{
              background: input.trim() && !isThinking ? "#00E5FF" : "#334155",
              color: input.trim() && !isThinking ? "#0f172a" : "#64748b",
              border: "none",
              borderRadius: 8,
              padding: "12px 20px",
              cursor: input.trim() && !isThinking ? "pointer" : "not-allowed",
              display: "flex",
              alignItems: "center",
              gap: 6,
              fontWeight: 600,
            }}
          >
            <Send size={16} /> Send
          </button>
        </div>
      </footer>
    </div>
  );
}

// ── Message bubble ──────────────────────────────────────────────────────

function MessageBubble({ msg }: { msg: ChatMessage }) {
  const isUser = msg.role === "user";
  const isSystem = msg.role === "system";

  const icon = isUser ? <User size={20} color="#FBBF24" /> : isSystem ? <Wrench size={20} color="#EF4444" /> : <Bot size={20} color="#00E5FF" />;
  const name = isUser ? "You" : isSystem ? "System" : "Aion";
  const bg = isUser ? "rgba(251, 191, 36, 0.05)" : isSystem ? "rgba(239, 68, 68, 0.05)" : "rgba(0, 229, 255, 0.05)";
  const border = isUser ? "#FBBF24" : isSystem ? "#EF4444" : "#00E5FF";

  return (
    <div style={{
      display: "flex",
      gap: 12,
      maxWidth: 1200,
      margin: "0 auto",
      width: "100%",
    }}>
      <div style={{
        width: 36,
        height: 36,
        borderRadius: 8,
        background: bg,
        border: `1px solid ${border}`,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        flexShrink: 0,
      }}>
        {icon}
      </div>
      <div style={{
        flex: 1,
        background: bg,
        border: `1px solid ${border}33`,
        borderRadius: 8,
        padding: "12px 16px",
      }}>
        <div style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          marginBottom: 6,
        }}>
          <span style={{ fontWeight: 600, color: border, fontSize: 13 }}>{name}</span>
          <span style={{ fontSize: 11, color: "#64748b" }}>
            {new Date(msg.timestamp).toLocaleTimeString()}
            {msg.tokens ? ` · ${msg.tokens} tokens` : ""}
          </span>
        </div>
        <div style={{
          fontSize: 14,
          lineHeight: 1.5,
          whiteSpace: "pre-wrap",
          wordBreak: "break-word",
        }}>
          {msg.content}
        </div>
        {msg.tools && msg.tools.length > 0 && (
          <div style={{
            display: "flex",
            gap: 6,
            marginTop: 8,
            flexWrap: "wrap",
          }}>
            {msg.tools.map((t, i) => (
              <span key={i} style={{
                background: "#334155",
                color: "#94a3b8",
                padding: "2px 8px",
                borderRadius: 4,
                fontSize: 11,
                display: "flex",
                alignItems: "center",
                gap: 4,
              }}>
                <Wrench size={10} /> {t}
              </span>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// ── Styles ──────────────────────────────────────────────────────────────

const inputStyle: React.CSSProperties = {
  background: "#0f172a",
  border: "1px solid #334155",
  borderRadius: 6,
  padding: "8px 12px",
  color: "#e2e8f0",
  fontFamily: "inherit",
  fontSize: 14,
  outline: "none",
};

// ── Simulated agent response (frontend-only fallback) ───────────────────

async function simulateAgentResponse(
  userMessage: string,
  config: AgentConfig,
): Promise<ChatMessage> {
  // Simulate network latency
  await new Promise((resolve) => setTimeout(resolve, 800 + Math.random() * 600));

  const lower = userMessage.toLowerCase();
  let content = "";
  let tools: string[] | undefined;

  if (lower.includes("hello") || lower.includes("hi") || lower.includes("hey")) {
    content = `Hello! I'm Aion, running in the **${config.persona}** persona with model **${config.model}**.\n\nI'm currently running in browser-simulation mode (no backend connected). To connect me to a real LLM backend, configure the Aion HTTP API at \`/api/chat\`.\n\nWhat would you like help with?`;
  } else if (lower.includes("what can you do")) {
    content = `I'm Aion Hand — a self-improving autonomous AI agent framework. Here's what I can do:\n\n**Core capabilities:**\n- 🧠 6-layer memory system (working → user profile)\n- 🛠️ 25+ built-in tools (web search, code execution, file I/O, etc.)\n- 📚 93 skills (SKILL.md format, Hermes-compatible)\n- 🎭 21 personas (SOUL.md format, OpenClaw-compatible)\n- 🤖 Multi-agent orchestration with DAG workflows\n- 🔌 MCP client AND server\n- 💬 20+ messaging platform adapters (Telegram, Discord, Slack, etc.)\n- 🔒 Security sandbox with approval modes\n- 📊 Benchmark harness\n- 🎨 Rich TUI + this web interface\n\nAsk me anything!`;
  } else if (lower.includes("search")) {
    tools = ["web_search"];
    content = `I would search the web for "${userMessage}" using my \`web_search\` tool, fetch the top results with \`web_fetch\`, and synthesize an answer with inline citations.\n\nIn simulation mode, I can't actually make HTTP requests. Connect a real backend to enable live web search.`;
  } else {
    content = `You said: "${userMessage}"\n\nI'm running in browser-simulation mode. To get real responses, connect this UI to a running Aion backend:\n\n\`\`\`bash\n# Start the Aion HTTP API server\npython -m aion_core.api.server --port 8000\n\n# Then set NEXT_PUBLIC_API_URL=http://localhost:8000\n\`\`\`\n\nIn the meantime, I'm pretending to respond as the **${config.persona}** persona.`;
  }

  return {
    id: crypto.randomUUID(),
    role: "agent",
    content,
    timestamp: new Date().toISOString(),
    tools,
    tokens: Math.floor(50 + Math.random() * 200),
  };
}
