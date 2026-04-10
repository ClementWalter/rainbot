// smithers-source: generated
import {
  ClaudeCodeAgent,
  CodexAgent,
  GeminiAgent,
  PiAgent,
  AmpAgent,
  type AgentLike,
} from "smithers-orchestrator";

export const providers = {
  claude: new ClaudeCodeAgent({ model: "claude-opus-4-6" }),
  codex: new CodexAgent({ model: "gpt-5.3-codex", skipGitRepoCheck: true }),
  gemini: new GeminiAgent({ model: "gemini-3.1-pro-preview" }),
  pi: new PiAgent({ provider: "openai", model: "gpt-5.3-codex" }),
  amp: new AmpAgent(),
  claudeSonnet: new ClaudeCodeAgent({ model: "claude-sonnet-4-6" }),
} as const;

export const agents = {
  cheapFast: [providers.claudeSonnet, providers.gemini],
  smart: [providers.codex, providers.claude, providers.gemini],
  smartTool: [providers.claude, providers.codex, providers.gemini],
} as const satisfies Record<string, AgentLike[]>;
