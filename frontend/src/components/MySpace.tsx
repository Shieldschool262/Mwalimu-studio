/** Phase 9 - My Space: profile, preferences, data export, account removal. */
import { useState } from "react";
import { api } from "../api";
import type { AuthUser } from "../types";

const GRADES = [
  "PP1", "PP2", "Grade 1", "Grade 2", "Grade 3", "Grade 4", "Grade 5", "Grade 6",
  "Grade 7", "Grade 8", "Grade 9",
];
const SUBJECTS = [
  "Mathematics", "English", "Kiswahili", "Science & Technology", "Agriculture",
  "Home Science", "Social Studies", "Religious Education", "Creative Arts", "Physical & Health Education",
];

interface Props {
  user: AuthUser;
  onUpdated: (user: AuthUser) => void;
  onLogout: () => void;
  onToast: (msg: string) => void;
  onError: (msg: string) => void;
  /** True when opened from the first-login migration banner. */
  confirmRequired?: boolean;
}

export default function MySpace({ user, onUpdated, onLogout, onToast, onError, confirmRequired }: Props) {
  const [editing, setEditing] = useState(Boolean(confirmRequired));
  const [name, setName] = useState(user.name);
  const [email, setEmail] = useState(user.email);
  const [tscNo, setTscNo] = useState(user.tscNo);
  const [county, setCounty] = useState(user.county);
  const [schoolName, setSchoolName] = useState(user.schoolName);
  const [grades, setGrades] = useState<string[]>(user.grades);
  const [subjects, setSubjects] = useState<string[]>(user.subjects);
  const [prefs, setPrefs] = useState(user.preferences || {});
  const [busy, setBusy] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [confirmation, setConfirmation] = useState("");
  const [pwOpen, setPwOpen] = useState(false);
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");

  const toggle = (value: string, list: string[], set: (v: string[]) => void) =>
    set(list.includes(value) ? list.filter((x) => x !== value) : [...list, value]);

  const saveProfile = async () => {
    setBusy(true);
    try {
      const updated = await api.updateMe({
        name, email, tscNo, county, schoolName, grades, subjects, preferences: prefs,
      });
      onUpdated(updated);
      setEditing(false);
      onToast("My Space profile saved.");
    } catch (e) {
      onError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const savePrefs = async () => {
    setBusy(true);
    try {
      const updated = await api.updateMe({ preferences: prefs });
      onUpdated(updated);
      onToast("Preferences saved for your workspace.");
    } catch (e) {
      onError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const changePassword = async () => {
    setBusy(true);
    try {
      await api.changePassword(currentPassword, newPassword);
      setPwOpen(false);
      setCurrentPassword("");
      setNewPassword("");
      onToast("Password changed.");
    } catch (e) {
      onError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const deleteAccount = async () => {
    setBusy(true);
    try {
      await api.deleteMe(confirmation);
      setDeleteOpen(false);
      onToast("My Space and all its content were deleted.");
      onLogout();
    } catch (e) {
      onError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mx-auto max-w-4xl space-y-4" data-testid="my-space">
      <div className="card">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="section-label">Private workspace</p>
            <h1 className="text-xl font-extrabold">My Space • {user.name}</h1>
            <p className="mt-1 text-xs text-muted">
              Only you can see this space. Profile changes here never alter your Schemes or Lesson Plans.
            </p>
          </div>
          <button className="btn-ghost" data-testid="my-space-logout" onClick={onLogout}>Logout</button>
        </div>
      </div>

      {confirmRequired ? (
        <div className="rounded-lg border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900">
          Welcome to My Space! Please confirm your Name and Email to secure your space.
        </div>
      ) : null}

      <section className="card space-y-3 scroll-mt-32" id="my-profile">
        <div className="flex items-center justify-between">
          <h2 className="text-base font-bold">1. My Profile</h2>
          {!editing ? (
            <button className="btn-mini" data-testid="profile-edit" onClick={() => setEditing(true)}>Edit</button>
          ) : null}
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="block">
            <span className="field-label">Full Name</span>
            <input className="input mt-1 w-full" value={name} disabled={!editing}
              data-testid="profile-name" onChange={(e) => setName(e.target.value)} />
          </label>
          <label className="block">
            <span className="field-label">Email</span>
            <input className="input mt-1 w-full" type="email" value={email} disabled={!editing}
              data-testid="profile-email" onChange={(e) => setEmail(e.target.value)} />
          </label>
          <label className="block">
            <span className="field-label">TSC No</span>
            <input className="input mt-1 w-full" value={tscNo} disabled={!editing}
              data-testid="profile-tsc" onChange={(e) => setTscNo(e.target.value)} />
          </label>
          <label className="block">
            <span className="field-label">County</span>
            <input className="input mt-1 w-full" value={county} disabled={!editing}
              onChange={(e) => setCounty(e.target.value)} />
          </label>
          <label className="block sm:col-span-2">
            <span className="field-label">School Name (optional - printed on your cover page only)</span>
            <input className="input mt-1 w-full" value={schoolName} disabled={!editing}
              data-testid="profile-school" onChange={(e) => setSchoolName(e.target.value)}
              placeholder="Leave blank for a handwriting line" />
          </label>
        </div>
        <div>
          <span className="field-label">Grades taught</span>
          <div className="mt-1 flex flex-wrap gap-1.5">
            {GRADES.map((g) => (
              <button key={g} type="button" disabled={!editing}
                className={`btn-mini ${grades.includes(g) ? "!bg-brand-600 !text-white" : ""}`}
                onClick={() => toggle(g, grades, setGrades)}>{g}</button>
            ))}
          </div>
        </div>
        <div>
          <span className="field-label">Subjects</span>
          <div className="mt-1 flex flex-wrap gap-1.5">
            {SUBJECTS.map((s) => (
              <button key={s} type="button" disabled={!editing}
                className={`btn-mini ${subjects.includes(s) ? "!bg-brand-600 !text-white" : ""}`}
                onClick={() => toggle(s, subjects, setSubjects)}>{s}</button>
            ))}
          </div>
        </div>
        {editing ? (
          <div className="flex gap-2">
            <button className="btn-primary" disabled={busy} data-testid="profile-save" onClick={saveProfile}>Save</button>
            <button className="btn-ghost" onClick={() => {
              setEditing(false);
              setName(user.name); setEmail(user.email); setTscNo(user.tscNo);
              setCounty(user.county); setSchoolName(user.schoolName);
              setGrades(user.grades); setSubjects(user.subjects);
            }}>Cancel</button>
          </div>
        ) : null}
      </section>

      <section className="card space-y-3 scroll-mt-32" id="my-preferences">
        <h2 className="text-base font-bold">2. My Preferences</h2>
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="block">
            <span className="field-label">Default Term</span>
            <select className="input mt-1 w-full" value={prefs.defaultTerm || "Term 1"}
              onChange={(e) => setPrefs({ ...prefs, defaultTerm: e.target.value })}>
              <option>Term 1</option><option>Term 2</option><option>Term 3</option>
            </select>
          </label>
          <label className="block">
            <span className="field-label">Default Year</span>
            <input className="input mt-1 w-full" type="number" value={prefs.defaultYear || new Date().getFullYear()}
              onChange={(e) => setPrefs({ ...prefs, defaultYear: e.target.value })} />
          </label>
          <label className="block">
            <span className="field-label">Font size for Notes</span>
            <select className="input mt-1 w-full" value={prefs.notesFontSize || 16}
              onChange={(e) => setPrefs({ ...prefs, notesFontSize: Number(e.target.value) })}>
              <option value={16}>16</option><option value={18}>18</option><option value={20}>20</option>
            </select>
          </label>
          <label className="flex items-end gap-2 pb-2 text-xs text-muted">
            <input type="checkbox" checked={Boolean(prefs.answersInNotesPdf)}
              onChange={(e) => setPrefs({ ...prefs, answersInNotesPdf: e.target.checked })} />
            Answers in Notes PDF (off by default)
          </label>
        </div>
        <button className="btn-primary" disabled={busy} data-testid="prefs-save" onClick={savePrefs}>Save preferences</button>
      </section>

      <section className="card space-y-2 scroll-mt-32" id="my-data">
        <h2 className="text-base font-bold">3. My Data</h2>
        <p className="text-xs text-muted">
          Take everything with you: Designs, Schemes, Lesson Plans, Notes, ROW, Exports, My Learners,
          Assessments, IEPs and a manifest, in one ZIP. Only your own workspace is included.
        </p>
        <p className="mt-1 text-xs text-rose-700">
          This ZIP contains learner names. Keep it private. Do NOT share it publicly.
        </p>
        <a className="btn-ghost inline-flex" data-testid="export-all"
          href={api.exportAllUrl()} download>
          ⬇ Export All My Data (ZIP)
        </a>
      </section>

      <section className="card space-y-3 border-rose-200 scroll-mt-32" id="danger-zone">
        <h2 className="text-base font-bold text-rose-700">4. Danger Zone</h2>
        <div className="flex flex-wrap gap-2">
          <button className="btn-ghost" data-testid="change-password" onClick={() => setPwOpen(true)}>
            Change Password
          </button>
          <button className="btn-ghost !border-rose-300 !text-rose-700" data-testid="delete-account"
            onClick={() => setDeleteOpen(true)}>
            Delete My Account
          </button>
        </div>
      </section>

      {pwOpen ? (
        <div className="card space-y-3" data-testid="password-panel">
          <h2 className="text-base font-bold">Change Password</h2>
          <label className="block">
            <span className="field-label">Current password</span>
            <input className="input mt-1 w-full" type="password" value={currentPassword}
              onChange={(e) => setCurrentPassword(e.target.value)} />
          </label>
          <label className="block">
            <span className="field-label">New password (8+ characters, 1 number)</span>
            <input className="input mt-1 w-full" type="password" value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)} data-testid="new-password" />
          </label>
          <div className="flex gap-2">
            <button className="btn-primary" disabled={busy} onClick={changePassword}>Save password</button>
            <button className="btn-ghost" onClick={() => setPwOpen(false)}>Cancel</button>
          </div>
        </div>
      ) : null}

      {deleteOpen ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4">
          <div className="w-full max-w-md rounded-lg bg-white p-5 shadow-xl" data-testid="delete-modal">
            <h3 className="text-base font-semibold text-slate-900">Delete My Space?</h3>
            <p className="mt-2 text-sm text-slate-600">
              This will permanently delete ALL your Designs, Schemes, Plans, Notes, ROW.
              This cannot be undone. Type DELETE to confirm.
            </p>
            <label className="mt-3 block">
              <span className="field-label">Type DELETE to confirm</span>
              <input className="input mt-1 w-full" value={confirmation}
                onChange={(e) => setConfirmation(e.target.value)} data-testid="delete-confirm" />
            </label>
            <div className="mt-4 flex justify-end gap-2">
              <button className="btn-ghost" onClick={() => { setDeleteOpen(false); setConfirmation(""); }}>
                Cancel
              </button>
              <button className="btn bg-rose-600 text-white hover:bg-rose-700"
                disabled={confirmation !== "DELETE" || busy} data-testid="delete-final"
                onClick={deleteAccount}>
                Delete
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
