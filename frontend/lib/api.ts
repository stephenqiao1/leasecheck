// Typed client for the LeaseCheck FastAPI backend.
// Types mirror the JSON shapes in backend/app/main.py.

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type Verdict = "ok" | "violation" | "unclear";
export type FindingStatus = "accepted" | "dismissed" | "pending";

// A clause's finding as returned by GET /documents/{id}/review-view.
export interface Finding {
  id: string;
  verdict: Verdict;
  rule_code: string | null;
  rule_title: string | null;
  rationale: string;
  status: FindingStatus;
}

export interface Clause {
  id: string;
  ordinal: number;
  text: string;
  finding: Finding | null;
}

export interface ReviewView {
  document_id: string;
  filename: string;
  jurisdiction: string;
  status: string;
  clause_count: number;
  violation_count: number;
  clauses: Clause[];
}

// Shape returned by PATCH /findings/{id} (note: no rule_title, includes clause_id).
export interface UpdatedFinding {
  id: string;
  clause_id: string;
  verdict: Verdict;
  rule_code: string | null;
  rationale: string;
  status: FindingStatus;
}

export async function getReviewView(documentId: string): Promise<ReviewView> {
  const res = await fetch(`${API_URL}/documents/${documentId}/review-view`);
  if (!res.ok) {
    throw new Error(`getReviewView failed: ${res.status} ${res.statusText}`);
  }
  return res.json();
}

export async function updateFindingStatus(
  findingId: string,
  status: FindingStatus,
): Promise<UpdatedFinding> {
  const res = await fetch(`${API_URL}/findings/${findingId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status }),
  });
  if (!res.ok) {
    throw new Error(`updateFindingStatus failed: ${res.status} ${res.statusText}`);
  }
  return res.json();
}
