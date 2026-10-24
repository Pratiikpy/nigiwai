import { SharedBrief } from "./SharedBrief";

export default async function SharedBriefPage({ params }: { params: Promise<{ token: string }> }) {
  const { token } = await params;
  return <SharedBrief token={token} />;
}
