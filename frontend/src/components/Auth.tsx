/** Phase 9 - sign in / sign up / password reset for an individual teacher. */
import { useEffect, useState } from "react";
import { api } from "../api";
import type { AuthUser } from "../types";

export type AuthPage = "login" | "signup" | "forgot" | "reset";

const GRADES = [
  "PP1", "PP2", "Grade 1", "Grade 2", "Grade 3", "Grade 4", "Grade 5", "Grade 6",
  "Grade 7", "Grade 8", "Grade 9",
];
const SUBJECTS = [
  "Mathematics", "English", "Kiswahili", "Science & Technology", "Agriculture",
  "Home Science", "Social Studies", "Religious Education", "Creative Arts", "Physical & Health Education",
];

function pageFromHash(): AuthPage {
  const h = window.location.hash;
  if (h.startsWith("#/signup")) return "signup";
  if (h.startsWith("#/forgot")) return "forgot";
  if (h.startsWith("#/reset")) return "reset";
  return "login";
}

function nextPath(): string {
  const q = new URLSearchParams(window.location.hash.split("?")[1] || "");
  const next = q.get("next") || "";
  return next.startsWith("/") && !next.startsWith("//") ? next : "/review";
}

interface Props {
  onSignedIn: (user: AuthUser) => void;
  onError: (msg: string) => void;
}

