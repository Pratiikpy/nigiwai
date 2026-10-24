import type { Metadata } from "next";
import { ForgotForm } from "@/components/auth/ForgotForm";

export const metadata: Metadata = { title: "Forgot your password", robots: { index: false, follow: false } };

export default function ForgotPage() {
  return <ForgotForm />;
}
