"use client";

import { useState, useEffect, useRef } from "react";
import {
  Activity,
  Brain,
  Bot,
  Calendar,
  Cpu,
  Flame,
  Gauge,
  MessageSquare,
  Play,
  Plus,
  Search,
  Send,
  Settings,
  Shield,
  Sparkles,
  Terminal,
  Timer,
  Wrench,
  Zap,
  ChevronRight,
  Globe,
  Layers,
  Database,
  Code,
  FileText,
  Image,
  Music,
  Video,
  ClipboardList,
  TrendingUp,
  TrendingDown,
  Eye,
  Target,
  ArrowRight,
  GitBranch,
  DollarSign,
  Server,
  FolderOpen,
  WifiOff,
} from "lucide-react";
import "./page.css";

// ── Types ──────────────────────────────────────────────────────────────────

interface ChatMessage {
  id: number;
  sender: "user" | "agent";
  text: string;
  timestamp: string;
}

interface SubAgent {
  id: string;
  name: string;
  role: string;
  status: "active" | "idle" | "busy";
  progress: number;
  icon: React.ReactNode;
}

interface ToolExecution {
  id: number;
  tool: string;
  action: string;
  duration: string;
  status: "success" | "running" | "error";
  timestamp: string;
}

interface Skill {
  id: number;
  name: string;
  description: string;
  icon: React.ReactNode;
  category: string;
}

interface ScheduledTask {
  id: number;
  title: string;
  time: string;
  agent: string;
  status: "upcoming" | "in-progress" | "completed";
}

// ── Mock Data ─────────────────────────────────────────────────────────────

const initialMessages: ChatMessage[] = [
  {
    id: 1,
    sender: "agent",
    text: "Welcome back! I'm Aion Hand, your AI agent framework. I've completed the code review task you assigned earlier. Found 3 optimizations and 2 potential bugs.",
    timestamp: "2 min ago",
  },
  {
    id: 2,
    sender: "user",
    text: "Great work! Can you apply the optimizations and run the test suite?",
    timestamp: "1 min ago",
  },
  {
    id: 3,
    sender: "agent",
    text: "Already on it! I've spawned a subagent to handle the code patches while another runs the integration tests in parallel. ETA: ~4 minutes.",
    timestamp: "30 sec ago",
  },
];

const subAgents: SubAgent[] = [
  {
    id: "sa-1",
    name: "Code Patcher",
    role: "Applying optimizations",
    status: "active",
    progress: 67,
    icon: <Code size={14} />,
  },
  {
    id: "sa-2",
    name: "Test Runner",
    role: "Integration tests",
    status: "active",
    progress: 42,
    icon: <Terminal size={14} />,
  },
  {
    id: "sa-3",
    name: "Doc Generator",
    role: "Updating API docs",
    status: "idle",
    progress: 0,
    icon: <FileText size={14} />,
  },
  {
    id: "sa-4",
    name: "Sentinel",
    role: "Monitoring system health",
    status: "active",
    progress: 91,
    icon: <Shield size={14} />,
  },
];

const toolExecutions: ToolExecution[] = [
  {
    id: 1,
    tool: "file_search",
    action: 'Found 12 files matching "*.test.ts"',
    duration: "0.8s",
    status: "success",
    timestamp: "Just now",
  },
  {
    id: 2,
    tool: "code_edit",
    action: "Optimized database query in user.ts",
    duration: "1.2s",
    status: "success",
    timestamp: "2m ago",
  },
  {
    id: 3,
    tool: "shell_exec",
    action: "Running npm test -- --coverage",
    duration: "12s",
    status: "running",
    timestamp: "3m ago",
  },
  {
    id: 4,
    tool: "web_scrape",
    action: "Fetched latest docs from API reference",
    duration: "2.1s",
    status: "success",
    timestamp: "5m ago",
  },
  {
    id: 5,
    tool: "memory_store",
    action: "Stored optimization patterns to memory",
    duration: "0.3s",
    status: "success",
    timestamp: "6m ago",
  },
  {
    id: 6,
    tool: "image_gen",
    action: "Generated diagram for architecture review",
    duration: "8.4s",
    status: "error",
    timestamp: "8m ago",
  },
];

const skills: Skill[] = [
  { id: 1, name: "Code Analysis", description: "Static analysis & refactoring", icon: <Code size={18} />, category: "dev" },
  { id: 2, name: "Web Research", description: "Search & extract web data", icon: <Globe size={18} />, category: "search" },
  { id: 3, name: "File Manager", description: "Read, write, transform files", icon: <FileText size={18} />, category: "system" },
  { id: 4, name: "Image Gen", description: "Generate images from prompts", icon: <Image size={18} />, category: "creative" },
  { id: 5, name: "Shell Exec", description: "Run terminal commands", icon: <Terminal size={18} />, category: "system" },
  { id: 6, name: "DB Query", description: "SQL & NoSQL operations", icon: <Database size={18} />, category: "data" },
  { id: 7, name: "Git Ops", description: "Version control operations", icon: <Layers size={18} />, category: "dev" },
  { id: 8, name: "Test Runner", description: "Execute & analyze tests", icon: <Zap size={18} />, category: "dev" },
  { id: 9, name: "Audio Process", description: "Transcribe & generate audio", icon: <Music size={18} />, category: "media" },
  { id: 10, name: "Video Analyze", description: "Extract info from video", icon: <Video size={18} />, category: "media" },
  { id: 11, name: "Data Viz", description: "Charts & data visualization", icon: <TrendingUp size={18} />, category: "data" },
  { id: 12, name: "Task Planner", description: "Schedule & manage tasks", icon: <ClipboardList size={18} />, category: "system" },
];

