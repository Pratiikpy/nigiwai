import Link from "next/link";
import { Logo } from "@/components/Logo";

export default function Home() {
  return (
    <main className="auth">
      <div className="auth__card card">
        <Logo />
        <h1 className="display">Read the crowd you already have.</h1>
        <p className="muted">Nigiwai turns what your guests say they love into decisions for your venue.</p>
        <div className="row row--wrap">
          <Link className="btn btn--primary" href="/signup">
            Create an account
          </Link>
          <Link className="btn" href="/login">
            Sign in
          </Link>
        </div>
      </div>
    </main>
  );
}
