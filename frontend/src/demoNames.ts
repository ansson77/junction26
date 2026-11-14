/**
 * DEMO ONLY: invented placeholder names for the shortlist's "show names" mode.
 *
 * Profiles store no identity at all (skills and points only), so these names are not real data.
 * Each is derived from the applicant id, so the same applicant always gets the same name.
 */

const FIRST = [
  "Aino", "Eero", "Laura", "Mikko", "Sara", "Juha", "Emilia", "Antti", "Noora", "Ville",
  "Fatima", "Ahmed", "Olga", "Dmitri", "Mei", "Wei", "Priya", "Arjun", "Sofia", "Mateo",
  "Amina", "Yusuf", "Hanna", "Tuomas", "Elina", "Oskari", "Leila", "Omar", "Anna", "Kalle",
];

const LAST = [
  "Virtanen", "Korhonen", "Mäkinen", "Nieminen", "Mäkelä", "Hämäläinen", "Laine", "Heikkinen",
  "Koskinen", "Järvinen", "Lehtonen", "Saarinen", "Ali", "Hassan", "Ivanova", "Petrov", "Chen",
  "Wang", "Sharma", "Patel", "García", "Rossi", "Nguyen", "Kim", "Lindqvist", "Nyberg",
];

/** FNV-1a string hash: small, fast and stable across browsers. */
function hash(s: string): number {
  let h = 0x811c9dc5;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  return h >>> 0;
}

export function demoName(applicantId: string): string {
  const h = hash(applicantId);
  return `${FIRST[h % FIRST.length]} ${LAST[Math.floor(h / FIRST.length) % LAST.length]}`;
}
