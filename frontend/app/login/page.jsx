import { Suspense } from "react";

import LoginForm from "@/components/LoginForm";

export const metadata = { title: "Log in · Vision AI" };

export default function LoginPage() {
  // useSearchParams() (reading ?next=) needs a Suspense boundary in the App Router.
  return (
    <main className="auth-page">
      <Suspense>
        <LoginForm />
      </Suspense>
    </main>
  );
}