export default function Auth({ onSignedIn, onError }: Props) {
  const [page, setPage] = useState<AuthPage>(pageFromHash);
  const [busy, setBusy] = useState(false);
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [remember, setRemember] = useState(false);
  const [tscNo, setTscNo] = useState("");
  const [county, setCounty] = useState("");
  const [grades, setGrades] = useState<string[]>([]);
  const [subjects, setSubjects] = useState<string[]>([]);
  const [token, setToken] = useState(() => new URLSearchParams(window.location.hash.split("?")[1] || "").get("token") || "");
  const [notice, setNotice] = useState("");
  const [link, setLink] = useState("");

  useEffect(() => {
    const onHash = () => setPage(pageFromHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  const go = (p: AuthPage) => {
    window.location.hash = `#/${p === "forgot" ? "forgot-password" : p === "reset" ? "reset-password" : p}`;
    setPage(p);
    setNotice("");
  };

  const toggle = (value: string, list: string[], set: (v: string[]) => void) =>
    set(list.includes(value) ? list.filter((x) => x !== value) : [...list, value]);

  const submit = async () => {
    setBusy(true);
    setNotice("");
    try {
      if (page === "login") {
        const user = await api.login({ email, password, remember });
        onSignedIn(user);
        window.location.hash = `#${nextPath()}`;
        return;
      }
      if (page === "signup") {
        const user = await api.signup({
          name, email, password, tscNo, county, grades, subjects,
        });
        onSignedIn(user);
        window.location.hash = "#/review";
        return;
      }
      if (page === "forgot") {
        const result = await api.forgot(email);
        setNotice(result.message || "If that account exists, a reset link has been created.");
        setLink(result.resetUrl || "");
        return;
      }
      await api.reset(token, password);
      setNotice("Password updated. You can sign in now.");
      setPassword("");
      setPage("login");
      window.location.hash = "#/login";
    } catch (e) {
      const message = (e as Error).message;
      setNotice(message);
      onError(message);
    } finally {
      setBusy(false);
    }
  };

  const title = page === "login" ? "Welcome back" : page === "signup"
    ? "Create your My Space" : page === "forgot" ? "Reset your password" : "Choose a new password";

  return (
    <div className="flex min-h-screen items-start justify-center bg-[#F5F8F6] px-4 py-12">
      <div className="w-full max-w-lg">
        <div className="mb-6 text-center">
          <p className="section-label">Mwalimu Studio</p>
          <h1 className="mt-1 text-2xl font-extrabold text-brand-800">My Space</h1>
          <p className="mt-1 text-xs text-muted">One teacher. One private workspace. Your data stays yours.</p>
        </div>

        <div className="card space-y-4">
          <div>
            <h2 className="text-lg font-bold">{title}</h2>
            {page === "login" ? (
              <p className="mt-1 text-xs text-muted">
                Sign in with your own email to open your workspace. Nothing is shared with other teachers.
              </p>
            ) : null}
          </div>

          {(page === "login" || page === "signup") ? (
            <label className="block">
              <span className="field-label">Email *</span>
              <input className="input mt-1 w-full" type="email" value={email}
                onChange={(e) => setEmail(e.target.value)} data-testid="auth-email" />
            </label>
          ) : null}

          {page === "login" || page === "signup" || page === "reset" ? (
            <label className="block">
              <span className="field-label">{page === "reset" ? "New password" : "Password"}</span>
              <input className="input mt-1 w-full" type="password" value={password}
                onChange={(e) => setPassword(e.target.value)} data-testid="auth-password"
                placeholder={page === "login" ? "" : "At least 8 characters and 1 number"} />
            </label>
          ) : null}

          {page === "signup" ? (
            <>
              <label className="block">
                <span className="field-label">Full Name *</span>
                <input className="input mt-1 w-full" value={name} onChange={(e) => setName(e.target.value)}
                  data-testid="auth-name" />
              </label>
              <div className="grid grid-cols-2 gap-3">
                <label className="block">
                  <span className="field-label">TSC No (optional)</span>
                  <input className="input mt-1 w-full" value={tscNo} onChange={(e) => setTscNo(e.target.value)} />
                </label>
                <label className="block">
                  <span className="field-label">County (optional)</span>
                  <input className="input mt-1 w-full" value={county} onChange={(e) => setCounty(e.target.value)} />
                </label>
              </div>
              <div>
                <span className="field-label">Grade(s) taught</span>
                <div className="mt-1 flex flex-wrap gap-1.5">
                  {GRADES.map((g) => (
                    <button key={g} type="button"
                      className={`btn-mini ${grades.includes(g) ? "!bg-brand-600 !text-white" : ""}`}
                      onClick={() => toggle(g, grades, setGrades)}>{g}</button>
                  ))}
                </div>
              </div>
              <div>
                <span className="field-label">Subject(s)</span>
                <div className="mt-1 flex flex-wrap gap-1.5">
                  {SUBJECTS.map((s) => (
                    <button key={s} type="button"
                      className={`btn-mini ${subjects.includes(s) ? "!bg-brand-600 !text-white" : ""}`}
                      onClick={() => toggle(s, subjects, setSubjects)}>{s}</button>
                  ))}
                </div>
              </div>
            </>
          ) : null}

          {page === "login" ? (
            <label className="flex items-center gap-2 text-xs text-muted">
              <input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)}
                data-testid="auth-remember" />
              Remember me for 30 days on this device
            </label>
          ) : null}

          {page === "forgot" ? (
            <label className="block">
              <span className="field-label">Email</span>
              <input className="input mt-1 w-full" type="email" value={email}
                onChange={(e) => setEmail(e.target.value)} data-testid="auth-email" />
            </label>
          ) : null}

          {page === "reset" ? (
            <label className="block">
              <span className="field-label">Reset token</span>
              <input className="input mt-1 w-full" value={token} onChange={(e) => setToken(e.target.value)}
                data-testid="auth-token" />
            </label>
          ) : null}

          {notice ? (
            <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900">
              {notice}
              {link ? (
                <a className="ml-2 underline" href={`#${link}`}>Open reset link</a>
              ) : null}
            </div>
          ) : null}

          <button className="btn-primary w-full" disabled={busy} onClick={submit}
            data-testid="auth-submit">
            {busy ? "Working…" : page === "login" ? "Sign in" : page === "signup"
              ? "Create My Space" : page === "forgot" ? "Create reset link" : "Set new password"}
          </button>

          <div className="flex flex-wrap justify-between gap-2 text-xs text-brand-700">
            {page !== "login" ? (
              <button className="underline" onClick={() => go("login")}>Back to sign in</button>
            ) : (
              <>
                <button className="underline" onClick={() => go("forgot")}>Forgot password?</button>
                <button className="underline" onClick={() => go("signup")}>Create an account</button>
              </>
            )}
          </div>

          {page === "login" ? (
            <p className="border-t border-line pt-3 text-[11px] leading-relaxed text-muted">
              Migrated workspace from before accounts? Sign in with <code>teacher@local</code> and{" "}
              <code>Teacher123</code>, then confirm your details in My Space to secure it.
            </p>
          ) : null}
        </div>
      </div>
    </div>
  );
}
