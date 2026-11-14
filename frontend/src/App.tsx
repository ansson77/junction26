import type { ReactNode } from "react";
import { NavLink, Route, Routes, useLocation, Link, Navigate, useParams } from "react-router-dom";
import Home from "./pages/Home";
import EspooLogo from "./components/EspooLogo";
import ApplicantFlow from "./pages/ApplicantFlow";
import EmployerFlow from "./pages/EmployerFlow";
import BizDevFlow from "./pages/BizDevFlow";
import Shortlist from "./pages/Shortlist";
import { ApplicantDetail, ApplicantList } from "./pages/Applicants";

/** Remount on every navigation, so "New profile" from the done step starts a fresh flow. */
function Fresh({ children }: { children: ReactNode }) {
  const { key } = useLocation();
  return <div key={key}>{children}</div>;
}

function JobRedirect() {
  const { id = "" } = useParams();
  return <Navigate to={`/shortlist/${encodeURIComponent(id)}`} replace />;
}

export default function App() {
  return (
    <>
      <a className="skip-link" href="#content">Skip to main content</a>
      <header className="topbar">
        <Link to="/" className="brand" aria-label="Skill Match Espoo – home">
          <EspooLogo className="brand-logo" />
          <span className="brand-name">Skill Match</span>
        </Link>
        <nav>
          <NavLink to="/applicant/new">Applicant</NavLink>
          <NavLink to="/employer/new">Employer</NavLink>
          <NavLink to="/bizdev">Business</NavLink>
          <NavLink to="/shortlist">Shortlist</NavLink>
          <NavLink to="/applicants">Applicants</NavLink>
        </nav>
      </header>
      <main id="content">
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/applicant/new" element={<Fresh><ApplicantFlow /></Fresh>} />
          <Route path="/employer/new" element={<Fresh><EmployerFlow /></Fresh>} />
          <Route path="/bizdev" element={<Fresh><BizDevFlow /></Fresh>} />
          <Route path="/shortlist" element={<Shortlist />} />
          <Route path="/shortlist/:id" element={<Shortlist />} />
          {/* The old Jobs pages live on as the shortlist; keep old links working. */}
          <Route path="/jobs" element={<Navigate to="/shortlist" replace />} />
          <Route path="/jobs/:id" element={<JobRedirect />} />
          <Route path="/applicants" element={<ApplicantList />} />
          <Route path="/applicants/:id" element={<ApplicantDetail />} />
          <Route path="*" element={<div className="page"><h1>Not found</h1><Link to="/">Home</Link></div>} />
        </Routes>
      </main>
      <footer className="footer">
        <div className="footer-inner">
          <EspooLogo className="footer-logo" />
          <p className="small">
            Junction 2026 · Skills from ESCO, © European Union · AI never evaluates people (EU AI Act, Annex III 4(a))
          </p>
        </div>
      </footer>
    </>
  );
}
