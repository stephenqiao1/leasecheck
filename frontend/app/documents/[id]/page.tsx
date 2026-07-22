import { getReviewView } from "@/lib/api";
import ReviewDocument from "./ReviewDocument";

// Dynamic route params are a Promise in Next.js and must be awaited.
export default async function DocumentPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const data = await getReviewView(id);
  return <ReviewDocument data={data} />;
}
