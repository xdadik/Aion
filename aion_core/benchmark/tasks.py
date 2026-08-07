"""""
Aion Hand Benchmark Tasks

20+ benchmark tasks across 6 categories that stress-test every dimension of agent capability.
Each task carries a real prompt, concrete evaluation criteria, and resource limits.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List


class Category(Enum):
    PLANNING = "planning"
    TOOL_USE = "tool_use"
    CODE_GENERATION = "code_generation"
    RECOVERY = "recovery"
    MEMORY = "memory"
    MULTI_STEP = "multi_step"


class Difficulty(Enum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"
    EXPERT = "expert"


@dataclass
class BenchmarkTask:
    """A single benchmark task with full specification."""

    id: str
    name: str
    category: Category
    difficulty: Difficulty
    description: str
    task_prompt: str
    evaluation_criteria: list[str]  # Each criterion is a check descriptor
    expected_tools: list[str] = field(default_factory=list)
    expected_steps: int = 1
    max_turns: int = 10
    max_tokens: int = 4096
    timeout: float = 60.0
    tags: list[str] = field(default_factory=list)

    def __post_init__(self):
        if not self.id:
            raise ValueError("Task must have a non-empty id")
        if not self.task_prompt:
            raise ValueError(f"Task {self.id} must have a non-empty task_prompt")
        if not self.evaluation_criteria:
            raise ValueError(f"Task {self.id} must have at least one evaluation criterion")


# ─── Planning Tasks ──────────────────────────────────────────────────────────

PLANNING_TASKS = [
    BenchmarkTask(
        id="plan-001",
        name="Multi-Step Research Plan",
        category=Category.PLANNING,
        difficulty=Difficulty.MEDIUM,
        description="Create a structured research plan for investigating a technical topic with dependencies.",
        task_prompt=(
            "Create a detailed research plan for investigating the performance characteristics of "
            "Rust's async runtime (Tokio) compared to Go's goroutine scheduler. The plan should include: "
            "1) At least 5 specific sub-topics to investigate, 2) Dependencies between sub-topics, "
            "3) Recommended tools/data sources for each, 4) A timeline with phases, "
            "5) Expected deliverables for each phase."
        ),
        evaluation_criteria=[
            "min_length:200",
            'keywords:Tokio,goroutine,scheduler',
            "has_code:false",
            "min_length:400",
        ],
        expected_tools=[],
        expected_steps=3,
        max_turns=5,
        max_tokens=2048,
        timeout=30.0,
        tags=["planning", "research"],
    ),
    BenchmarkTask(
        id="plan-002",
        name="Trip Planning with Constraints",
        category=Category.PLANNING,
        difficulty=Difficulty.MEDIUM,
        description="Plan a multi-city trip with budget and time constraints.",
        task_prompt=(
            "Plan a 7-day trip to Japan for a software engineer with a $3000 budget. Requirements: "
            "1) Visit at least 3 cities (Tokyo, Kyoto, Osaka), 2) Include tech-related attractions "
            "(Akihabara, teamLab, Nintendo Store), 3) Budget breakdown for accommodation, food, transport, "
            "4) Daily itinerary with time slots, 5) JR Pass cost-benefit analysis. "
            "Format as a structured day-by-day plan."
        ),
        evaluation_criteria=[
            "min_length:300",
            'keywords:Tokyo,Kyoto,Osaka',
            'keywords:budget,itinerary',
            r"pattern_match:\$\d{3,4}",
        ],
        expected_tools=[],
        expected_steps=2,
        max_turns=5,
        max_tokens=2048,
        timeout=30.0,
        tags=["planning", "travel"],
    ),
    BenchmarkTask(
        id="plan-003",
        name="Project Architecture Design",
        category=Category.PLANNING,
        difficulty=Difficulty.HARD,
        description="Design system architecture for a real-time collaborative editor.",
        task_prompt=(
            "Design the system architecture for a real-time collaborative code editor (like Google Docs but for code). "
            "Include: 1) High-level component diagram description, 2) Data flow for real-time sync, "
            "3) Conflict resolution strategy (CRDT vs OT), 4) Technology stack recommendations with justifications, "
            "5) Scalability considerations for 10,000 concurrent users, "
            "6) API endpoint design for the collaboration service."
        ),
        evaluation_criteria=[
            "min_length:500",
            'keywords:CRDT,OT,WebSocket,real-time',
            'keywords:scalability,concurrent',
            "min_length:300",
        ],
        expected_tools=[],
        expected_steps=3,
        max_turns=8,
        max_tokens=4096,
        timeout=60.0,
        tags=["planning", "architecture", "system-design"],
    ),
]


# ─── Tool Use Tasks ──────────────────────────────────────────────────────────

TOOL_USE_TASKS = [
    BenchmarkTask(
        id="tool-001",
        name="File Operations Pipeline",
        category=Category.TOOL_USE,
        difficulty=Difficulty.EASY,
        description="Create, write, read, and delete files using file tools.",
        task_prompt=(
            "Perform the following file operations in order: "
            "1) Create a directory called 'benchmark_test', "
            "2) Write a file 'benchmark_test/data.txt' with the content 'Hello from benchmark', "
            "3) Read the file back and confirm the content, "
            "4) List the directory contents, "
            "5) Delete the file and directory. Report the result of each step."
        ),
        evaluation_criteria=[
            "tool_used:file_write",
            "tool_used:file_read",
            "tool_used:file_list",
            "min_length:100",
        ],
        expected_tools=["file_write", "file_read", "file_list"],
        expected_steps=5,
        max_turns=10,
        max_tokens=2048,
        timeout=30.0,
        tags=["tools", "files"],
    ),
    BenchmarkTask(
        id="tool-002",
        name="Web Search and Summarize",
        category=Category.TOOL_USE,
        difficulty=Difficulty.MEDIUM,
        description="Search the web for a topic and produce a structured summary.",
        task_prompt=(
            "Search the web for 'Python 3.13 new features' and provide a structured summary that includes: "
            "1) A list of at least 3 major new features, 2) For each feature, a brief explanation and practical example, "
            "3) Potential breaking changes, 4) Your assessment of which feature is most impactful."
        ),
        evaluation_criteria=[
            "tool_used:web_search",
            "min_length:200",
            'keywords:Python,feature',
            r"pattern_match:\d+\.\d+",
        ],
        expected_tools=["web_search"],
        expected_steps=2,
        max_turns=6,
        max_tokens=3072,
        timeout=45.0,
        tags=["tools", "web", "search"],
    ),
    BenchmarkTask(
        id="tool-003",
        name="Calculator Chain",
        category=Category.TOOL_USE,
        difficulty=Difficulty.EASY,
        description="Use a calculator tool to solve a multi-step math problem.",
        task_prompt=(
            "Using the calculator tool, solve this problem step by step: "
            "A company has 150 employees. The average salary is $75,000. "
            "They want to give a 4% raise to employees with 5+ years experience (60% of staff) "
            "and a 2% raise to the rest. Calculate: 1) Total current payroll, "
            "2) New payroll after raises, 3) Total increase amount, 4) Average raise per employee."
        ),
        evaluation_criteria=[
            "tool_used:calculator",
            r"pattern_match:\$[\d,]+\.\d{2}",
            "min_length:100",
        ],
        expected_tools=["calculator"],
        expected_steps=4,
        max_turns=8,
        max_tokens=2048,
        timeout=30.0,
        tags=["tools", "math", "calculator"],
    ),
    BenchmarkTask(
        id="tool-004",
        name="Multi-Tool Data Pipeline",
        category=Category.TOOL_USE,
        difficulty=Difficulty.HARD,
        description="Chain multiple tools to fetch, process, and store data.",
        task_prompt=(
            "Build a small data pipeline: 1) Use web_search to find the current top 5 programming languages "
            "by TIOBE index, 2) For each language, use web_search to find its primary use case, "
            "3) Write the results to a file called 'language_report.md' in Markdown table format, "
            "4) Read the file back to verify. Report the final table."
        ),
        evaluation_criteria=[
            "tool_used:web_search",
            "tool_used:file_write",
            "tool_used:file_read",
            "min_length:200",
            'keywords:Python,Java,C',
        ],
        expected_tools=["web_search", "file_write", "file_read"],
        expected_steps=4,
        max_turns=15,
        max_tokens=4096,
        timeout=90.0,
        tags=["tools", "pipeline", "web", "files"],
    ),
]


# ─── Code Generation Tasks ───────────────────────────────────────────────────

CODE_GENERATION_TASKS = [
    BenchmarkTask(
        id="code-001",
        name="Fibonacci Function",
        category=Category.CODE_GENERATION,
        difficulty=Difficulty.EASY,
        description="Implement an efficient Fibonacci function with proper documentation.",
        task_prompt=(
            "Write a Python function that calculates the nth Fibonacci number efficiently. "
            "Requirements: 1) Handle n=0 and n=1 as base cases, 2) Use O(n) time and O(1) space, "
            "3) Include type hints, 4) Add docstring with examples, 5) Include 3 test cases using assert."
        ),
        evaluation_criteria=[
            "has_code:true",
            'keywords:def,fibonacci',
            'keywords:type hints,->',
            'pattern_match:assert.*fib',
            "min_length:150",
        ],
        expected_tools=[],
        expected_steps=1,
        max_turns=3,
        max_tokens=2048,
        timeout=30.0,
        tags=["code", "algorithms", "python"],
    ),
    BenchmarkTask(
        id="code-002",
        name="REST API Implementation",
        category=Category.CODE_GENERATION,
        difficulty=Difficulty.HARD,
        description="Implement a REST API with CRUD endpoints and error handling.",
        task_prompt=(
            "Write a complete FastAPI REST API for a task management system with these endpoints: "
            "POST /tasks - Create a task (title, description, priority, due_date), "
            "GET /tasks - List all tasks with optional priority filter, "
            "GET /tasks/{id} - Get a single task, "
            "PUT /tasks/{id} - Update a task, "
            "DELETE /tasks/{id} - Delete a task. "
            "Include: Pydantic models, proper HTTP status codes, error handling for 404, "
            "and an in-memory storage solution."
        ),
        evaluation_criteria=[
            "has_code:true",
            'keywords:FastAPI,POST,GET,PUT,DELETE',
            'keywords:Pydantic,BaseModel',
            "pattern_match:/tasks",
            "min_length:400",
        ],
        expected_tools=[],
        expected_steps=2,
        max_turns=5,
        max_tokens=4096,
        timeout=60.0,
        tags=["code", "api", "fastapi"],
    ),
    BenchmarkTask(
        id="code-003",
        name="Sorting Algorithm Suite",
        category=Category.CODE_GENERATION,
        difficulty=Difficulty.MEDIUM,
        description="Implement multiple sorting algorithms with complexity analysis.",
        task_prompt=(
            "Implement three sorting algorithms in Python: 1) QuickSort (in-place, Lomuto partition), "
            "2) MergeSort (returning new list), 3) HeapSort (using heapq). "
            "For each algorithm: provide the implementation with type hints, "
            "a docstring explaining the approach, time/space complexity in comments, "
            "and a simple correctness test with assert."
        ),
        evaluation_criteria=[
            "has_code:true",
            'keywords:quicksort,mergesort,heapsort',
            r"keywords:O\(n log n\)",
            'pattern_match:assert.*sort',
            "min_length:300",
        ],
        expected_tools=[],
        expected_steps=2,
        max_turns=5,
        max_tokens=4096,
        timeout=60.0,
        tags=["code", "algorithms", "sorting"],
    ),
    BenchmarkTask(
        id="code-004",
        name="Unit Test Writer",
        category=Category.CODE_GENERATION,
        difficulty=Difficulty.MEDIUM,
        description="Generate comprehensive unit tests for a given module.",
        task_prompt=(
            "Write comprehensive pytest unit tests for this Python class:\n\n"
            "```python\n"
            "class UserAccount:\n"
            "    def __init__(self, username: str, email: str):\n"
            "        self.username = username\n"
            "        self.email = email\n"
            "        self.balance = 0.0\n"
            "        self.is_active = True\n\n"
            "    def deposit(self, amount: float):\n"
            "        if amount <= 0: raise ValueError('Amount must be positive')\n"
            "        self.balance += amount\n\n"
            "    def withdraw(self, amount: float):\n"
            "        if amount <= 0: raise ValueError('Amount must be positive')\n"
            "        if amount > self.balance: raise ValueError('Insufficient funds')\n"
            "        self.balance -= amount\n\n"
            "    def deactivate(self):\n"
            "        self.is_active = False\n"
            "```\n\n"
            "Cover: happy paths, edge cases (zero/negative amounts, overdraft), "
            "deactivation behavior. Use pytest fixtures and parametrize where appropriate."
        ),
        evaluation_criteria=[
            "has_code:true",
            'keywords:pytest,test_,fixture',
            'keywords:ValueError,Insufficient',
            "pattern_match:@pytest",
            "min_length:300",
        ],
        expected_tools=[],
        expected_steps=1,
        max_turns=4,
        max_tokens=3072,
        timeout=45.0,
        tags=["code", "testing", "pytest"],
    ),
]


# ─── Recovery Tasks ──────────────────────────────────────────────────────────

RECOVERY_TASKS = [
    BenchmarkTask(
        id="recv-001",
        name="Tool Error Recovery",
        category=Category.RECOVERY,
        difficulty=Difficulty.MEDIUM,
        description="Recover gracefully when a tool returns an error.",
        task_prompt=(
            "Try to read a file called '/nonexistent/path/missing.txt'. When you get an error, "
            "handle it gracefully by: 1) Acknowledging the error, 2) Creating the directory structure, "
            "3) Creating the file with placeholder content 'This file was created during recovery', "
            "4) Reading it back to confirm. Report each step clearly."
        ),
        evaluation_criteria=[
            "tool_used:file_read",
            "tool_used:file_write",
            'keywords:error,created,recovery',
            "min_length:100",
        ],
        expected_tools=["file_read", "file_write"],
        expected_steps=4,
        max_turns=10,
        max_tokens=2048,
        timeout=30.0,
        tags=["recovery", "error-handling", "tools"],
    ),
    BenchmarkTask(
        id="recv-002",
        name="Code Error Recovery",
        category=Category.RECOVERY,
        difficulty=Difficulty.HARD,
        description="Debug and fix a buggy code snippet without being told what's wrong.",
        task_prompt=(
            "This Python function is supposed to find the median of a sorted list using binary search, "
            "but it has bugs. Find and fix ALL bugs without being told what they are:\n\n"
            "```python\n"
            "def find_median(sorted_list):\n"
            "    n = len(sorted_list)\n"
            "    if n == 0:\n"
            "        return None\n"
            "    if n % 2 == 1:\n"
            "        return sorted_list[n]  # Bug 1\n"
            "    else:\n"
            "        mid = n // 2\n"
            "        return sorted_list[mid - 1]  # Bug 2\n"
            "```\n\n"
            "Provide the corrected code and explain each bug you found."
        ),
        evaluation_criteria=[
            "has_code:true",
            'keywords:bug,fix,correct',
            "pattern_match:n - 1|n//2",
            "min_length:150",
        ],
        expected_tools=[],
        expected_steps=3,
        max_turns=8,
        max_tokens=3072,
        timeout=45.0,
        tags=["recovery", "debugging", "code"],
    ),
    BenchmarkTask(
        id="recv-003",
        name="Ambiguous Request Handling",
        category=Category.RECOVERY,
        difficulty=Difficulty.MEDIUM,
        description="Handle a deliberately ambiguous request by asking clarifying questions.",
        task_prompt=(
            "I need you to 'fix the API'. That's all the information I'm giving you. "
            "Determine what additional information you need and ask specific, focused questions "
            "to clarify the request. Do NOT make assumptions - ask at least 3 specific questions "
            "about: what's broken, the tech stack, the expected behavior, and error messages."
        ),
        evaluation_criteria=[
            'keywords:question,clarif',
            "pattern_match:\\?",
            "min_length:100",
        ],
        expected_tools=[],
        expected_steps=2,
        max_turns=4,
        max_tokens=2048,
        timeout=30.0,
        tags=["recovery", "clarification", "communication"],
    ),
]


# ─── Memory Tasks ────────────────────────────────────────────────────────────

MEMORY_TASKS = [
    BenchmarkTask(
        id="mem-001",
        name="Cross-Session Recall",
        category=Category.MEMORY,
        difficulty=Difficulty.HARD,
        description="Recall information from earlier in the conversation.",
        task_prompt=(
            "I'm going to give you some information to remember, then ask you questions about it later.\n\n"
            "INFORMATION TO REMEMBER:\n"
            "- Project: Aion Hand\n"
            "- Lead Developer: Sarah Chen\n"
            "- Tech Stack: Python, Rust, TypeScript\n"
            "- Current Sprint: Sprint 14\n"
            "- Key Feature: Benchmark Engine\n"
            "- Deadline: March 15, 2025\n\n"
            "Now, answer these questions using ONLY the information above:\n"
            "1) Who is the lead developer? 2) What sprint are we in? "
            "3) What is the key feature being developed? 4) When is the deadline? "
            "5) What are the three languages in the tech stack?"
        ),
        evaluation_criteria=[
            'keywords:Sarah Chen',
            'keywords:Sprint 14',
            'keywords:March 15',
            'keywords:Python,Rust,TypeScript',
            'keywords:Benchmark Engine',
        ],
        expected_tools=[],
        expected_steps=1,
        max_turns=3,
        max_tokens=2048,
        timeout=30.0,
        tags=["memory", "recall"],
    ),
    BenchmarkTask(
        id="mem-002",
        name="Fact Consistency Check",
        category=Category.MEMORY,
        difficulty=Difficulty.MEDIUM,
        description="Maintain consistent facts across a multi-turn conversation.",
        task_prompt=(
            "Let's work through a scenario. Follow each instruction carefully:\n\n"
            "Step 1: I have 3 cats named Luna, Milo, and Nala.\n"
            "Step 2: Luna is 3 years old, Milo is 5, and Nala is 2.\n"
            "Step 3: Milo and Nala are siblings.\n"
            "Step 4: I adopted Luna last year.\n"
            "Step 5: Nala is the youngest.\n\n"
            "Now summarize ALL the facts above in a structured list. "
            "Then answer: Which cat is the oldest? Which cats are related? "
            "How old was Luna when adopted?"
        ),
        evaluation_criteria=[
            'keywords:Luna,Milo,Nala',
            'keywords:sibling,oldest,youngest',
            "min_length:150",
        ],
        expected_tools=[],
        expected_steps=2,
        max_turns=5,
        max_tokens=2048,
        timeout=30.0,
        tags=["memory", "consistency", "reasoning"],
    ),
    BenchmarkTask(
        id="mem-003",
        name="Preference Learning",
        category=Category.MEMORY,
        difficulty=Difficulty.MEDIUM,
        description="Learn and apply user preferences stated across the conversation.",
        task_prompt=(
            "I have some preferences for how you should write code for me:\n\n"
            "1. I prefer functional style over OOP when possible\n"
            "2. Always use type hints\n"
            "3. I hate single-letter variable names except for 'i' and 'j' in loops\n"
            "4. Use snake_case for everything\n"
            "5. Always include a module docstring\n\n"
            "Now write a function that takes a list of strings and returns the unique ones, "
            "sorted by length. Apply ALL my preferences."
        ),
        evaluation_criteria=[
            "has_code:true",
            r"pattern_match:\->\s*(list|List)",
            "min_length:100",
            'keywords:def,return',
        ],
        expected_tools=[],
        expected_steps=2,
        max_turns=4,
        max_tokens=2048,
        timeout=30.0,
        tags=["memory", "preferences", "code"],
    ),
]


# ─── Multi-Step Tasks ────────────────────────────────────────────────────────

MULTI_STEP_TASKS = [
    BenchmarkTask(
        id="multi-001",
        name="Research and Report",
        category=Category.MULTI_STEP,
        difficulty=Difficulty.HARD,
        description="Research a topic, synthesize findings, and produce a formatted report.",
        task_prompt=(
            "Produce a mini research report on 'LLM Context Window Techniques'. Steps:\n"
            "1) Identify the main techniques (RAG, summarization, sliding window, etc.), "
            "2) For each technique, note pros and cons, "
            "3) Compare them in a summary table, "
            "4) Give a recommendation for a chat application with 100K token limit.\n\n"
            "Format the report with headers and a comparison table."
        ),
        evaluation_criteria=[
            "min_length:400",
            'keywords:RAG,summarization',
            'keywords:context,window,token',
            'pattern_match:##|###',
        ],
        expected_tools=[],
        expected_steps=4,
        max_turns=8,
        max_tokens=4096,
        timeout=60.0,
        tags=["multi-step", "research", "report"],
    ),
    BenchmarkTask(
        id="multi-002",
        name="Data Pipeline Construction",
        category=Category.MULTI_STEP,
        difficulty=Difficulty.EXPERT,
        description="Design and implement a data processing pipeline with multiple stages.",
        task_prompt=(
            "Design and implement a Python data pipeline that: 1) Generates 1000 random user records "
            "(name, email, age, score) using Faker, 2) Filters out users under 18, "
            "3) Normalizes scores to 0-100 range, 4) Groups by age bracket (18-25, 26-35, 36-50, 50+), "
            "5) Computes average score per bracket, 6) Writes results to a CSV file. "
            "Use functional-style Python. Include the full runnable code."
        ),
        evaluation_criteria=[
            "has_code:true",
            'keywords:Faker,filter,group',
            'keywords:CSV,normalize,average',
            "pattern_match:import.*csv|to_csv",
            "min_length:300",
        ],
        expected_tools=[],
        expected_steps=3,
        max_turns=6,
        max_tokens=4096,
        timeout=60.0,
        tags=["multi-step", "data", "pipeline", "code"],
    ),
    BenchmarkTask(
        id="multi-003",
        name="Code Review and Improvement",
        category=Category.MULTI_STEP,
        difficulty=Difficulty.HARD,
        description="Review code, identify issues, and provide an improved version.",
        task_prompt=(
            "Perform a thorough code review of this function, then provide an improved version:\n\n"
            "```python\n"
            "def process_data(data):\n"
            "    result = []\n"
            "    for i in range(len(data)):\n"
            "        if data[i]['age'] > 18 and data[i]['score'] > 50:\n"
            "            result.append(data[i]['name'].upper())\n"
            "        elif data[i]['age'] > 18:\n"
            "            result.append(data[i]['name'])\n"
            "    return result\n"
            "```\n\n"
            "Your review should: 1) List at least 3 issues (style, performance, robustness), "
            "2) Explain why each is an issue, 3) Provide the rewritten function, "
            "4) Explain what you changed and why."
        ),
        evaluation_criteria=[
            "has_code:true",
            'keywords:review,issue,improve',
            'keywords:comprehension|list comp',
            "min_length:250",
        ],
        expected_tools=[],
        expected_steps=3,
        max_turns=6,
        max_tokens=4096,
        timeout=45.0,
        tags=["multi-step", "review", "code"],
    ),
    BenchmarkTask(
        id="multi-004",
        name="Systematic Debugging",
        category=Category.MULTI_STEP,
        difficulty=Difficulty.EXPERT,
        description="Systematically debug a complex multi-function program.",
        task_prompt=(
            "Debug this program that should calculate word frequency statistics but produces wrong results:\n\n"
            "```python\n"
            "import re\n\n"
            "def tokenize(text):\n"
            "    return re.split(r'\\s+', text.lower())\n\n"
            "def count_words(tokens):\n"
            "    counts = {}\n"
            "    for word in tokens:\n"
            "        counts[word] = counts.get(word, 0) + 1\n"
            "    return counts\n\n"
            "def get_top_n(counts, n=5):\n"
            "    return sorted(counts.items(), key=lambda x: x[1])[:n]\n\n"
            "def analyze(text):\n"
            "    tokens = tokenize(text)\n"
            "    counts = count_words(tokens)\n"
            "    return get_top_n(counts)\n"
            "```\n\n"
            "Bug 1: tokenize doesn't strip punctuation. Bug 2: get_top_n returns lowest, not highest. "
            "Bug 3: empty strings from multiple spaces. Find all bugs, explain them, and provide the fix."
        ),
        evaluation_criteria=[
            "has_code:true",
            'keywords:bug,punctuation,sorted,reverse',
            'keywords:tokenize,fix,strip',
            "min_length:200",
        ],
        expected_tools=[],
        expected_steps=3,
        max_turns=6,
        max_tokens=3072,
        timeout=45.0,
        tags=["multi-step", "debugging", "code"],
    ),
]


# ─── Master Task List ────────────────────────────────────────────────────────

BENCHMARK_TASKS: list[BenchmarkTask] = [
    *PLANNING_TASKS,
    *TOOL_USE_TASKS,
    *CODE_GENERATION_TASKS,
    *RECOVERY_TASKS,
    *MEMORY_TASKS,
    *MULTI_STEP_TASKS,
]


def get_tasks_by_category(category: Category | str) -> list[BenchmarkTask]:
    """Return all tasks matching a given category."""
    if isinstance(category, str):
        category = Category(category.lower())
    return [t for t in BENCHMARK_TASKS if t.category == category]


def get_tasks_by_difficulty(difficulty: Difficulty | str) -> list[BenchmarkTask]:
    """Return all tasks matching a given difficulty level."""
    if isinstance(difficulty, str):
        difficulty = Difficulty(difficulty.lower())
    return [t for t in BENCHMARK_TASKS if t.difficulty == difficulty]


__all__ = [
    "BenchmarkTask",
    "BENCHMARK_TASKS",
    "Category",
    "Difficulty",
    "get_tasks_by_category",
    "get_tasks_by_difficulty",
    "PLANNING_TASKS",
    "TOOL_USE_TASKS",
    "CODE_GENERATION_TASKS",
    "RECOVERY_TASKS",
    "MEMORY_TASKS",
    "MULTI_STEP_TASKS",
]
