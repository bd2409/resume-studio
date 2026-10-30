// A plain word-list check for US Fair Housing Act advertising risks
// (race, color, religion, sex, disability, familial status, national origin).
// It runs on every generated listing, no AI involved, so its result is the same
// every time. It flags words to review; it is not legal advice.

const RULES = [
  // Explicit preference or exclusion: almost always a problem.
  { re: /\b(adults? only|no (kids|children)|no families)\b/i, level: "high", why: "Excludes families with children (familial status)." },
  { re: /\b(bachelor pad|perfect for (a )?(young )?(couple|singles?|bachelor))\b/i, level: "high", why: "Describes the buyer instead of the home (familial status, sex)." },
  { re: /\b(christian|jewish|muslim|catholic) (home|community|neighbou?rhood|family)\b/i, level: "high", why: "States a religious preference." },
  { re: /\b(no (wheelchairs?|disabled|handicapped)|must be able to climb)\b/i, level: "high", why: "Excludes people with disabilities." },
  { re: /\b(white|black|hispanic|latino|asian|caucasian|ethnic|integrated|segregated) (neighbou?rhood|area|community)\b/i, level: "high", why: "Refers to the race or ethnicity of an area." },
  { re: /\b(english[- ]speaking only|americans only|no immigrants)\b/i, level: "high", why: "Excludes by national origin." },
  { re: /\b(ideal|perfect) for (retirees|seniors|empty[- ]nesters)\b/i, level: "high", why: "Describes the buyer by age or family status (fine only for legal 55+ housing)." },
  // Softer words that many MLSs and brokerages ask agents to avoid.
  { re: /\b(family[- ]friendly|great for families|perfect for families)\b/i, level: "review", why: "Can signal a preference for families; describe features instead (yard, nearby parks)." },
  { re: /\b(safe|crime[- ]free) (neighbou?rhood|area|community|street)\b/i, level: "review", why: "Safety claims are subjective and can steer buyers; cite facts or leave it out." },
  { re: /\bexclusive (neighbou?rhood|community|area)\b/i, level: "review", why: "Can imply that some people are not welcome." },
  { re: /\bmaster (bedroom|suite|bath)\b/i, level: "review", why: "Many MLSs now prefer 'primary bedroom' or 'primary suite'." },
  { re: /\b(handicap(ped)?)\b/i, level: "review", why: "Use 'accessible' and describe the feature." },
];

export function checkFairHousing(text) {
  const flags = [];
  for (const rule of RULES) {
    const match = text.match(rule.re);
    if (match) flags.push({ phrase: match[0], level: rule.level, why: rule.why });
  }
  return {
    ok: !flags.some((f) => f.level === "high"),
    flags,
  };
}
