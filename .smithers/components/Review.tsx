// smithers-source: seeded
/** @jsxImportSource smithers-orchestrator */
import { Parallel, Task, type AgentLike } from "smithers-orchestrator";
import { z } from "zod/v4";
import ReviewPrompt from "../prompts/review.mdx";

const reviewIssueSchema = z.object({
  severity: z.enum(["critical", "major", "minor", "nit"]),
  title: z.string(),
  file: z.string().nullable().default(null),
  description: z.string(),
});

export const reviewOutputSchema = z.object({
  reviewer: z.string(),
  approved: z.boolean(),
  feedback: z.string(),
  issues: z.array(reviewIssueSchema).default([]),
});

type ReviewProps = {
  idPrefix: string;
  prompt: unknown;
  agents: AgentLike[];
};

export function Review({ idPrefix, prompt, agents }: ReviewProps) {
  const promptText =
    typeof prompt === "string" ? prompt : JSON.stringify(prompt ?? null);
  // Build per-task fallback chains so a transient provider failure
  // (auth error, rate limit, circuit breaker) on one reviewer does not
  // kill the review — Task tries the list in order until one succeeds.
  // Task i uses agents[i] as primary and the rest as fallbacks.
  return (
    <Parallel>
      {agents.map((agent, index) => {
        const fallbacks = agents.filter((_, i) => i !== index);
        const chain = [agent, ...fallbacks];
        return (
          <Task
            key={`${idPrefix}:${index}`}
            id={`${idPrefix}:${index}`}
            output={reviewOutputSchema}
            agent={chain}
            continueOnFail
          >
            <ReviewPrompt
              reviewer={`reviewer-${index + 1}`}
              prompt={promptText}
            />
          </Task>
        );
      })}
    </Parallel>
  );
}
