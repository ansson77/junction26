import { useState } from "react";

const same = (a: string, b: string) => a.toLocaleLowerCase() === b.toLocaleLowerCase();

/** Multi-select toggle chips for languages. With `allowOther`, any language can be typed in too. */
export default function LanguagePicker({
  options,
  selected,
  onChange,
  allowOther = false,
  label = "Languages",
}: {
  options: string[];
  selected: string[];
  onChange: (next: string[]) => void;
  allowOther?: boolean;
  label?: string;
}) {
  const [other, setOther] = useState("");
  const isOn = (lang: string) => selected.some((s) => same(s, lang));
  const toggle = (lang: string) =>
    onChange(isOn(lang) ? selected.filter((s) => !same(s, lang)) : [...selected, lang]);

  // Languages typed in by the applicant that aren't among the options still get a chip.
  const extra = selected.filter((s) => !options.some((o) => same(o, s)));

  const addOther = () => {
    const lang = other.trim().replace(/\s+/g, " ");
    if (!lang) return;
    const known = options.find((o) => same(o, lang));
    if (!isOn(lang)) onChange([...selected, known ?? lang]);
    setOther("");
  };

  return (
    <div className="lang-picker" role="group" aria-label={label}>
      <div className="lang-chips">
        {[...options, ...extra].map((lang) => (
          <button
            key={lang}
            type="button"
            className={`lang-chip ${isOn(lang) ? "on" : ""}`}
            aria-pressed={isOn(lang)}
            onClick={() => toggle(lang)}
          >
            {isOn(lang) && <span aria-hidden>✓ </span>}
            {lang}
          </button>
        ))}
      </div>
      {allowOther && (
        <form
          className="lang-other"
          onSubmit={(e) => {
            e.preventDefault();
            addOther();
          }}
        >
          <input
            type="text"
            value={other}
            maxLength={40}
            onChange={(e) => setOther(e.target.value)}
            placeholder="Another language, e.g. Tigrinya"
            aria-label="Add another language"
          />
          <button type="submit" className="btn small" disabled={!other.trim()}>
            Add
          </button>
        </form>
      )}
    </div>
  );
}