const scheduledTasks: ScheduledTask[] = [
  { id: 1, title: "Weekly security audit", time: "10:00 AM", agent: "Sentinel", status: "completed" },
  { id: 2, title: "Update dependency versions", time: "11:30 AM", agent: "Code Patcher", status: "completed" },
  { id: 3, title: "Generate quarterly report", time: "2:00 PM", agent: "Doc Generator", status: "in-progress" },
  { id: 4, title: "Deploy staging build", time: "4:00 PM", agent: "Shell Runner", status: "upcoming" },
  { id: 5, title: "Sync knowledge base", time: "6:00 PM", agent: "Memory Agent", status: "upcoming" },
];

const memoryStats = [
  { label: "Short-term", value: 72, color: "from-purple-500 to-purple-400" },
  { label: "Long-term", value: 45, color: "from-cyan-500 to-cyan-400" },
  { label: "Episodic", value: 28, color: "from-emerald-500 to-emerald-400" },
  { label: "Semantic", value: 63, color: "from-amber-500 to-amber-400" },
  { label: "Procedural", value: 55, color: "from-rose-500 to-rose-400" },
];

// ── Dashboard Component ────────────────────────────────────────────────────

export default function Dashboard() {
  const [messages, setMessages] = useState<ChatMessage[]>(initialMessages);
  const [inputValue, setInputValue] = useState("");
  const [isTyping, setIsTyping] = useState(false);
  const [activeTab, setActiveTab] = useState<"subagents" | "tools" | "memory">("subagents");
  const [currentTime, setCurrentTime] = useState(new Date());
  const chatEndRef = useRef<HTMLDivElement>(null);

  // Clock ticker
  useEffect(() => {
    const interval = setInterval(() => setCurrentTime(new Date()), 1000);
    return () => clearInterval(interval);
  }, []);

  // Auto-scroll chat
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isTyping]);

  // Handle sending a message
  const handleSend = () => {
    const text = inputValue.trim();
    if (!text) return;

    const userMsg: ChatMessage = {
      id: messages.length + 1,
      sender: "user",
      text,
      timestamp: "Just now",
    };
    setMessages((prev) => [...prev, userMsg]);
    setInputValue("");
    setIsTyping(true);

    // Simulate agent response
    setTimeout(() => {
      const responses = [
        "I've analyzed your request and I'm initiating the appropriate subagents to handle this task efficiently.",
        "Good question! Let me query my knowledge base and cross-reference with the latest documentation.",
        "I'll process that right away. Spawning a dedicated agent for this operation — ETA is approximately 30 seconds.",
        "Understood. I'm breaking this down into subtasks and distributing them across my available agents.",
        "I've already identified the relevant patterns from memory. Executing the optimal approach now.",
      ];
      const agentMsg: ChatMessage = {
        id: messages.length + 2,
        sender: "agent",
        text: responses[Math.floor(Math.random() * responses.length)],
        timestamp: "Just now",
      };
      setMessages((prev) => [...prev, agentMsg]);
      setIsTyping(false);
    }, 2000 + Math.random() * 1500);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const stats = [
    { label: "Uptime", value: "47h 23m", icon: <Timer size={18} />, trend: "+12%", color: "text-emerald-400" },
    { label: "Memory Used", value: "2.4 GB", icon: <Brain size={18} />, trend: "67%", color: "text-purple-400" },
    { label: "Skills Active", value: "8 / 12", icon: <Sparkles size={18} />, trend: "+2", color: "text-cyan-400" },
    { label: "Tools Available", value: "24", icon: <Wrench size={18} />, trend: "All green", color: "text-amber-400" },
    { label: "Tasks Today", value: "34", icon: <ClipboardList size={18} />, trend: "+8", color: "text-rose-400" },
    { label: "Tokens Used", value: "148.2K", icon: <Gauge size={18} />, trend: "42% budget", color: "text-blue-400" },
  ];

  const quickActions = [
    { label: "New Chat", icon: <MessageSquare size={16} />, gradient: "from-purple-500/20 to-purple-600/10 border-purple-500/20 hover:border-purple-500/40" },
    { label: "Spawn Agent", icon: <Play size={16} />, gradient: "from-cyan-500/20 to-cyan-600/10 border-cyan-500/20 hover:border-cyan-500/40" },
    { label: "Schedule Task", icon: <Calendar size={16} />, gradient: "from-emerald-500/20 to-emerald-600/10 border-emerald-500/20 hover:border-emerald-500/40" },
    { label: "Search Memory", icon: <Search size={16} />, gradient: "from-amber-500/20 to-amber-600/10 border-amber-500/20 hover:border-amber-500/40" },
  ];

  const getStatusColor = (status: string) => {
    switch (status) {
      case "active":
        return "bg-emerald-500";
      case "idle":
        return "bg-amber-500";
      case "busy":
        return "bg-purple-500";
      default:
        return "bg-gray-500";
    }
  };

  const getToolStatusIcon = (status: string) => {
    switch (status) {
      case "success":
        return <Zap size={12} className="text-emerald-400" />;
      case "running":
        return <Activity size={12} className="text-cyan-400 animate-pulse" />;
      case "error":
        return <Flame size={12} className="text-rose-400" />;
      default:
        return null;
    }
  };

  return (
    <div className="min-h-screen px-4 py-6 md:px-6 lg:px-8 max-w-[1600px] mx-auto">
      {/* ── Header ──────────────────────────────────────────────── */}
      <header className="header-gradient glass-card p-6 mb-6 fade-in-up relative overflow-hidden">
        {/* Decorative orbs */}
        <div className="orb orb-purple w-40 h-40 -top-20 -left-20" />
        <div className="orb orb-cyan w-32 h-32 -bottom-16 -right-16" />

        <div className="relative z-10 flex flex-col md:flex-row items-start md:items-center justify-between gap-4">
          <div className="flex items-center gap-4">
            {/* Logo */}
            <div className="relative">
              <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-purple-600 to-cyan-500 flex items-center justify-center shadow-lg shadow-purple-500/20">
                <Bot size={30} className="text-white" />
              </div>
              <div className="absolute -top-1 -right-1 w-4 h-4 rounded-full bg-emerald-500 border-2 border-[#0f0b1e] status-pulse" />
            </div>

            <div>
              <h1 className="text-3xl md:text-4xl font-bold gradient-text tracking-tight">
                Aion Hand
              </h1>
              <p className="text-sm text-[#a1a0ab] mt-0.5">
                AI Agent Framework &middot; Control Center
              </p>
            </div>
          </div>

          {/* Right side info */}
          <div className="flex items-center gap-4">
            {/* Status Badge */}
            <div className="status-badge-active px-4 py-2 rounded-full flex items-center gap-2 text-sm font-medium">
              <span className="w-2 h-2 rounded-full bg-emerald-400 status-pulse" />
              All Systems Online
            </div>

            {/* Time */}
            <div className="glass-card-subtle px-4 py-2 text-sm font-mono text-[#a1a0ab]">
              {currentTime.toLocaleTimeString("en-US", {
                hour: "2-digit",
                minute: "2-digit",
                second: "2-digit",
              })}
            </div>

            {/* Settings */}
            <button className="w-10 h-10 rounded-xl glass-card-subtle flex items-center justify-center hover:bg-white/10 transition-colors">
              <Settings size={18} className="text-[#a1a0ab]" />
            </button>
          </div>
        </div>
      </header>

      {/* ── Stats Grid ──────────────────────────────────────────── */}
      <div className="stats-grid grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4 mb-6">
        {stats.map((stat, i) => (
          <div
            key={stat.label}
            className={`glass-card p-4 fade-in-up fade-in-up-delay-${i + 1}`}
          >
            <div className="flex items-center justify-between mb-3">
              <div className="w-9 h-9 rounded-xl bg-white/5 flex items-center justify-center">
                <span className={stat.color}>{stat.icon}</span>
              </div>
              <span className="text-[10px] uppercase tracking-wider text-emerald-400 font-semibold bg-emerald-400/10 px-2 py-0.5 rounded-full">
                {stat.trend}
              </span>
            </div>
            <div className={`text-2xl font-bold stat-number ${stat.color}`}>
              {stat.value}
            </div>
            <div className="text-xs text-[#6b6a78] mt-1">{stat.label}</div>
          </div>
        ))}
      </div>

      {/* ── Main Dashboard Grid ─────────────────────────────────── */}
      <div className="dashboard-grid grid grid-cols-1 lg:grid-cols-[1fr_420px] gap-6 mb-6">
        {/* ── Left Column: Chat Interface ──────────────────────── */}
        <div className="glass-card flex flex-col h-[560px] fade-in-up fade-in-up-delay-3">
          {/* Chat Header */}
          <div className="px-5 py-4 border-b border-white/5 flex items-center justify-between shrink-0">
            <div className="flex items-center gap-3">
              <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-purple-600/30 to-cyan-500/30 flex items-center justify-center">
                <MessageSquare size={16} className="text-purple-400" />
              </div>
              <div>
                <h2 className="text-sm font-semibold text-[#f1f0f5]">Agent Chat</h2>
                <p className="text-[11px] text-[#6b6a78]">Conversational Interface</p>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <div className="flex -space-x-2">
                {subAgents.slice(0, 3).map((sa) => (
                  <div
                    key={sa.id}
                    className="w-6 h-6 rounded-full bg-white/10 border border-[#0f0b1e] flex items-center justify-center"
                    title={sa.name}
                  >
                    {sa.icon}
                  </div>
                ))}
              </div>
              <span className="text-[11px] text-[#6b6a78]">3 agents active</span>
            </div>
          </div>

          {/* Messages Area */}
          <div className="flex-1 overflow-y-auto scroll-area px-5 py-4 space-y-4">
            {messages.map((msg) => (
              <div
                key={msg.id}
                className={`flex ${msg.sender === "user" ? "justify-end" : "justify-start"} fade-in-up`}
              >
                {msg.sender === "agent" && (
                  <div className="w-7 h-7 rounded-full bg-gradient-to-br from-purple-600 to-cyan-500 flex items-center justify-center mr-3 mt-1 shrink-0">
                    <Bot size={14} className="text-white" />
                  </div>
                )}
                <div className="max-w-[80%]">
                  <div
                    className={`px-4 py-3 text-sm leading-relaxed ${
                      msg.sender === "user" ? "chat-bubble-user" : "chat-bubble-agent"
                    }`}
                  >
                    {msg.text}
                  </div>
                  <div
                    className={`text-[10px] text-[#6b6a78] mt-1 ${
                      msg.sender === "user" ? "text-right mr-1" : "ml-1"
                    }`}
                  >
                    {msg.timestamp}
                  </div>
                </div>
              </div>
            ))}

            {/* Typing indicator */}
            {isTyping && (
              <div className="flex justify-start fade-in-up">
                <div className="w-7 h-7 rounded-full bg-gradient-to-br from-purple-600 to-cyan-500 flex items-center justify-center mr-3 mt-1 shrink-0">
                  <Bot size={14} className="text-white" />
                </div>
                <div className="chat-bubble-agent px-4 py-3 flex items-center gap-1.5">
                  <div className="typing-dot w-2 h-2 rounded-full bg-purple-400" />
                  <div className="typing-dot w-2 h-2 rounded-full bg-purple-400" />
                  <div className="typing-dot w-2 h-2 rounded-full bg-purple-400" />
                </div>
              </div>
            )}
            <div ref={chatEndRef} />
          </div>

          {/* Chat Input */}
          <div className="px-5 py-4 border-t border-white/5 shrink-0">
            <div className="flex items-center gap-3">
              <div className="flex-1 relative">
                <input
                  type="text"
                  value={inputValue}
                  onChange={(e) => setInputValue(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder="Send a message to Aion Hand..."
                  className="w-full bg-white/5 border border-white/10 rounded-xl px-4 py-3 text-sm text-[#f1f0f5] placeholder-[#6b6a78] outline-none input-glow transition-all duration-300"
                />
              </div>
              <button
                onClick={handleSend}
                disabled={!inputValue.trim()}
                className="w-11 h-11 rounded-xl bg-gradient-to-br from-purple-600 to-purple-500 flex items-center justify-center hover:from-purple-500 hover:to-purple-400 disabled:opacity-30 disabled:cursor-not-allowed transition-all duration-200 shadow-lg shadow-purple-500/20 hover:shadow-purple-500/40"
              >
                <Send size={16} className="text-white" />
              </button>
            </div>
            <div className="flex items-center gap-2 mt-2">
              <span className="text-[10px] text-[#6b6a78]">Quick:</span>
              {["Analyze code", "Search memory", "Status report"].map((q) => (
                <button
                  key={q}
                  onClick={() => setInputValue(q)}
                  className="text-[10px] text-purple-400/70 bg-purple-500/10 hover:bg-purple-500/20 px-2.5 py-0.5 rounded-full transition-colors border border-purple-500/10 hover:border-purple-500/20"
                >
                  {q}
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* ── Right Column: Agent Activity Panel ────────────────── */}
        <div className="flex flex-col gap-6">
          {/* Tabs + Content */}
          <div className="glass-card flex flex-col h-[560px] fade-in-up fade-in-up-delay-4">
            {/* Tab Bar */}
            <div className="px-4 pt-4 pb-0 flex items-center gap-1 border-b border-white/5 shrink-0">
              {[
                { key: "subagents" as const, label: "Subagents", icon: <Layers size={13} /> },
                { key: "tools" as const, label: "Tool Log", icon: <Wrench size={13} /> },
                { key: "memory" as const, label: "Memory", icon: <Brain size={13} /> },
              ].map((tab) => (
                <button
                  key={tab.key}
                  onClick={() => setActiveTab(tab.key)}
                  className={`flex items-center gap-1.5 px-3 py-2.5 text-xs font-medium rounded-t-lg transition-all duration-200 ${
                    activeTab === tab.key
                      ? "text-purple-300 bg-white/5 border-b-2 border-purple-500"
                      : "text-[#6b6a78] hover:text-[#a1a0ab] hover:bg-white/3"
                  }`}
                >
                  {tab.icon}
                  {tab.label}
                </button>
              ))}
            </div>

            {/* Tab Content */}
            <div className="flex-1 overflow-y-auto scroll-area px-4 py-4">
              {/* Subagents Tab */}
              {activeTab === "subagents" && (
                <div className="space-y-3">
                  {subAgents.map((agent) => (
                    <div key={agent.id} className="glass-card-subtle p-3 hover:bg-white/5">
                      <div className="flex items-center justify-between mb-2">
                        <div className="flex items-center gap-2.5">
                          <div
                            className={`w-8 h-8 rounded-lg flex items-center justify-center ${
                              agent.status === "active"
                                ? "bg-purple-500/20 text-purple-400"
                                : agent.status === "idle"
                                ? "bg-amber-500/20 text-amber-400"
                                : "bg-cyan-500/20 text-cyan-400"
                            }`}
                          >
                            {agent.icon}
                          </div>
                          <div>
                            <div className="text-sm font-medium text-[#f1f0f5]">{agent.name}</div>
                            <div className="text-[11px] text-[#6b6a78]">{agent.role}</div>
                          </div>
                        </div>
                        <div className="flex items-center gap-1.5">
                          <span className={`w-1.5 h-1.5 rounded-full ${getStatusColor(agent.status)} ${agent.status === "active" ? "status-pulse" : ""}`} />
                          <span className="text-[10px] uppercase tracking-wider text-[#6b6a78]">
                            {agent.status}
                          </span>
                        </div>
                      </div>
                      {agent.status === "active" && (
                        <div className="mt-2">
                          <div className="flex justify-between text-[10px] text-[#6b6a78] mb-1">
                            <span>Progress</span>
                            <span>{agent.progress}%</span>
                          </div>
                          <div className="w-full h-1.5 bg-white/5 rounded-full overflow-hidden">
                            <div
                              className="subagent-bar h-full bg-gradient-to-r from-purple-500 to-cyan-400 rounded-full"
                              style={{ width: `${agent.progress}%` }}
                            />
                          </div>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}

              {/* Tools Tab */}
              {activeTab === "tools" && (
                <div className="space-y-1">
                  {toolExecutions.map((tool) => (
                    <div
                      key={tool.id}
                      className="tool-log-entry flex items-start gap-3 px-3 py-2.5 rounded-lg cursor-default"
                    >
                      <div className="w-7 h-7 rounded-lg bg-white/5 flex items-center justify-center shrink-0 mt-0.5">
                        {getToolStatusIcon(tool.status)}
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="text-xs font-mono font-medium text-purple-300">
                            {tool.tool}
                          </span>
                          <span className="text-[10px] text-[#6b6a78]">{tool.duration}</span>
                        </div>
                        <div className="text-[11px] text-[#a1a0ab] mt-0.5 truncate">{tool.action}</div>
                      </div>
                      <span className="text-[10px] text-[#6b6a78] shrink-0 mt-1">{tool.timestamp}</span>
                    </div>
                  ))}
                </div>
              )}

              {/* Memory Tab */}
              {activeTab === "memory" && (
                <div className="space-y-4">
                  <div className="glass-card-subtle p-4 mb-4">
                    <div className="flex items-center justify-between mb-3">
                      <h3 className="text-sm font-medium text-[#f1f0f5]">Memory Overview</h3>
                      <span className="text-[10px] text-emerald-400 bg-emerald-400/10 px-2 py-0.5 rounded-full">
                        Healthy
                      </span>
                    </div>
                    <div className="flex items-center gap-3">
                      <div className="relative w-20 h-20">
                        <svg className="w-20 h-20 -rotate-90" viewBox="0 0 36 36">
                          <path
                            d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831"
                            fill="none"
                            stroke="rgba(255,255,255,0.05)"
                            strokeWidth="3"
                          />
                          <path
                            d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831"
                            fill="none"
                            stroke="url(#memoryGradient)"
                            strokeWidth="3"
                            strokeDasharray="72, 100"
                            strokeLinecap="round"
                          />
                          <defs>
                            <linearGradient id="memoryGradient" x1="0%" y1="0%" x2="100%" y2="0%">
                              <stop offset="0%" stopColor="#7c3aed" />
                              <stop offset="100%" stopColor="#06b6d4" />
                            </linearGradient>
                          </defs>
                        </svg>
                        <div className="absolute inset-0 flex items-center justify-center">
                          <span className="text-sm font-bold text-[#f1f0f5]">72%</span>
                        </div>
                      </div>
                      <div className="flex-1">
                        <div className="text-xs text-[#6b6a78]">Total Memory</div>
                        <div className="text-lg font-bold text-[#f1f0f5]">2.4 GB</div>
                        <div className="text-[11px] text-[#a1a0ab] mt-0.5">of 4.0 GB allocated</div>
                      </div>
                    </div>
                  </div>

                  <h4 className="text-xs font-semibold text-[#a1a0ab] uppercase tracking-wider px-1">
                    Memory Types
                  </h4>
                  {memoryStats.map((stat) => (
                    <div key={stat.label} className="px-1">
                      <div className="flex items-center justify-between mb-1.5">
                        <span className="text-xs text-[#a1a0ab]">{stat.label}</span>
                        <span className="text-xs font-mono text-[#6b6a78]">{stat.value}%</span>
                      </div>
                      <div className="w-full h-2 bg-white/5 rounded-full overflow-hidden">
                        <div
                          className={`memory-bar h-full bg-gradient-to-r ${stat.color}`}
                          style={{ width: `${stat.value}%` }}
                        />
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* Quick Actions */}
          <div className="grid grid-cols-2 gap-3 fade-in-up fade-in-up-delay-5">
            {quickActions.map((action) => (
              <button
                key={action.label}
                className={`quick-action glass-card-subtle p-3.5 flex items-center gap-2.5 bg-gradient-to-br ${action.gradient} border text-left`}
              >
                <span className="text-purple-300">{action.icon}</span>
                <span className="text-xs font-medium text-[#f1f0f5]">{action.label}</span>
                <ChevronRight size={12} className="text-[#6b6a78] ml-auto" />
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* ── Bottom Section ───────────────────────────────────────── */}
      <div className="grid grid-cols-1 lg:grid-cols-[1fr_380px] gap-6">
        {/* Skills Carousel */}
        <div className="glass-card p-5 fade-in-up fade-in-up-delay-5">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-2.5">
              <div className="w-8 h-8 rounded-lg bg-purple-500/15 flex items-center justify-center">
                <Sparkles size={16} className="text-purple-400" />
              </div>
              <div>
                <h3 className="text-sm font-semibold text-[#f1f0f5]">Available Skills</h3>
                <p className="text-[11px] text-[#6b6a78]">12 skills loaded &middot; 8 active</p>
              </div>
            </div>
            <button className="text-xs text-purple-400 hover:text-purple-300 bg-purple-500/10 hover:bg-purple-500/20 px-3 py-1.5 rounded-lg transition-colors flex items-center gap-1">
              <Plus size={12} />
              Install Skill
            </button>
          </div>

          <div className="overflow-hidden relative">
            {/* Fade edges */}
            <div className="absolute left-0 top-0 bottom-0 w-12 bg-gradient-to-r from-[#0f0b1e] to-transparent z-10 pointer-events-none" />
            <div className="absolute right-0 top-0 bottom-0 w-12 bg-gradient-to-l from-[#0f0b1e] to-transparent z-10 pointer-events-none" />

            <div className="overflow-hidden">
              <div className="skills-track">
                {/* Double the skills for infinite scroll */}
                {[...skills, ...skills].map((skill, idx) => (
                  <div
                    key={`${skill.id}-${idx}`}
                    className="shrink-0 w-[160px] glass-card-subtle p-3.5 cursor-pointer group"
                  >
                    <div className="w-10 h-10 rounded-xl bg-white/5 flex items-center justify-center mb-3 group-hover:bg-purple-500/15 transition-colors">
                      <span className="text-[#a1a0ab] group-hover:text-purple-400 transition-colors">
                        {skill.icon}
                      </span>
                    </div>
                    <div className="text-xs font-semibold text-[#f1f0f5] group-hover:text-purple-300 transition-colors">
                      {skill.name}
                    </div>
                    <div className="text-[10px] text-[#6b6a78] mt-0.5 leading-tight">
                      {skill.description}
                    </div>
                    <div className="mt-2 flex items-center gap-1">
                      <span
                        className={`w-1.5 h-1.5 rounded-full ${
                          idx % 3 === 0
                            ? "bg-emerald-500"
                            : idx % 3 === 1
                            ? "bg-purple-500"
                            : "bg-gray-600"
                        }`}
                      />
                      <span className="text-[10px] text-[#6b6a78] capitalize">{skill.category}</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>

        {/* Scheduled Tasks Timeline */}
        <div className="glass-card p-5 fade-in-up fade-in-up-delay-6">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-2.5">
              <div className="w-8 h-8 rounded-lg bg-cyan-500/15 flex items-center justify-center">
                <Calendar size={16} className="text-cyan-400" />
              </div>
              <div>
                <h3 className="text-sm font-semibold text-[#f1f0f5]">Today&apos;s Schedule</h3>
                <p className="text-[11px] text-[#6b6a78]">2 completed &middot; 1 in progress</p>
              </div>
            </div>
            <button className="text-xs text-cyan-400 hover:text-cyan-300 bg-cyan-500/10 hover:bg-cyan-500/20 px-3 py-1.5 rounded-lg transition-colors flex items-center gap-1">
              <Plus size={12} />
              New Task
            </button>
          </div>

          <div className="space-y-0">
            {scheduledTasks.map((task, idx) => (
              <div key={task.id} className={`timeline-connector flex items-start gap-3 pb-5 ${idx === scheduledTasks.length - 1 ? 'last:!pb-0' : ''}`}>
                {/* Timeline dot */}
                <div className="relative shrink-0 mt-0.5">
                  <div
                    className={`w-6 h-6 rounded-full flex items-center justify-center ${
                      task.status === "completed"
                        ? "bg-emerald-500/20 border border-emerald-500/30"
                        : task.status === "in-progress"
                        ? "bg-cyan-500/20 border border-cyan-500/30"
                        : "bg-white/5 border border-white/10"
                    }`}
                  >
                    {task.status === "completed" ? (
                      <Zap size={10} className="text-emerald-400" />
                    ) : task.status === "in-progress" ? (
                      <Activity size={10} className="text-cyan-400 animate-pulse" />
                    ) : (
                      <Eye size={10} className="text-[#6b6a78]" />
                    )}
                  </div>
                </div>

                {/* Task content */}
                <div className="flex-1 min-w-0">
                  <div className="flex items-center justify-between">
                    <span
                      className={`text-xs font-medium ${
                        task.status === "completed"
                          ? "text-[#6b6a78] line-through"
                          : "text-[#f1f0f5]"
                      }`}
                    >
                      {task.title}
                    </span>
                    <span className="text-[10px] font-mono text-[#6b6a78] shrink-0 ml-2">
                      {task.time}
                    </span>
                  </div>
                  <div className="text-[10px] text-[#6b6a78] mt-0.5">
                    Agent: <span className="text-purple-400/70">{task.agent}</span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* ── Pipeline Visualization ────────────────────────────── */}
      <div className="glass-card p-5 fade-in-up mb-6">
        <div className="flex items-center gap-2.5 mb-5">
          <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-purple-500/20 to-cyan-500/20 flex items-center justify-center">
            <GitBranch size={16} className="text-purple-400" />
          </div>
          <div>
            <h3 className="text-sm font-semibold text-[#f1f0f5]">9-Stage Pipeline</h3>
            <p className="text-[11px] text-[#6b6a78]">Mission → Plan → Execute → Verify → Critic → Repair → Confidence → Learn → Output</p>
          </div>
        </div>
        <div className="flex items-center gap-1.5 overflow-x-auto pb-2">
          {[
            { icon: <Target size={14} />, label: "Mission", active: true },
            { icon: <ClipboardList size={14} />, label: "Plan", active: true },
            { icon: <Play size={14} />, label: "Execute", active: true },
            { icon: <Eye size={14} />, label: "Verify", active: false },
            { icon: <MessageSquare size={14} />, label: "Critic", active: false },
            { icon: <Wrench size={14} />, label: "Repair", active: false },
            { icon: <Shield size={14} />, label: "Confidence", active: false },
            { icon: <Brain size={14} />, label: "Learn", active: false },
            { icon: <FileText size={14} />, label: "Output", active: false },
          ].map((stage, idx) => (
            <div key={stage.label} className="flex items-center gap-1.5 shrink-0">
              <div
                className={`flex items-center gap-1.5 px-3 py-2 rounded-lg border transition-all duration-300 ${
                  stage.active
                    ? "bg-purple-500/15 border-purple-500/30 text-purple-300 shadow-lg shadow-purple-500/10"
                    : "bg-white/5 border-white/10 text-[#6b6a78] hover:bg-white/8 hover:border-white/15"
                }`}
              >
                <span className={stage.active ? "text-purple-400" : "text-[#6b6a78]"}>{stage.icon}</span>
                <span className="text-[11px] font-medium whitespace-nowrap">{stage.label}</span>
              </div>
              {idx < 8 && (
                <ArrowRight
                  size={12}
                  className={`shrink-0 ${stage.active ? "text-purple-500 animate-pulse" : "text-white/15"}`}
                />
              )}
            </div>
          ))}
        </div>
      </div>

      {/* ── Benchmark Results ──────────────────────────────────── */}
      <div className="mb-6">
        <div className="flex items-center gap-2.5 mb-4">
          <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-cyan-500/20 to-purple-500/20 flex items-center justify-center">
            <TrendingUp size={16} className="text-cyan-400" />
          </div>
          <div>
            <h3 className="text-sm font-semibold text-[#f1f0f5]">Benchmark Results</h3>
            <p className="text-[11px] text-[#6b6a78]">AgentForge eval suite v2.1</p>
          </div>
        </div>
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
          {[
            { category: "Planning", score: 92, trend: "up" },
            { category: "Tool Use", score: 88, trend: "up" },
            { category: "Code Gen", score: 95, trend: "up" },
            { category: "Recovery", score: 85, trend: "down" },
            { category: "Memory", score: 90, trend: "up" },
            { category: "Multi-Step", score: 87, trend: "down" },
          ].map((bench) => (
            <div
              key={bench.category}
              className="glass-card-subtle bg-white/5 backdrop-blur border border-white/10 p-4 rounded-xl hover:bg-white/8 transition-all duration-200"
            >
              <div className="flex items-center justify-between mb-3">
                <span className="text-xs font-medium text-[#a1a0ab]">{bench.category}</span>
                <span
                  className={`flex items-center text-[10px] font-medium ${
                    bench.trend === "up" ? "text-emerald-400" : "text-rose-400"
                  }`}
                >
                  {bench.trend === "up" ? <TrendingUp size={12} /> : <TrendingDown size={12} />}
                </span>
              </div>
              <div className="flex items-center justify-center">
                <div className="relative w-14 h-14">
                  <svg className="w-14 h-14 -rotate-90" viewBox="0 0 36 36">
                    <path
                      d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831"
                      fill="none"
                      stroke="rgba(255,255,255,0.05)"
                      strokeWidth="3"
                    />
                    <path
                      d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831"
                      fill="none"
                      stroke={bench.score >= 90 ? "#7c3aed" : bench.score >= 85 ? "#06b6d4" : "#f59e0b"}
                      strokeWidth="3"
                      strokeDasharray={`${bench.score}, 100`}
                      strokeLinecap="round"
                    />
                  </svg>
                  <div className="absolute inset-0 flex items-center justify-center">
                    <span className="text-xs font-bold text-[#f1f0f5]">{bench.score}%</span>
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* ── Knowledge Graph Stats ──────────────────────────────── */}
      <div className="grid grid-cols-1 lg:grid-cols-[1fr_320px] gap-6 mb-6">
        <div className="grid grid-cols-3 gap-3">
          {[
            { label: "Entities", value: "2,847", icon: <Database size={18} />, color: "text-purple-400", bg: "from-purple-500/15 to-purple-600/5" },
            { label: "Relations", value: "12,340", icon: <GitBranch size={18} />, color: "text-cyan-400", bg: "from-cyan-500/15 to-cyan-600/5" },
            { label: "Patterns", value: "156", icon: <Layers size={18} />, color: "text-emerald-400", bg: "from-emerald-500/15 to-emerald-600/5" },
          ].map((stat) => (
            <div
              key={stat.label}
              className="glass-card-subtle bg-white/5 backdrop-blur border border-white/10 p-5 rounded-xl"
            >
              <div className={`w-10 h-10 rounded-xl bg-gradient-to-br ${stat.bg} flex items-center justify-center mb-3`}>
                <span className={stat.color}>{stat.icon}</span>
              </div>
              <div className={`text-xl font-bold stat-number ${stat.color}`}>{stat.value}</div>
              <div className="text-[11px] text-[#6b6a78] mt-1">{stat.label}</div>
            </div>
          ))}
        </div>

        {/* Mini bar chart - Entity type distribution */}
        <div className="glass-card-subtle bg-white/5 backdrop-blur border border-white/10 p-5 rounded-xl">
          <div className="text-xs font-medium text-[#a1a0ab] mb-4">Entity Type Distribution</div>
          <div className="space-y-3">
            {[
              { type: "Concepts", pct: 72, color: "from-purple-500 to-purple-400" },
              { type: "Agents", pct: 54, color: "from-cyan-500 to-cyan-400" },
              { type: "Tools", pct: 41, color: "from-emerald-500 to-emerald-400" },
              { type: "Tasks", pct: 33, color: "from-amber-500 to-amber-400" },
              { type: "Memories", pct: 28, color: "from-rose-500 to-rose-400" },
            ].map((item) => (
              <div key={item.type}>
                <div className="flex items-center justify-between mb-1">
                  <span className="text-[11px] text-[#a1a0ab]">{item.type}</span>
                  <span className="text-[10px] font-mono text-[#6b6a78]">{item.pct}%</span>
                </div>
                <div className="w-full h-2 bg-white/5 rounded-full overflow-hidden">
                  <div
                    className="memory-bar h-full bg-gradient-to-r rounded-full"
                    style={{ width: `${item.pct}%` }}
                    >
                    <div className={`h-full w-full bg-gradient-to-r ${item.color} rounded-full`} />
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* ── Model Router + MCP Servers ─────────────────────────── */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
        {/* Model Router Panel */}
        <div className="glass-card-subtle bg-white/5 backdrop-blur border border-white/10 p-5 rounded-xl">
          <div className="flex items-center gap-2.5 mb-5">
            <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-purple-500/20 to-cyan-500/20 flex items-center justify-center">
              <Cpu size={16} className="text-purple-400" />
            </div>
            <div>
              <h3 className="text-sm font-semibold text-[#f1f0f5]">Model Router</h3>
              <p className="text-[11px] text-[#6b6a78]">Current routing decision</p>
            </div>
          </div>

          {/* Selected model card */}
          <div className="bg-white/5 border border-white/10 rounded-xl p-4 mb-4">
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-2.5">
                <div className="w-8 h-8 rounded-lg bg-purple-500/20 flex items-center justify-center">
                  <Sparkles size={14} className="text-purple-400" />
                </div>
                <div>
                  <div className="text-sm font-medium text-[#f1f0f5]">GPT-4o</div>
                  <div className="text-[10px] text-[#6b6a78]">Standard tier</div>
                </div>
              </div>
              <span className="text-[10px] px-2 py-0.5 rounded-full bg-emerald-400/10 text-emerald-400 font-medium border border-emerald-400/20">Selected</span>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="bg-white/5 rounded-lg p-3">
                <div className="flex items-center gap-1.5 mb-1">
                  <DollarSign size={11} className="text-amber-400" />
                  <span className="text-[10px] text-[#6b6a78]">Cost</span>
                </div>
                <span className="text-sm font-bold text-[#f1f0f5]">$0.03</span>
                <span className="text-[10px] text-[#6b6a78]"> / request</span>
              </div>
              <div className="bg-white/5 rounded-lg p-3">
                <div className="flex items-center gap-1.5 mb-1">
                  <Timer size={11} className="text-cyan-400" />
                  <span className="text-[10px] text-[#6b6a78]">Latency</span>
                </div>
                <span className="text-sm font-bold text-[#f1f0f5]">1.2s</span>
                <span className="text-[10px] text-[#6b6a78]"> avg</span>
              </div>
            </div>
          </div>

          {/* Budget bar */}
          <div>
            <div className="flex items-center justify-between mb-2">
              <span className="text-[11px] text-[#a1a0ab]">Daily Budget</span>
              <span className="text-[11px] font-mono text-[#6b6a78]">34% used</span>
            </div>
            <div className="w-full h-2.5 bg-white/5 rounded-full overflow-hidden">
              <div className="h-full rounded-full bg-gradient-to-r from-purple-500 to-cyan-400 transition-all duration-500" style={{ width: "34%" }} />
            </div>
            <div className="flex items-center justify-between mt-1.5">
              <span className="text-[10px] text-[#6b6a78]">$3.40 of $10.00</span>
              <span className="text-[10px] text-emerald-400">$6.60 remaining</span>
            </div>
          </div>
        </div>

        {/* MCP Servers */}
        <div className="glass-card-subtle bg-white/5 backdrop-blur border border-white/10 p-5 rounded-xl">
          <div className="flex items-center gap-2.5 mb-5">
            <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-cyan-500/20 to-purple-500/20 flex items-center justify-center">
              <Server size={16} className="text-cyan-400" />
            </div>
            <div>
              <h3 className="text-sm font-semibold text-[#f1f0f5]">MCP Servers</h3>
              <p className="text-[11px] text-[#6b6a78]">2 connected &middot; 1 disconnected</p>
            </div>
          </div>

          <div className="space-y-3">
            {/* Filesystem */}
            <div className="bg-white/5 border border-white/10 rounded-xl p-4 hover:bg-white/8 transition-all duration-200">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-xl bg-emerald-500/15 flex items-center justify-center">
                    <FolderOpen size={18} className="text-emerald-400" />
                  </div>
                  <div>
                    <div className="text-sm font-medium text-[#f1f0f5]">Filesystem</div>
                    <div className="text-[10px] text-[#6b6a78]">Local file operations</div>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-[10px] px-2 py-0.5 rounded-full bg-white/5 text-[#6b6a78] border border-white/10">5 tools</span>
                  <span className="w-2.5 h-2.5 rounded-full bg-emerald-500 status-pulse" />
                </div>
              </div>
            </div>

            {/* GitHub */}
            <div className="bg-white/5 border border-white/10 rounded-xl p-4 hover:bg-white/8 transition-all duration-200">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-xl bg-rose-500/15 flex items-center justify-center">
                    <WifiOff size={18} className="text-rose-400" />
                  </div>
                  <div>
                    <div className="text-sm font-medium text-[#f1f0f5]">GitHub</div>
                    <div className="text-[10px] text-[#6b6a78]">Repository management</div>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-[10px] px-2 py-0.5 rounded-full bg-white/5 text-[#6b6a78] border border-white/10">— tools</span>
                  <span className="w-2.5 h-2.5 rounded-full bg-rose-500" />
                </div>
              </div>
            </div>

            {/* Browser */}
            <div className="bg-white/5 border border-white/10 rounded-xl p-4 hover:bg-white/8 transition-all duration-200">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 rounded-xl bg-emerald-500/15 flex items-center justify-center">
                    <Globe size={18} className="text-emerald-400" />
                  </div>
                  <div>
                    <div className="text-sm font-medium text-[#f1f0f5]">Browser</div>
                    <div className="text-[10px] text-[#6b6a78]">Web browsing & scraping</div>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-[10px] px-2 py-0.5 rounded-full bg-white/5 text-[#6b6a78] border border-white/10">3 tools</span>
                  <span className="w-2.5 h-2.5 rounded-full bg-emerald-500 status-pulse" />
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* ── Footer ──────────────────────────────────────────────── */}
      <footer className="mt-8 pb-4 text-center">
        <div className="flex items-center justify-center gap-2 text-[11px] text-[#6b6a78]">
          <Cpu size={12} className="text-purple-500/40" />
          <span>
            Aion Hand v0.1.0 &middot; Built with Next.js 15 &middot; AI Agent Framework
          </span>
          <Cpu size={12} className="text-cyan-500/40" />
        </div>
      </footer>
    </div>
  );
}
